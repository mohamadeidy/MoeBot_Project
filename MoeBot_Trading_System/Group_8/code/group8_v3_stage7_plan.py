#!/usr/bin/env python3
"""Freeze an exact, fail-closed Group 8 V3 Stage 7 annual shard plan.

This planner performs no Stage 7 materialization. It consumes only PASS measurement
artifacts, recomputes exact 2023 work cardinality from read-only inputs, applies the
frozen causal-root bucket rule, and chooses power-of-two bucket counts until every
projected shard is below the frozen soft target under an explicit size safety factor.

Stage 7 is never auto-launched by this module.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import bucket_for_root, epoch_month, stable_hash
from group8_v3_stage7_shard_executor import Stage7SchoolCoreEngine, Stage7ShardSpec
from moebot_group8_engine_v0_8_0 import sha256_file

SOFT_TARGET_BYTES = 1_500_000_000
HARD_GUARD_BYTES = 2_500_000_000
EXPECTED_STORAGE_CONTRACT = "d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a"
EXPECTED_DESIGN_FREEZE = "213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git_head(artifacts_root: Path) -> str:
    repo = artifacts_root.resolve().parent.parent
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _verify_hash(record: dict[str, Any], field: str) -> None:
    saved = str(record.get(field, ""))
    payload = dict(record)
    payload.pop(field, None)
    if not saved or stable_hash(payload) != saved:
        raise RuntimeError(f"{field} mismatch")


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _status_active(status: str | None) -> bool:
    s = (status or "").lower()
    return not any(x in s for x in ("invalid", "expired", "broken", "deleted", "inactive"))


def _load_invalidators(staging: sqlite3.Connection) -> dict[str, list[int]]:
    by_zone: dict[str, list[int]] = defaultdict(list)
    for r in staging.execute(
        "SELECT zone_id,transition_time,to_status FROM group4__zone_transitions "
        "ORDER BY zone_id,transition_time,transition_id"
    ):
        if not _status_active(str(r["to_status"])):
            by_zone[str(r["zone_id"])].append(int(r["transition_time"]))
    for r in staging.execute(
        "SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions "
        "ORDER BY zone_id,interaction_time,interaction_id"
    ):
        if not _status_active(str(r["status_after"])):
            by_zone[str(r["zone_id"])].append(int(r["interaction_time"]))
    for v in by_zone.values():
        v.sort()
    return by_zone


def _first_after(times: list[int], t: int) -> int | None:
    i = bisect.bisect_right(times, int(t))
    return None if i >= len(times) else int(times[i])


def _choose_bucket_plan(
    roots: list[dict[str, Any]],
    *,
    bytes_for_root,
    size_safety_factor: float,
    soft_target_bytes: int = SOFT_TARGET_BYTES,
) -> tuple[int, list[dict[str, Any]]]:
    if not roots:
        return 1, []
    buckets = 1
    while True:
        agg: dict[int, dict[str, Any]] = {}
        for r in roots:
            b = bucket_for_root(str(r["root_id"]), buckets)
            x = agg.setdefault(b, {"bucket_index": b, "interpretations": 0, "evidence_chain_rows": 0, "logical_rows": 0, "measured_raw_bytes": 0.0})
            x["interpretations"] += int(r["interpretations"])
            x["evidence_chain_rows"] += int(r["evidence_chain_rows"])
            x["logical_rows"] += int(r["interpretations"]) + int(r["evidence_chain_rows"])
            x["measured_raw_bytes"] += float(bytes_for_root(r))
        out = []
        too_large = False
        for b in sorted(agg):
            x = agg[b]
            guarded = int(math.ceil(float(x["measured_raw_bytes"]) * float(size_safety_factor)))
            x["projected_raw_bytes"] = int(math.ceil(float(x["measured_raw_bytes"])))
            x["guarded_projected_raw_bytes"] = guarded
            if guarded > soft_target_bytes:
                too_large = True
            out.append(x)
        if not too_large:
            return buckets, out
        buckets *= 2
        if buckets > 4096:
            raise RuntimeError("unable to satisfy Stage 7 soft shard target with <=4096 buckets")


def _range_roots(
    *,
    staging: sqlite3.Connection,
    stage5: sqlite3.Connection,
    symbol: str,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    bars_by_key: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    bar_pos: dict[int, tuple[tuple[str, str], int]] = {}
    for r in staging.execute(
        "SELECT id,symbol,timeframe,available_at FROM source__bars WHERE symbol=? "
        "ORDER BY symbol,timeframe,available_at,id",
        (symbol,),
    ):
        key = (str(r["symbol"]), str(r["timeframe"]))
        idx = len(bars_by_key[key])
        bars_by_key[key].append((int(r["id"]), int(r["available_at"])))
        bar_pos[int(r["id"])] = (key, idx)
    avails = {k: [x[1] for x in v] for k, v in bars_by_key.items()}
    invalidators = _load_invalidators(staging)

    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rg in stage5.execute(
        """SELECT candidate_id,timeframe,source_bar_id,event_time,availability_time,features_json
           FROM price_action_pattern_candidate
           WHERE definition_id='pa_bounded_range_context' AND symbol=?
           ORDER BY timeframe,event_time,availability_time,candidate_id""",
        (symbol,),
    ):
        src_id = int(rg["source_bar_id"])
        if src_id not in bar_pos:
            raise RuntimeError(f"bounded range source bar missing:{rg['candidate_id']}")
        key, src_idx = bar_pos[src_id]
        availability = int(rg["availability_time"])
        left = max(src_idx, bisect.bisect_left(avails[key], availability))
        features = json.loads(str(rg["features_json"] or "{}"))
        cuts: list[int] = []
        for zid in (features.get("lower_zone_id"), features.get("upper_zone_id")):
            if not zid:
                continue
            t = _first_after(invalidators.get(str(zid), []), availability)
            if t is not None:
                cuts.append(t)
        cutoff = min(cuts) if cuts else None
        right = len(avails[key]) if cutoff is None else bisect.bisect_left(avails[key], cutoff)
        n = max(0, right - left)
        if n <= 0:
            continue
        tf = str(rg["timeframe"])
        month = epoch_month(int(rg["event_time"]))
        out[(tf, month)].append(
            {
                "root_id": str(rg["candidate_id"]),
                "interpretations": n,
                "evidence_chain_rows": 2 * n,
            }
        )
    return dict(out)


def _school_roots(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    work_root: Path,
    symbol: str,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    scratch_db = work_root / "stage7_plan_school_scratch.sqlite"
    scratch_cp = work_root / "stage7_plan_school_scratch.checkpoint.json"
    for p in (scratch_db, scratch_cp):
        if p.exists():
            p.unlink()
    # The spec is only a constructor vehicle; _iter_actions enumerates all current
    # frozen school-core actions before shard filtering is applied by this planner.
    spec = Stage7ShardSpec("school_core", 2023, symbol, "M1", "2023-01", 1, 0)
    eng = Stage7SchoolCoreEngine(
        staging_db=staging_db,
        output_db=scratch_db,
        artifacts_root=artifacts_root,
        year=2023,
        symbol=symbol,
        stage5_db=stage5_db,
        checkpoint_path=scratch_cp,
        shard_spec=spec,
        hard_guard_bytes=HARD_GUARD_BYTES,
    )
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    try:
        eng.verify_stage5_boundary()
        # Temporarily bypass the shard predicate so one causal scan inventories all roots.
        eng._belongs = lambda root_key, timeframe, root_time: True  # type: ignore[method-assign]
        for definition, kwargs in eng._iter_actions():
            refs = list(kwargs["upstream_refs"])
            if not refs:
                raise RuntimeError(f"{definition} emitted no mandatory evidence")
            first = refs[0]
            root_id = f"{first['source_group']}:{first['source_type']}:{first['source_id']}"
            root_time = first.get("event_time")
            if root_time is None:
                root_time = kwargs["event_time"]
            tf = str(first.get("timeframe") or kwargs["timeframe"])
            month = epoch_month(int(root_time))
            key = (tf, month, root_id)
            x = grouped.setdefault(
                key,
                {"root_id": root_id, "interpretations": 0, "evidence_chain_rows": 0},
            )
            x["interpretations"] += 1
            x["evidence_chain_rows"] += len(refs)
    finally:
        eng.close(commit=False)
        for p in (scratch_db, scratch_cp):
            if p.exists():
                p.unlink()
    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (tf, month, _), rec in grouped.items():
        out[(tf, month)].append(rec)
    return dict(out)


def build_plan(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    preflight_path: Path,
    premium_benchmark_path: Path,
    compression_gate_path: Path,
    school_benchmark_path: Path,
    work_root: Path,
    output_path: Path,
    expected_commit: str,
    symbol: str,
    size_safety_factor: float,
    disk_safety_floor_gb: float,
) -> dict[str, Any]:
    if _git_head(artifacts_root) != expected_commit:
        raise RuntimeError("Git HEAD does not match expected Stage 7 planning commit")
    contract = json.loads((artifacts_root / "SHARDED_STORAGE_CONTRACT.json").read_text())
    freeze = json.loads((artifacts_root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    if contract.get("storage_contract_hash") != EXPECTED_STORAGE_CONTRACT:
        raise RuntimeError("storage contract drift")
    if freeze.get("design_freeze_hash") != EXPECTED_DESIGN_FREEZE:
        raise RuntimeError("design freeze drift")

    pf = json.loads(preflight_path.read_text()); _verify_hash(pf, "report_hash")
    pb = json.loads(premium_benchmark_path.read_text()); _verify_hash(pb, "report_hash")
    cg = json.loads(compression_gate_path.read_text()); _verify_hash(cg, "report_hash")
    sb = json.loads(school_benchmark_path.read_text()); _verify_hash(sb, "report_hash")
    if any(x.get("status") != "PASS" for x in (pf, pb, cg, sb)):
        raise RuntimeError("all Stage 7 prerequisite reports must PASS")
    if not cg.get("storage_gate_pass") or not cg.get("lossless_roundtrip_verified"):
        raise RuntimeError("Stage 7 compression gate is not lossless PASS")
    if any(x.get("stage7_authorized") is not False for x in (pf, pb, cg, sb)):
        raise RuntimeError("prerequisite artifact unexpectedly authorizes Stage 7")

    stage5_sha = sha256_file(stage5_db)
    if any(x.get("stage5_database_sha256") not in (None, stage5_sha) for x in (pf, pb, sb)):
        raise RuntimeError("Stage 5 lineage drift in Stage 7 measurements")

    premium_bpi = float(pb["sample"]["bytes_per_interpretation_with_two_evidence_rows"])
    premium_ratio = float(cg["measured_compression_ratio"])
    school_bpl = float(sb["sample"]["bytes_per_logical_row"])
    school_ratio = float(sb["sample"]["compression_ratio"])

    staging = _ro(staging_db); stage5 = _ro(stage5_db)
    try:
        range_roots = _range_roots(staging=staging, stage5=stage5, symbol=symbol)
    finally:
        stage5.close(); staging.close()
    school_roots = _school_roots(
        staging_db=staging_db,
        stage5_db=stage5_db,
        artifacts_root=artifacts_root,
        work_root=work_root,
        symbol=symbol,
    )

    shards: list[dict[str, Any]] = []
    total_range_i = total_range_e = total_school_i = total_school_e = 0
    max_guarded = 0

    for (tf, month), roots in sorted(range_roots.items()):
        bucket_count, bucket_rows = _choose_bucket_plan(
            roots,
            bytes_for_root=lambda r: int(r["interpretations"]) * premium_bpi,
            size_safety_factor=size_safety_factor,
        )
        for b in bucket_rows:
            max_guarded = max(max_guarded, int(b["guarded_projected_raw_bytes"]))
            total_range_i += int(b["interpretations"]); total_range_e += int(b["evidence_chain_rows"])
            shards.append({
                "family": "range_chain", "year": 2023, "symbol": symbol,
                "timeframe": tf, "root_month": month,
                "bucket_count": bucket_count, "bucket_index": int(b["bucket_index"]),
                "interpretations": int(b["interpretations"]),
                "evidence_chain_rows": int(b["evidence_chain_rows"]),
                "logical_rows": int(b["logical_rows"]),
                "projected_raw_bytes": int(b["projected_raw_bytes"]),
                "guarded_projected_raw_bytes": int(b["guarded_projected_raw_bytes"]),
                "projected_compressed_bytes": int(math.ceil(int(b["projected_raw_bytes"]) / premium_ratio)),
            })

    for (tf, month), roots in sorted(school_roots.items()):
        bucket_count, bucket_rows = _choose_bucket_plan(
            roots,
            bytes_for_root=lambda r: (int(r["interpretations"]) + int(r["evidence_chain_rows"])) * school_bpl,
            size_safety_factor=size_safety_factor,
        )
        for b in bucket_rows:
            max_guarded = max(max_guarded, int(b["guarded_projected_raw_bytes"]))
            total_school_i += int(b["interpretations"]); total_school_e += int(b["evidence_chain_rows"])
            shards.append({
                "family": "school_core", "year": 2023, "symbol": symbol,
                "timeframe": tf, "root_month": month,
                "bucket_count": bucket_count, "bucket_index": int(b["bucket_index"]),
                "interpretations": int(b["interpretations"]),
                "evidence_chain_rows": int(b["evidence_chain_rows"]),
                "logical_rows": int(b["logical_rows"]),
                "projected_raw_bytes": int(b["projected_raw_bytes"]),
                "guarded_projected_raw_bytes": int(b["guarded_projected_raw_bytes"]),
                "projected_compressed_bytes": int(math.ceil(int(b["projected_raw_bytes"]) / school_ratio)),
            })

    expected = pf["definition_cardinality_current_engine"]
    expected_range = int(expected["ict_premium_discount_context"])
    expected_school = sum(int(expected[k]) for k in expected if k != "ict_premium_discount_context")
    blockers: list[str] = []
    if total_range_i != expected_range:
        blockers.append(f"range interpretation cardinality mismatch:{total_range_i}!={expected_range}")
    if total_school_i != expected_school:
        blockers.append(f"school interpretation cardinality mismatch:{total_school_i}!={expected_school}")
    if max_guarded > SOFT_TARGET_BYTES:
        blockers.append(f"guarded shard projection exceeds soft target:{max_guarded}")
    if any(int(s["guarded_projected_raw_bytes"]) > HARD_GUARD_BYTES for s in shards):
        blockers.append("at least one shard exceeds hard guard projection")

    projected_raw = sum(int(s["projected_raw_bytes"]) for s in shards)
    projected_compressed = sum(int(s["projected_compressed_bytes"]) for s in shards)
    guarded_raw = sum(int(s["guarded_projected_raw_bytes"]) for s in shards)
    # Compression safety is already established on measured samples; reserve the
    # explicit size-safety factor again for annual aggregate compressed storage.
    guarded_compressed = int(math.ceil(projected_compressed * size_safety_factor))
    disk = os.statvfs(str(output_path.parent)) if hasattr(os, "statvfs") else None
    if disk is None:
        import shutil
        usage = shutil.disk_usage(output_path.parent)
        free = int(usage.free)
    else:
        free = int(disk.f_bavail * disk.f_frsize)
    floor = int(float(disk_safety_floor_gb) * (1024 ** 3))
    usable = max(free - floor, 0)
    peak = guarded_compressed + max_guarded
    if peak > usable:
        blockers.append(f"compressed annual peak exceeds usable storage:{peak}>{usable}")

    result = {
        "format_version": 1,
        "scope": "GROUP8_V3_STAGE7_2023_ANNUAL_SHARD_PLAN",
        "status": "PASS" if not blockers else "BLOCKED",
        "year": 2023,
        "symbol": symbol,
        "validated_commit": expected_commit,
        "stage7_auto_launch": False,
        "stage7_authorized": False,
        "full_annual_stage7_permitted_by_plan": not blockers,
        "explicit_user_launch_still_required": True,
        "stage5_database_sha256": stage5_sha,
        "stage6_release_hash": pf["stage6_release_hash"],
        "stage6_union_report_hash": pf["stage6_union_report_hash"],
        "stage7_preflight_report_hash": pf["report_hash"],
        "premium_benchmark_report_hash": pb["report_hash"],
        "compression_gate_report_hash": cg["report_hash"],
        "school_core_benchmark_report_hash": sb["report_hash"],
        "storage_contract_hash": contract["storage_contract_hash"],
        "design_freeze_hash": freeze["design_freeze_hash"],
        "size_safety_factor": size_safety_factor,
        "soft_target_bytes": SOFT_TARGET_BYTES,
        "hard_guard_bytes": HARD_GUARD_BYTES,
        "shard_count": len(shards),
        "range_chain_shard_count": sum(1 for s in shards if s["family"] == "range_chain"),
        "school_core_shard_count": sum(1 for s in shards if s["family"] == "school_core"),
        "exact_cardinality": {
            "range_interpretations": total_range_i,
            "range_evidence_chain_rows": total_range_e,
            "school_interpretations": total_school_i,
            "school_evidence_chain_rows": total_school_e,
            "total_interpretations": total_range_i + total_school_i,
            "total_evidence_chain_rows": total_range_e + total_school_e,
        },
        "storage_projection": {
            "projected_raw_bytes": projected_raw,
            "guarded_projected_raw_bytes": guarded_raw,
            "projected_compressed_bytes": projected_compressed,
            "guarded_projected_compressed_bytes": guarded_compressed,
            "max_guarded_raw_shard_bytes": max_guarded,
            "drive_free_bytes_at_plan": free,
            "safety_floor_bytes": floor,
            "usable_new_output_bytes": usable,
            "projected_peak_bytes": peak,
        },
        "shards": shards,
        "blockers": blockers,
    }
    result["plan_hash"] = stable_hash(result)
    _atomic_json(output_path, result)
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--preflight", type=Path, required=True)
    p.add_argument("--premium-benchmark", type=Path, required=True)
    p.add_argument("--compression-gate", type=Path, required=True)
    p.add_argument("--school-benchmark", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-commit", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--size-safety-factor", type=float, default=1.5)
    p.add_argument("--disk-safety-floor-gb", type=float, default=120.0)
    a = p.parse_args()
    r = build_plan(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        preflight_path=a.preflight.resolve(),
        premium_benchmark_path=a.premium_benchmark.resolve(),
        compression_gate_path=a.compression_gate.resolve(),
        school_benchmark_path=a.school_benchmark.resolve(),
        work_root=a.work_root.resolve(),
        output_path=a.output.resolve(),
        expected_commit=a.expected_commit,
        symbol=a.symbol,
        size_safety_factor=a.size_safety_factor,
        disk_safety_floor_gb=a.disk_safety_floor_gb,
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
