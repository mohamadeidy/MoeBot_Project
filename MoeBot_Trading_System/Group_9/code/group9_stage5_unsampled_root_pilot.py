#!/usr/bin/env python3
"""Group 9: read-only Stage5-root adapter, bounded real-data materialization.

Purpose: verify Group 9 can process *previously unsampled* 2023 Group8 Stage5
roots using the original source and prebuilt support index. The support index
is benchmark-era and is NOT certified as a full production annual input.
No full-shard/annual-run commands or automatic overwrites are implemented.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from group9_real_root_inventory import atomic_json, load_hashed
from group9_real_setup_benchmark import init_sample_output, materialize_one
from group9_exact_shard_planner import setup_id, hash_bucket
from group9_bounded_materializer_smoke import readonly

SCHOOL_COLUMNS = "interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json"
WYCKOFF_FAMILY = "G9_WYCKOFF_RANGE_RESOLUTION"
ROOT_DEFS = ("wyckoff_spring_candidate", "wyckoff_upthrust_candidate")
TABLES = ("setup_instance", "setup_component_evidence", "setup_transition")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def make_index_overlay(support_path: Path) -> sqlite3.Connection:
    """SQL TEMP views expose support subjects and new full-source roots together."""
    idx = sqlite3.connect(":memory:", uri=True)
    idx.row_factory = sqlite3.Row
    idx.execute("ATTACH DATABASE ? AS supp",
                (support_path.resolve().as_uri() + "?mode=ro&immutable=1",))
    idx.executescript("""
        CREATE TABLE source_root (
          subject_id TEXT PRIMARY KEY, subject_type TEXT NOT NULL,
          dataset_year INTEGER NOT NULL, definition_id TEXT NOT NULL,
          symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
          direction TEXT NOT NULL, event_time INTEGER NOT NULL,
          availability_time INTEGER NOT NULL, row_hash TEXT NOT NULL,
          upstream_refs_json TEXT NOT NULL, is_sample_root INTEGER NOT NULL
        );
        CREATE TEMP VIEW subject AS
          SELECT * FROM main.source_root
          UNION ALL
          SELECT * FROM supp.subject
          WHERE subject_id NOT IN (SELECT subject_id FROM main.source_root);
        CREATE TEMP VIEW support_ref AS SELECT * FROM supp.support_ref;
        CREATE TEMP VIEW invalidation AS SELECT * FROM supp.invalidation;
        CREATE TEMP VIEW annual_boundary AS SELECT * FROM supp.annual_boundary;
    """)
    return idx


def select_unsampled_roots(inventory: sqlite3.Connection, source: sqlite3.Connection,
                           idx: sqlite3.Connection, shard: dict, *, offset: int,
                           roots_to_run: int) -> tuple[list[sqlite3.Row], int]:
    if not (1 <= roots_to_run <= 16):
        raise ValueError("pilot_root_limit_must_be_1_to_16")
    if offset < 12_000:
        raise ValueError("offset_must_skip_existing_benchmark_region")
    if int(shard["year"]) != 2023 or shard["timeframe"] != "H1":
        raise ValueError("only_2023_H1_frozen_stage5_source_supported")
    year, symbol, tf, month = shard["year"], shard["symbol"], shard["timeframe"], shard["root_month"]
    bucket, buckets = int(shard["bucket_index"]), int(shard["bucket_count"])
    found = []
    examined = 0
    # Scope index bounds this query; OFFSET is an additional deterministic
    # separation from the old root-key-sorted 12,000-root benchmark.
    candidates = inventory.execute("""
        SELECT * FROM root_candidate
        WHERE dataset_year=? AND symbol=? AND timeframe=? AND root_month=?
        AND setup_family=? AND definition_id IN (?,?)
        ORDER BY root_key LIMIT 1024 OFFSET ?
    """, (year, symbol, tf, month, WYCKOFF_FAMILY, *ROOT_DEFS, offset))
    for row in candidates:
        examined += 1
        sid = setup_id(WYCKOFF_FAMILY, symbol, tf, row["direction"],
                       row["source_type"], row["source_id"], "G9-SSI-1.0.0")
        if hash_bucket(sid, buckets) != bucket:
            continue
        if idx.execute("SELECT 1 FROM supp.subject WHERE subject_id=?",
                       (row["source_id"],)).fetchone():
            # Do not claim a previously unseen Group8 root if already indexed.
            continue
        src = source.execute(
            f"SELECT {SCHOOL_COLUMNS} FROM school_interpretation WHERE interpretation_id=?",
            (row["source_id"],),
        ).fetchone()
        if src is None:
            raise RuntimeError("frozen_source_root_missing:" + row["source_id"])
        if (src["definition_id"] != row["definition_id"] or
            src["interpretation_hash"] != row["source_row_hash"] or
            src["symbol"] != symbol or src["timeframe"] != tf or
            src["direction"] != row["direction"] or
            src["event_time"] != row["event_time"] or
            src["availability_time"] != row["availability_time"]):
            raise RuntimeError("frozen_source_root_lineage_mismatch:" + row["source_id"])
        idx.execute("""
          INSERT INTO source_root VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (str(src["interpretation_id"]), "school_interpretation", year,
              str(src["definition_id"]), str(src["symbol"]), str(src["timeframe"]),
              str(src["direction"]), int(src["event_time"]),
              int(src["availability_time"]), str(src["interpretation_hash"]),
              str(src["upstream_refs_json"]), 0))
        found.append(row)
        if len(found) == roots_to_run:
            break
    if len(found) != roots_to_run:
        raise RuntimeError(f"insufficient_unbenchmarked_stage5_roots:{len(found)}/{roots_to_run}")
    return found, examined


