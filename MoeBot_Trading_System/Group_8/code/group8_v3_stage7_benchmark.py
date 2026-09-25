#!/usr/bin/env python3
"""Representative V3 Stage 7 premium/discount benchmark.

This is a read-only-input, bounded-output engineering benchmark. It materializes
a deterministic representative sample of the frozen ICT3.1 definition through
the frozen Group8 writer so IDs, hashes, evidence-chain rows, and SQLite layout
match the production logical contract. It never authorizes annual Stage 7.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import epoch_month, stable_hash
from moebot_group8_engine_v0_8_0 import Group8Engine, max_time, sha256_file

SOFT_TARGET_BYTES = 1_500_000_000
HARD_GUARD_BYTES = 2_500_000_000


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


def _range_cutoff(rg: sqlite3.Row, invalidators: dict[str, list[int]]) -> int | None:
    f = json.loads(str(rg["features_json"] or "{}"))
    times: list[int] = []
    for zid in (f.get("lower_zone_id"), f.get("upper_zone_id")):
        if not zid:
            continue
        x = _first_after(invalidators.get(str(zid), []), int(rg["availability_time"]))
        if x is not None:
            times.append(x)
    return min(times) if times else None


def _even_sample(rows: list[sqlite3.Row], n: int) -> list[sqlite3.Row]:
    if n <= 0 or not rows:
        return []
    if len(rows) <= n:
        return rows
    if n == 1:
        return [rows[len(rows) // 2]]
    idxs = [round(i * (len(rows) - 1) / (n - 1)) for i in range(n)]
    return [rows[i] for i in sorted(set(idxs))]


def _next_power_two(n: float) -> int:
    if n <= 1:
        return 1
    return 1 << math.ceil(math.log2(n))


def run_benchmark(
    *,
    staging_db: Path,
    stage5_db: Path,
    preflight_report_path: Path,
    artifacts_root: Path,
    sample_db: Path,
    report_path: Path,
    symbol: str,
    sample_roots_per_window: int,
    chunk_interpretations: int,
    safety_floor_gb: float,
    storage_safety_factor: float,
    runtime_safety_factor: float,
) -> dict[str, Any]:
    preflight = json.loads(preflight_report_path.read_text())
    if preflight.get("status") != "PASS":
        raise RuntimeError("Stage 7 preflight is not PASS")
    if preflight.get("stage7_authorized") is not False:
        raise RuntimeError("Stage 7 preflight unexpectedly authorizes execution")
    if sha256_file(stage5_db) != preflight.get("stage5_database_sha256"):
        raise RuntimeError("Stage 5 hash drift since Stage 7 preflight")

    if sample_db.exists():
        sample_db.unlink()
    sample_db.parent.mkdir(parents=True, exist_ok=True)

    stage5 = _ro(stage5_db)
    staging = _ro(staging_db)
    try:
        windows: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for rg in stage5.execute(
            """SELECT candidate_id,symbol,timeframe,source_bar_id,event_time,
                      confirmation_time,availability_time,lower,upper,features_json
               FROM price_action_pattern_candidate
               WHERE definition_id='pa_bounded_range_context' AND symbol=?
               ORDER BY timeframe,event_time,availability_time,candidate_id""",
            (symbol,),
        ):
            windows[(str(rg["timeframe"]), epoch_month(int(rg["event_time"])))].append(rg)

        selected: list[sqlite3.Row] = []
        selected_by_window: dict[str, int] = {}
        for key in sorted(windows):
            sample = _even_sample(windows[key], sample_roots_per_window)
            selected.extend(sample)
            selected_by_window[f"{key[0]}:{key[1]}"] = len(sample)

        engine = Group8Engine(
            staging_db=staging_db,
            output_db=sample_db,
            artifacts_root=artifacts_root,
            year=2023,
            symbol=symbol,
        )
        try:
            engine.out.execute("PRAGMA journal_mode=DELETE")
            engine.out.execute("PRAGMA synchronous=FULL")
            engine.out.commit()
            baseline_bytes = sample_db.stat().st_size
            engine.load_bars()
            invalidators = _load_invalidators(staging)

            emitted = 0
            started = time.monotonic()
            per_window: dict[str, dict[str, int]] = {}
            pending = 0

            for rg in selected:
                src = engine._bar_by_id(rg["source_bar_id"])
                if not src:
                    raise RuntimeError(f"sampled range source bar missing: {rg['candidate_id']}")
                key, idx = engine.bar_pos[src.id]
                cutoff = _range_cutoff(rg, invalidators)
                window_key = f"{rg['timeframe']}:{epoch_month(int(rg['event_time']))}"
                stats = per_window.setdefault(window_key, {"roots": 0, "interpretations": 0})
                stats["roots"] += 1
                midpoint = (float(rg["lower"]) + float(rg["upper"])) / 2.0
                for bar in engine.bars_by_tf[key][idx:]:
                    if int(bar.available_at) < int(rg["availability_time"]):
                        continue
                    if cutoff is not None and int(bar.available_at) >= int(cutoff):
                        break
                    loc = "discount" if bar.close < midpoint else "premium" if bar.close > midpoint else "equilibrium"
                    engine._write_interpretation(
                        "ict_premium_discount_context",
                        symbol=bar.symbol,
                        timeframe=bar.timeframe,
                        direction="neutral",
                        event_time=bar.close_time,
                        confirmation_time=bar.close_time,
                        availability_time=max_time(bar.available_at, rg["availability_time"]),
                        upstream_refs=[
                            engine._ref(
                                "group8",
                                "price_action_pattern_candidate",
                                rg["candidate_id"],
                                rg["availability_time"],
                            ),
                            engine._ref(
                                "source",
                                "bars",
                                bar.id,
                                bar.available_at,
                                event_time=bar.close_time,
                                timeframe=bar.timeframe,
                            ),
                        ],
                        reasons=[loc],
                        evidence_strength={"location": loc, "midpoint": midpoint, "close": bar.close},
                    )
                    emitted += 1
                    stats["interpretations"] += 1
                    pending += 1
                    if pending >= chunk_interpretations:
                        engine.out.commit()
                        pending = 0
            if pending:
                engine.out.commit()
            elapsed = max(time.monotonic() - started, 1e-9)

            irows = int(engine.out.execute(
                "SELECT COUNT(*) FROM school_interpretation WHERE definition_id='ict_premium_discount_context'"
            ).fetchone()[0])
            erows = int(engine.out.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0])
            if irows != emitted:
                raise RuntimeError(f"benchmark interpretation count mismatch {irows}!={emitted}")
            if erows != 2 * irows:
                raise RuntimeError(f"benchmark evidence-chain cardinality mismatch {erows}!={2*irows}")
            qc = engine.out.execute("PRAGMA quick_check").fetchone()[0]
            ic = engine.out.execute("PRAGMA integrity_check").fetchone()[0]
            fk = engine.out.execute("PRAGMA foreign_key_check").fetchall()
            if qc != "ok" or ic != "ok" or fk:
                raise RuntimeError(f"benchmark SQLite validation failed qc={qc} ic={ic} fk={len(fk)}")
        finally:
            engine.close()

        final_bytes = sample_db.stat().st_size
        variable_bytes = max(final_bytes - baseline_bytes, 0)
        logical_rows = irows + erows
        bytes_per_interpretation = variable_bytes / max(irows, 1)
        bytes_per_logical_row = variable_bytes / max(logical_rows, 1)
        seconds_per_interpretation = elapsed / max(irows, 1)

        full_premium = int(preflight["definition_cardinality_current_engine"]["ict_premium_discount_context"])
        total_current_logical = int(preflight["projection_diagnostic"]["current_engine_total_logical_rows"])
        premium_logical = 3 * full_premium
        nonpremium_logical = max(total_current_logical - premium_logical, 0)
        stage6_density = float(preflight["projection_diagnostic"]["stage6_observed_bytes_per_logical_row"])

        premium_projected_bytes = int(bytes_per_interpretation * full_premium)
        nonpremium_projected_bytes = int(stage6_density * nonpremium_logical)
        projected_total_bytes = premium_projected_bytes + nonpremium_projected_bytes
        projected_total_safety = int(projected_total_bytes * storage_safety_factor)
        premium_runtime_seconds = seconds_per_interpretation * full_premium * runtime_safety_factor

        window_cardinality = preflight["premium_discount"]["by_root_window"]
        preliminary_buckets: dict[str, int] = {}
        projected_max_shard = 0
        total_shards = 0
        for window, count in sorted(window_cardinality.items()):
            b = int(count) * bytes_per_interpretation
            buckets = _next_power_two(b / SOFT_TARGET_BYTES)
            preliminary_buckets[window] = buckets
            total_shards += buckets
            projected_max_shard = max(projected_max_shard, int(math.ceil(b / buckets)))

        disk = shutil.disk_usage(sample_db.parent)
        floor = int(safety_floor_gb * (1024 ** 3))
        usable = max(int(disk.free) - floor, 0)

        result = {
            "format_version": 1,
            "scope": "GROUP8_V3_STAGE7_PREMIUM_DISCOUNT_REPRESENTATIVE_BENCHMARK",
            "status": "PASS",
            "stage7_authorized": False,
            "full_annual_stage7_permitted": False,
            "symbol": symbol,
            "stage5_database_sha256": sha256_file(stage5_db),
            "stage7_preflight_report_hash": preflight["report_hash"],
            "sample": {
                "window_count": len(selected_by_window),
                "selected_roots": len(selected),
                "selected_roots_by_window": selected_by_window,
                "interpretations": irows,
                "evidence_chain_rows": erows,
                "logical_rows": logical_rows,
                "baseline_db_bytes": baseline_bytes,
                "final_db_bytes": final_bytes,
                "variable_db_bytes": variable_bytes,
                "elapsed_seconds": elapsed,
                "bytes_per_interpretation_with_two_evidence_rows": bytes_per_interpretation,
                "bytes_per_logical_row": bytes_per_logical_row,
                "seconds_per_interpretation": seconds_per_interpretation,
                "per_window": dict(sorted(per_window.items())),
            },
            "projection": {
                "full_premium_discount_interpretations": full_premium,
                "premium_discount_logical_rows": premium_logical,
                "nonpremium_logical_rows": nonpremium_logical,
                "premium_projected_bytes_from_measured_sample": premium_projected_bytes,
                "nonpremium_projected_bytes_using_stage6_density": nonpremium_projected_bytes,
                "projected_total_uncompressed_bytes": projected_total_bytes,
                "projected_total_bytes_with_storage_safety_factor": projected_total_safety,
                "projected_premium_runtime_seconds_with_runtime_safety_factor": premium_runtime_seconds,
                "storage_safety_factor": storage_safety_factor,
                "runtime_safety_factor": runtime_safety_factor,
                "preliminary_range_chain_bucket_count_by_window": preliminary_buckets,
                "preliminary_range_chain_shard_count": total_shards,
                "projected_max_range_chain_shard_bytes": projected_max_shard,
                "soft_target_shard_bytes": SOFT_TARGET_BYTES,
                "hard_guard_shard_bytes": HARD_GUARD_BYTES,
            },
            "storage_budget": {
                "drive_free_bytes": int(disk.free),
                "drive_total_bytes": int(disk.total),
                "safety_floor_gb": safety_floor_gb,
                "safety_floor_bytes": floor,
                "usable_new_output_bytes": usable,
                "projected_uncompressed_fits_usable_space": projected_total_safety <= usable,
            },
            "next_gate": "build Stage 7 shard executor + school_core benchmark + parity/resume/idempotence; annual execution remains blocked",
        }
        result["report_hash"] = stable_hash(result)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result
    finally:
        staging.close()
        stage5.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--preflight-report", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--sample-db", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--sample-roots-per-window", type=int, default=2)
    p.add_argument("--chunk-interpretations", type=int, default=5000)
    p.add_argument("--safety-floor-gb", type=float, default=120.0)
    p.add_argument("--storage-safety-factor", type=float, default=1.5)
    p.add_argument("--runtime-safety-factor", type=float, default=1.5)
    a = p.parse_args()
    r = run_benchmark(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        preflight_report_path=a.preflight_report.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        sample_db=a.sample_db.resolve(),
        report_path=a.report.resolve(),
        symbol=a.symbol,
        sample_roots_per_window=a.sample_roots_per_window,
        chunk_interpretations=a.chunk_interpretations,
        safety_floor_gb=a.safety_floor_gb,
        storage_safety_factor=a.storage_safety_factor,
        runtime_safety_factor=a.runtime_safety_factor,
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
