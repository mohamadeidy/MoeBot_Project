#!/usr/bin/env python3
"""Representative preflight and hard-gate planner for Group 8 V3 Stage 6.

This module is diagnostic/planning only. It never mutates the protected Stage 5
boundary or any Groups 1-7 data. It measures a deterministic real-data sample,
derives exact Stage-6 range/DOW work-unit cardinality from the Stage-5 boundary,
projects runtime/storage, chooses a frozen power-of-two range_chain bucket count,
and refuses authorization when the configured budgets are exceeded.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import (
    EXPECTED_DESIGN_FREEZE,
    EXPECTED_STORAGE_CONTRACT,
    RangeShardSpec,
    Stage6RangeShardEngine,
    bucket_for_root,
    epoch_month,
    stable_hash,
)

STAGE6_DEFS = ("wyckoff_range_context", "wyckoff_spring_candidate", "wyckoff_upthrust_candidate")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git_head(artifacts_root: Path) -> str:
    repo = artifacts_root.resolve().parent.parent
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _layer_from_range(features_json: str) -> str | None:
    value = (json.loads(features_json) or {}).get("layer")
    return None if value is None else str(value)


def _layer_from_dow(upstream_refs_json: str) -> str | None:
    refs = json.loads(upstream_refs_json)
    if not refs:
        return None
    value = (refs[0].get("details") or {}).get("layer")
    return None if value is None else str(value)


def _count_le(values: list[int], limit: int) -> int:
    return bisect.bisect_right(values, int(limit))


def inventory_stage6_pairs(stage5_db: Path, symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    con = sqlite3.connect(f"file:{stage5_db.resolve()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        dows_all: dict[str, list[int]] = defaultdict(list)
        dows_none: dict[str, list[int]] = defaultdict(list)
        dows_layer: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in con.execute(
            """SELECT timeframe,availability_time,upstream_refs_json
               FROM school_interpretation
               WHERE definition_id='dow_indeterminate_structure' AND symbol=?
               ORDER BY timeframe,availability_time,interpretation_id""",
            (symbol,),
        ):
            tf = str(row["timeframe"])
            av = int(row["availability_time"])
            layer = _layer_from_dow(str(row["upstream_refs_json"]))
            dows_all[tf].append(av)
            if layer is None:
                dows_none[tf].append(av)
            else:
                dows_layer[(tf, layer)].append(av)

        roots: list[dict[str, Any]] = []
        window_pairs: dict[tuple[str, str], int] = defaultdict(int)
        range_count_by_window: dict[tuple[str, str], int] = defaultdict(int)
        total_pairs = 0
        for row in con.execute(
            """SELECT candidate_id,timeframe,event_time,availability_time,features_json
               FROM price_action_pattern_candidate
               WHERE definition_id='pa_bounded_range_context' AND symbol=?
               ORDER BY timeframe,availability_time,candidate_id""",
            (symbol,),
        ):
            tf = str(row["timeframe"])
            av = int(row["availability_time"])
            layer = _layer_from_range(str(row["features_json"]))
            if layer is None:
                pairs = _count_le(dows_all[tf], av)
            else:
                pairs = _count_le(dows_none[tf], av) + _count_le(dows_layer[(tf, layer)], av)
            month = epoch_month(int(row["event_time"]))
            rec = {
                "candidate_id": str(row["candidate_id"]),
                "timeframe": tf,
                "root_month": month,
                "availability_time": av,
                "layer": layer,
                "pair_count": int(pairs),
            }
            roots.append(rec)
            key = (tf, month)
            range_count_by_window[key] += 1
            window_pairs[key] += int(pairs)
            total_pairs += int(pairs)

        windows = [
            {
                "timeframe": tf,
                "root_month": month,
                "range_roots": range_count_by_window[(tf, month)],
                "range_dow_pairs": window_pairs[(tf, month)],
            }
            for tf, month in sorted(window_pairs)
        ]
        return roots, {
            "range_root_count": len(roots),
            "range_dow_pair_count": total_pairs,
            "windows": windows,
        }
    finally:
        con.close()


def _choose_sample_windows(roots: list[dict[str, Any]], max_windows: int, roots_per_window: int) -> list[tuple[str, str, set[str]]]:
    by_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for root in roots:
        if int(root["pair_count"]) > 0:
            by_window[(root["timeframe"], root["root_month"])].append(root)
    keys = sorted(by_window)
    if not keys:
        return []
    if len(keys) <= max_windows:
        chosen = keys
    elif max_windows <= 1:
        chosen = [keys[len(keys) // 2]]
    else:
        idxs = sorted({round(i * (len(keys) - 1) / (max_windows - 1)) for i in range(max_windows)})
        chosen = [keys[i] for i in idxs]
    out = []
    for key in chosen:
        ranked = sorted(
            by_window[key],
            key=lambda r: hashlib.sha256(str(r["candidate_id"]).encode("utf-8")).hexdigest(),
        )
        selected = {str(r["candidate_id"]) for r in ranked[: max(1, roots_per_window)]}
        out.append((key[0], key[1], selected))
    return out


def _sample_one(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    workdir: Path,
    year: int,
    symbol: str,
    timeframe: str,
    root_month: str,
    roots: set[str],
    hard_guard_bytes: int,
) -> dict[str, Any]:
    output = workdir / f"sample_{timeframe}_{root_month}_{stable_hash(sorted(roots))[:12]}.sqlite"
    cp = workdir / f"{output.stem}.checkpoint.json"
    spec = RangeShardSpec(year, symbol, timeframe, root_month, 1, 0)
    started = time.monotonic()
    engine = Stage6RangeShardEngine(
        staging_db=staging_db,
        output_db=output,
        artifacts_root=artifacts_root,
        year=year,
        symbol=symbol,
        stage5_db=stage5_db,
        checkpoint_path=cp,
        shard_spec=spec,
        hard_guard_bytes=hard_guard_bytes,
        root_allowlist=roots,
    )
    try:
        checkpoint = engine.run_resumable(chunk_pairs=50)
    except Exception:
        engine.close(commit=False)
        raise
    else:
        engine.close(commit=True)
    elapsed = time.monotonic() - started
    con = sqlite3.connect(output)
    try:
        q = ",".join("?" for _ in STAGE6_DEFS)
        interpretations = int(
            con.execute(
                f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",
                STAGE6_DEFS,
            ).fetchone()[0]
        )
        spring_rows = int(
            con.execute(
                """SELECT COUNT(*) FROM school_interpretation
                   WHERE definition_id IN ('wyckoff_spring_candidate','wyckoff_upthrust_candidate')"""
            ).fetchone()[0]
        )
        evidence = int(con.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0])
    finally:
        con.close()
    return {
        "timeframe": timeframe,
        "root_month": root_month,
        "selected_roots": len(roots),
        "pairs": int(checkpoint["total_pairs"]),
        "interpretations": interpretations,
        "spring_upthrust_rows": spring_rows,
        "evidence_rows": evidence,
        "logical_rows": interpretations + evidence,
        "db_bytes": output.stat().st_size,
        "elapsed_seconds": elapsed,
    }


def _baseline(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    workdir: Path,
    year: int,
    symbol: str,
    timeframe: str,
    root_month: str,
    hard_guard_bytes: int,
) -> dict[str, Any]:
    output = workdir / "baseline_empty.sqlite"
    cp = workdir / "baseline_empty.checkpoint.json"
    spec = RangeShardSpec(year, symbol, timeframe, root_month, 1, 0)
    started = time.monotonic()
    engine = Stage6RangeShardEngine(
        staging_db=staging_db,
        output_db=output,
        artifacts_root=artifacts_root,
        year=year,
        symbol=symbol,
        stage5_db=stage5_db,
        checkpoint_path=cp,
        shard_spec=spec,
        hard_guard_bytes=hard_guard_bytes,
        root_allowlist=set(),
    )
    try:
        checkpoint = engine.run_resumable(chunk_pairs=1)
    except Exception:
        engine.close(commit=False)
        raise
    else:
        engine.close(commit=True)
    return {
        "db_bytes": output.stat().st_size,
        "elapsed_seconds": time.monotonic() - started,
        "pairs": int(checkpoint["total_pairs"]),
    }


def _bucket_plan(
    roots: list[dict[str, Any]],
    *,
    bytes_per_pair: float,
    baseline_bytes: int,
    soft_target_bytes: int,
    hard_guard_bytes: int,
    safety_factor: float,
) -> tuple[int, list[dict[str, Any]], int]:
    bucket_count = 1
    while bucket_count <= 4096:
        agg: dict[tuple[str, str, int], int] = defaultdict(int)
        root_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        for root in roots:
            pairs = int(root["pair_count"])
            if pairs <= 0:
                continue
            b = bucket_for_root(str(root["candidate_id"]), bucket_count)
            key = (str(root["timeframe"]), str(root["root_month"]), b)
            agg[key] += pairs
            root_counts[key] += 1
        specs = []
        max_projected = 0
        ok = True
        for (tf, month, bucket), pairs in sorted(agg.items()):
            projected = int(baseline_bytes + pairs * bytes_per_pair * safety_factor)
            max_projected = max(max_projected, projected)
            if projected > soft_target_bytes or projected > hard_guard_bytes:
                ok = False
            specs.append(
                {
                    "timeframe": tf,
                    "root_month": month,
                    "bucket_count": bucket_count,
                    "bucket_index": bucket,
                    "range_roots": root_counts[(tf, month, bucket)],
                    "range_dow_pairs": pairs,
                    "projected_bytes": projected,
                }
            )
        if ok:
            return bucket_count, specs, max_projected
        bucket_count *= 2
    raise RuntimeError("no feasible range_chain bucket_count <=4096 under configured shard guards")


def run_preflight(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    output_root: Path,
    work_root: Path,
    year: int,
    symbol: str,
    validated_commit: str,
    safety_floor_gb: float,
    max_runtime_hours: float,
    max_sample_windows: int,
    sample_roots_per_window: int,
    storage_safety_factor: float,
    runtime_safety_factor: float,
    report_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    if year != 2023:
        raise RuntimeError("V3 Stage 6 preflight currently authorizes 2023 only")
    actual_head = _git_head(artifacts_root)
    if actual_head != validated_commit:
        raise RuntimeError(f"Git checkout mismatch: {actual_head} != validated {validated_commit}")

    freeze = json.loads((artifacts_root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    contract = json.loads((artifacts_root / "SHARDED_STORAGE_CONTRACT.json").read_text())
    if freeze.get("design_freeze_hash") != EXPECTED_DESIGN_FREEZE:
        raise RuntimeError("design freeze drift")
    if contract.get("storage_contract_hash") != EXPECTED_STORAGE_CONTRACT:
        raise RuntimeError("storage contract drift")

    roots, inventory = inventory_stage6_pairs(stage5_db, symbol)
    samples = _choose_sample_windows(roots, max_sample_windows, sample_roots_per_window)
    if inventory["range_dow_pair_count"] > 0 and not samples:
        raise RuntimeError("nonzero Stage 6 work but no representative sample selected")

    soft_target = int(contract["partitioning"]["soft_target_uncompressed_bytes"])
    hard_guard = int(contract["partitioning"]["runtime_hard_guard_bytes"])
    work_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    sample_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="g8v3_stage6_preflight_", dir=work_root) as raw:
        temp = Path(raw)
        if samples:
            baseline = _baseline(
                staging_db=staging_db,
                stage5_db=stage5_db,
                artifacts_root=artifacts_root,
                workdir=temp,
                year=year,
                symbol=symbol,
                timeframe=samples[0][0],
                root_month=samples[0][1],
                hard_guard_bytes=hard_guard,
            )
            for tf, month, allow in samples:
                result = _sample_one(
                    staging_db=staging_db,
                    stage5_db=stage5_db,
                    artifacts_root=artifacts_root,
                    workdir=temp,
                    year=year,
                    symbol=symbol,
                    timeframe=tf,
                    root_month=month,
                    roots=allow,
                    hard_guard_bytes=hard_guard,
                )
                sample_results.append(result)
        else:
            baseline = {"db_bytes": 0, "elapsed_seconds": 0.0, "pairs": 0}

    sample_pairs = sum(int(x["pairs"]) for x in sample_results)
    sample_logic = sum(int(x["logical_rows"]) for x in sample_results)
    sample_variable_bytes = sum(max(int(x["db_bytes"]) - int(baseline["db_bytes"]), 0) for x in sample_results)
    sample_variable_seconds = sum(max(float(x["elapsed_seconds"]) - float(baseline["elapsed_seconds"]), 0.0) for x in sample_results)

    if inventory["range_dow_pair_count"] == 0:
        bytes_per_pair = 0.0
        seconds_per_pair = 0.0
    else:
        if sample_pairs <= 0:
            raise RuntimeError("representative sample produced zero range/DOW pairs")
        bytes_per_pair = max(sample_variable_bytes / sample_pairs, 1.0)
        seconds_per_pair = max(sample_variable_seconds / sample_pairs, 1e-9)

    bucket_count, specs, max_shard = _bucket_plan(
        roots,
        bytes_per_pair=bytes_per_pair,
        baseline_bytes=int(baseline["db_bytes"]),
        soft_target_bytes=soft_target,
        hard_guard_bytes=hard_guard,
        safety_factor=storage_safety_factor,
    )

    projected_storage = sum(int(s["projected_bytes"]) for s in specs)
    projected_runtime_seconds = (
        len(specs) * float(baseline["elapsed_seconds"])
        + inventory["range_dow_pair_count"] * seconds_per_pair * runtime_safety_factor
    )
    disk = shutil.disk_usage(output_root)
    floor_bytes = int(safety_floor_gb * (1024 ** 3))
    usable_bytes = max(int(disk.free) - floor_bytes, 0)
    storage_gate = projected_storage <= usable_bytes
    runtime_gate = projected_runtime_seconds <= max_runtime_hours * 3600.0
    shard_gate = max_shard <= soft_target and max_shard <= hard_guard

    spring_rows = sum(int(x["spring_upthrust_rows"]) for x in sample_results)
    range_rows = sum(max(int(x["interpretations"]) - int(x["spring_upthrust_rows"]), 0) for x in sample_results)
    amplification = None
    if sample_pairs:
        amplification = {
            "range_context_rows_per_pair": range_rows / sample_pairs,
            "spring_upthrust_rows_per_pair": spring_rows / sample_pairs,
            "logical_rows_per_pair": sample_logic / sample_pairs,
        }

    target_chunk_bytes = 64 * 1024 * 1024
    chunk_pairs = 1 if bytes_per_pair <= 0 else max(1, min(1000, int(target_chunk_bytes / bytes_per_pair)))

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "PASS" if storage_gate and runtime_gate and shard_gate else "BLOCKED",
        "scope": "GROUP8_V3_STAGE6_2023_PREFLIGHT",
        "validated_commit": validated_commit,
        "design_freeze_hash": freeze["design_freeze_hash"],
        "storage_contract_hash": contract["storage_contract_hash"],
        "stage5_read_only": True,
        "groups_1_7_read_only": True,
        "inventory": inventory,
        "sample": {
            "window_count": len(sample_results),
            "pairs": sample_pairs,
            "logical_rows": sample_logic,
            "baseline_db_bytes": int(baseline["db_bytes"]),
            "baseline_elapsed_seconds": float(baseline["elapsed_seconds"]),
            "variable_db_bytes": sample_variable_bytes,
            "variable_elapsed_seconds": sample_variable_seconds,
            "bytes_per_pair": bytes_per_pair,
            "seconds_per_pair": seconds_per_pair,
            "amplification": amplification,
            "results": sample_results,
        },
        "projection": {
            "storage_safety_factor": storage_safety_factor,
            "runtime_safety_factor": runtime_safety_factor,
            "recommended_bucket_count": bucket_count,
            "recommended_chunk_pairs": chunk_pairs,
            "planned_nonempty_shards": len(specs),
            "projected_total_output_bytes": projected_storage,
            "projected_max_shard_bytes": max_shard,
            "projected_runtime_seconds": projected_runtime_seconds,
            "projected_runtime_hours": projected_runtime_seconds / 3600.0,
        },
        "storage_budget": {
            "drive_total_bytes": int(disk.total),
            "drive_free_bytes": int(disk.free),
            "safety_floor_gb": safety_floor_gb,
            "safety_floor_bytes": floor_bytes,
            "usable_new_output_bytes": usable_bytes,
            "soft_target_shard_bytes": soft_target,
            "hard_guard_shard_bytes": hard_guard,
        },
        "gates": {
            "storage_budget_pass": storage_gate,
            "runtime_budget_pass": runtime_gate,
            "shard_size_pass": shard_gate,
            "max_runtime_hours": max_runtime_hours,
            "full_annual_stage6_permitted_by_preflight": storage_gate and runtime_gate and shard_gate,
        },
        "materialization_diagnosis": {
            "range_context_cardinality_is_range_x_eligible_dow": True,
            "dow_specific_range_context_ids_are_frozen_semantic_rows": True,
            "liquidity_matching_is_dow_invariant_and_reused_once_per_range_in_v3": True,
            "logical_rows_are_not_merged_or_dropped_for_storage": True,
        },
    }
    report["report_hash"] = stable_hash(report)
    _atomic_json(report_path, report)

    plan = {
        "format_version": 1,
        "status": "PASS" if report["gates"]["full_annual_stage6_permitted_by_preflight"] else "BLOCKED",
        "stage": 6,
        "year": year,
        "symbol": symbol,
        "validated_commit": validated_commit,
        "bucket_count": bucket_count,
        "chunk_pairs": chunk_pairs,
        "soft_target_shard_bytes": soft_target,
        "hard_guard_shard_bytes": hard_guard,
        "safety_floor_gb": safety_floor_gb,
        "projected_total_output_bytes": projected_storage,
        "projected_runtime_seconds": projected_runtime_seconds,
        "specs": specs,
        "preflight_report_hash": report["report_hash"],
    }
    plan["plan_hash"] = stable_hash(plan)
    _atomic_json(plan_path, plan)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--symbol", required=True)
    p.add_argument("--validated-commit", required=True)
    p.add_argument("--safety-floor-gb", type=float, default=120.0)
    p.add_argument("--max-runtime-hours", type=float, default=24.0)
    p.add_argument("--max-sample-windows", type=int, default=6)
    p.add_argument("--sample-roots-per-window", type=int, default=4)
    p.add_argument("--storage-safety-factor", type=float, default=1.5)
    p.add_argument("--runtime-safety-factor", type=float, default=1.5)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    a = p.parse_args()
    r = run_preflight(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        output_root=a.output_root.resolve(),
        work_root=a.work_root.resolve(),
        year=a.year,
        symbol=a.symbol,
        validated_commit=a.validated_commit,
        safety_floor_gb=a.safety_floor_gb,
        max_runtime_hours=a.max_runtime_hours,
        max_sample_windows=a.max_sample_windows,
        sample_roots_per_window=a.sample_roots_per_window,
        storage_safety_factor=a.storage_safety_factor,
        runtime_safety_factor=a.runtime_safety_factor,
        report_path=a.report.resolve(),
        plan_path=a.plan.resolve(),
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0 if r["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