def run(args: argparse.Namespace) -> dict:
    plan = load_hashed(args.plan)
    inv = load_hashed(args.inventory_report)
    bench = load_hashed(args.benchmark)
    if plan["status"] != "EXACT_COUNTS_PASS_ESTIMATED_SIZES":
        raise RuntimeError("plan_not_pass")
    if plan["inventory_report_hash"] != inv["report_hash"] or plan["benchmark_report_hash"] != bench["report_hash"]:
        raise RuntimeError("source_lineage_mismatch")
    if (args.output.exists() or args.report.exists()):
        raise FileExistsError("output_already_exists")
    if args.stage5_raw.stat().st_size != int(bench["largest_stage5_restore_bytes"]):
        raise RuntimeError("stage5_raw_size_not_expected_2023")
    if args.support_index.stat().st_size != int(bench["support_index_bytes"]):
        raise RuntimeError("support_index_size_drift")
    candidates = [s for s in plan["shards"] if s["shard_key"] == args.shard_key]
    if len(candidates) != 1:
        raise RuntimeError("shard_not_in_exact_plan")
    shard = candidates[0]
    if shard["root_month"] != "2023-05" or shard["symbol"] != "XAUUSD_":
        raise ValueError("pilot_scope_must_be_XAUUSD_H1_2023_05")
    if args.max_roots > int(shard["candidate_count_exact"]):
        raise ValueError("bounded_size_exceeds_shard_count")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    incomplete_output = args.output.with_suffix(args.output.suffix + ".incomplete")
    if incomplete_output.exists():
        raise RuntimeError("prior_incomplete_output_requires_review")
    began = time.perf_counter()
    with closing(readonly(args.inventory_db)) as inventory, closing(readonly(args.stage5_raw)) as source, closing(make_index_overlay(args.support_index)) as idx:
        roots, examined = select_unsampled_roots(
            inventory, source, idx, shard, offset=args.offset, roots_to_run=args.max_roots
        )
        if idx.execute("SELECT COUNT(*) FROM source_root").fetchone()[0] != len(roots):
            raise RuntimeError("source_root_duplicate_detected")
        with closing(init_sample_output(incomplete_output, args.schema)) as out:
            out.execute("PRAGMA foreign_keys=ON")
            stats = defaultdict(lambda: {
                "roots": 0, "setup_rows": 0, "evidence_rows": 0,
                "transition_rows": 0, "logical_bytes": 0,
            })
            for root in roots:
                materialize_one(idx, out, root, "G9-SSI-1.0.0", stats, benchmark_mode=False)
            out.commit()
            integrity = out.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok" or out.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("bounded_output_integrity_failed")
            counts = {t: int(out.execute("SELECT COUNT(*) FROM " + t).fetchone()[0])
                      for t in TABLES}
            states = dict(out.execute(
                "SELECT current_state,COUNT(*) FROM setup_instance GROUP BY current_state"
            ))
            if any(json.loads(row[0]).get("benchmark") is not False
                   for row in out.execute("SELECT features_json FROM setup_instance")):
                raise RuntimeError("production_shard_contains_benchmark_metadata")
            emitted_ids = {r[0] for r in out.execute("SELECT setup_id FROM setup_instance")}
            expected_ids = {
                setup_id(WYCKOFF_FAMILY, r["symbol"], r["timeframe"], r["direction"],
                         r["source_type"], r["source_id"], "G9-SSI-1.0.0")
                for r in roots
            }
            if emitted_ids != expected_ids or counts["setup_instance"] != len(roots):
                raise RuntimeError("exact_output_root_identity_mismatch")
    os.replace(incomplete_output, args.output)
    result = {
        "format_version": 1, "status": "PASS_BOUNDED_UNSAMPLED_STAGE5_ROOTS",
        "scope": "G9_2023_STAGE5_ROOTS_WITH_PREBUILT_SUPPORT_INDEX",
        "shard_key": args.shard_key, "full_shard_candidate_count": int(shard["candidate_count_exact"]),
        "actual_root_count": len(roots), "examined_inventory_candidates": examined,
        "source_root_ids": sorted(str(r["source_id"]) for r in roots),
        "root_source": str(args.stage5_raw),
        "support_source": str(args.support_index),
        "root_source_lineage_checked": True,
        "roots_absent_from_benchmark_index": True,
        "row_counts": counts, "states": states, "quick_check": "ok",
        "foreign_key_check": "ok", "output_bytes": args.output.stat().st_size,
        "output_sha256": sha_file(args.output), "output_path": str(args.output),
        "elapsed_seconds": time.perf_counter() - began,
        "support_coverage_complete_for_annual": False,
        "stage7_roots_supported": False, "year2024_supported": False,
        "annual_shards_materialized": False,
        "real_annual_execution_authorized": False,
    }
    result["report_hash"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    atomic_json(args.report, result)
    return result


def main():
    p = argparse.ArgumentParser()
    for name in ("plan", "inventory-db", "inventory-report", "benchmark",
                 "stage5-raw", "support-index", "schema", "output", "report"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--shard-key", required=True)
    p.add_argument("--max-roots", type=int, default=8)
    p.add_argument("--offset", type=int, default=20_000)
    a = p.parse_args()
    result = run(a)
    print(json.dumps({k: result[k] for k in (
        "status", "actual_root_count", "examined_inventory_candidates",
        "row_counts", "states", "output_bytes", "root_source_lineage_checked",
        "roots_absent_from_benchmark_index", "real_annual_execution_authorized"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
