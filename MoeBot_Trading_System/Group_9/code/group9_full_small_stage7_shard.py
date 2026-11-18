#!/usr/bin/env python3
"""First exact FULL Group9 shard from verified frozen Group8 Stage7.

Scope intentionally fixed: XAUUSD_ D1 2023-02 (five ICT root candidates).
Inputs are read-only official release, root inventory and *benchmark-era*
support index. This verifies physical shard materialization, identity and
lossless compression; annual coverage and production support parity remain
separate, unverified gates.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from group9_real_root_inventory import (
    atomic_json, load_hashed, sha256_file, stable, stream_decompress_verified,
)
from group9_real_setup_benchmark import init_sample_output, materialize_one
from group9_exact_shard_planner import setup_id
from group9_stage5_unsampled_root_pilot import make_index_overlay
from group9_bounded_materializer_smoke import readonly
from group9_real_root_inventory import month_utc

ICT_FAMILY = "G9_ICT_LIQUIDITY_DELIVERY"
ICT_DEF = "ict_liquidity_sweep_displacement"
SQL_COLS = ("interpretation_id,definition_id,symbol,timeframe,direction,"
            "event_time,availability_time,interpretation_hash,upstream_refs_json")
TABLES = ("setup_instance", "setup_component_evidence", "setup_transition")


def run(args):
    plan = load_hashed(args.exact_plan)
    invrep = load_hashed(args.inventory_report)
    bench = load_hashed(args.benchmark)
    release = load_hashed(args.stage7_release)
    if plan["status"] != "EXACT_COUNTS_PASS_ESTIMATED_SIZES":
        raise RuntimeError("group9_exact_plan_not_pass")
    if (plan["inventory_report_hash"] != invrep["report_hash"]
        or plan["benchmark_report_hash"] != bench["report_hash"]):
        raise RuntimeError("group9_lineage_mismatch")
    if release["status"] != "PASS" or int(release["year"]) != 2023:
        raise RuntimeError("frozen_group8_stage7_release_not_pass")
    if args.support_index.stat().st_size != int(bench["support_index_bytes"]):
        raise RuntimeError("support_index_size_drift")
    entries = [s for s in plan["shards"] if (
        s["year"] == 2023 and s["symbol"] == "XAUUSD_"
        and s["timeframe"] == "D1" and s["root_month"] == "2023-02"
    )]
    if len(entries) != 1 or entries[0]["bucket_count"] != 1:
        raise RuntimeError("unique_full_scope_shard_not_found")
    g9_shard = entries[0]
    if g9_shard["candidate_count_exact"] > 32:
        raise RuntimeError("bounded_pilot_scope_too_large")
    rel_shards = [s for s in release["shards"] if (
        s.get("spec", {}).get("family") == "school_core"
        and s["spec"].get("timeframe") == "D1"
        and s["spec"].get("root_month") == "2023-02"
        and s["spec"].get("symbol") == "XAUUSD_"
    )]
    if len(rel_shards) != 1:
        raise RuntimeError("official_stage7_source_not_unique")
    source_shard = rel_shards[0]
    manifest_path = args.stage7_output_root / Path(source_shard["manifest_path"])
    manifest = load_hashed(manifest_path)
    if (manifest["status"] != "PASS"
        or int(manifest["definition_coverage"].get(ICT_DEF, 0)) != int(g9_shard["candidate_count_exact"])
        or manifest["sha256"] != source_shard["raw_sha256"]):
        raise RuntimeError("stage7_source_manifest_coverage_mismatch")
    archive = args.stage7_output_root / Path(source_shard["archive_path"])
    if (archive.stat().st_size != int(source_shard["compressed_size_bytes"])
        or sha256_file(archive) != source_shard["compressed_sha256"]
        or sha256_file(archive) != manifest["compressed_sha256"]):
        raise RuntimeError("stage7_archive_identity_mismatch")
    outputs = (args.source_raw, args.output, args.output_archive, args.report)
    if any(p.exists() for p in outputs):
        raise FileExistsError("full_shard_pilot_outputs_already_exist")
    started = time.perf_counter()
    raw_bytes, decompression_seconds = stream_decompress_verified(
        args.zstd, archive, args.source_raw, source_shard["raw_sha256"]
    )
    try:
        with closing(readonly(args.inventory_db)) as inventory, closing(readonly(args.source_raw)) as src, closing(make_index_overlay(args.support_index)) as idx:
            roots = inventory.execute("""
                SELECT * FROM root_candidate
                WHERE dataset_year=2023 AND symbol='XAUUSD_' AND timeframe='D1'
                      AND root_month='2023-02'
                ORDER BY root_key
            """).fetchall()
            if len(roots) != int(g9_shard["candidate_count_exact"]):
                raise RuntimeError("full_scope_inventory_cardinality_mismatch")
            source = src.execute(
                f"SELECT {SQL_COLS} FROM school_interpretation WHERE definition_id=?",
                (ICT_DEF,)
            ).fetchall()
            by_id = {str(s["interpretation_id"]): s for s in source}
            if len(source) != len(roots) or len(by_id) != len(roots):
                raise RuntimeError("full_scope_stage7_source_cardinality_mismatch")
            root_ids = {str(r["source_id"]) for r in roots}
            if set(by_id) != root_ids:
                raise RuntimeError("full_scope_root_ids_do_not_match_source")
            for r in roots:
                s = by_id[str(r["source_id"])]
                if (r["setup_family"] != ICT_FAMILY
                    or r["definition_id"] != s["definition_id"]
                    or r["source_type"] != "school_interpretation"
                    or r["source_row_hash"] != s["interpretation_hash"]
                    or r["direction"] != s["direction"]
                    or r["event_time"] != s["event_time"]
                    or r["availability_time"] != s["availability_time"]
                    or month_utc(int(s["event_time"])) != "2023-02"):
                    raise RuntimeError("official_stage7_source_row_lineage_mismatch")
                idx.execute("INSERT INTO source_root VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    str(s["interpretation_id"]), "school_interpretation", 2023,
                    str(s["definition_id"]), str(s["symbol"]), str(s["timeframe"]),
                    str(s["direction"]), int(s["event_time"]), int(s["availability_time"]),
                    str(s["interpretation_hash"]), str(s["upstream_refs_json"]), 0,
                ))
            tmp = args.output.with_suffix(".sqlite.incomplete")
            if tmp.exists():
                raise FileExistsError("prior_incomplete_output_requires_review")
            with closing(init_sample_output(tmp, args.schema)) as out:
                out.execute("PRAGMA foreign_keys=ON")
                stats = defaultdict(lambda: {
                    "roots": 0, "setup_rows": 0, "evidence_rows": 0,
                    "transition_rows": 0, "logical_bytes": 0,
                })
                for r in roots:
                    materialize_one(idx, out, r, "G9-SSI-1.0.0", stats, benchmark_mode=False)
                out.commit()
                if (out.execute("PRAGMA quick_check").fetchone()[0] != "ok"
                    or out.execute("PRAGMA foreign_key_check").fetchall()):
                    raise RuntimeError("full_shard_sqlite_integrity_failed")
                counts = {
                    table: out.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in TABLES
                }
                states = dict(out.execute(
                    "SELECT current_state,COUNT(*) FROM setup_instance GROUP BY current_state"
                ))
                if any(json.loads(row[0]).get("benchmark") is not False
                       for row in out.execute("SELECT features_json FROM setup_instance")):
                    raise RuntimeError("production_shard_contains_benchmark_metadata")
                produced = set(r[0] for r in out.execute("SELECT setup_id FROM setup_instance"))
                expected = {
                    setup_id(ICT_FAMILY, r["symbol"], r["timeframe"], r["direction"],
                             r["source_type"], r["source_id"], "G9-SSI-1.0.0")
                    for r in roots
                }
                if produced != expected or len(expected) != counts["setup_instance"]:
                    raise RuntimeError("full_shard_output_identity_mismatch")
            os.replace(tmp, args.output)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "groups9_15_shared"))
        from shard_runtime import compress_verified
        compressed = compress_verified(
            raw=args.output, archive=args.output_archive, zstd=args.zstd,
            level=6, delete_raw=False,
        )
        result = {
            "format_version": 1,
            "status": "PASS_ONE_EXACT_COMPLETE_SHARD",
            "scope": "G9_2023_D1_FEB_SINGLE_REAL_STAGE7_SHARD",
            "shard_key": g9_shard["shard_key"],
            "stage7_release_hash": release["release_hash"],
            "stage7_source_manifest_hash": manifest["manifest_hash"],
            "exact_plan_report_hash": plan["report_hash"],
            "inventory_report_hash": invrep["report_hash"],
            "source_roots_complete": True,
            "support_index_full_annual_coverage_verified": False,
            "candidate_count": len(roots),
            "counts": counts,
            "states": states,
            "source_raw_bytes": raw_bytes,
            "source_decompression_seconds": decompression_seconds,
            "output_path": str(args.output),
            "output_bytes": args.output.stat().st_size,
            "output_sha256": sha256_file(args.output),
            "archive_path": str(args.output_archive),
            "archive_bytes": args.output_archive.stat().st_size,
            "archive_compression_roundtrip_verified": compressed["lossless_roundtrip_verified"],
            "archive_sha256": compressed["compressed_sha256"],
            "source_original_untouched": True,
            "real_annual_execution_authorized": False,
            "annual_union_verified": False,
            "elapsed_seconds": time.perf_counter() - started,
        }
        result["report_hash"] = stable(result)
        atomic_json(args.report, result)
        return result
    finally:
        # Source was verified using the official release SHA; retained archive
        # remains untouched and upstream Stage7 was never written.
        args.source_raw.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser()
    for field in ("exact-plan", "inventory-report", "inventory-db", "benchmark",
                  "stage7-release", "stage7-output-root", "support-index",
                  "schema", "zstd", "source-raw", "output", "output-archive", "report"):
        p.add_argument("--" + field, type=Path, required=True)
    a = p.parse_args()
    result = run(a)
    print(json.dumps({
        key: result[key] for key in ("status", "shard_key", "candidate_count",
                                     "counts", "states", "output_bytes",
                                     "archive_bytes", "archive_compression_roundtrip_verified",
                                     "real_annual_execution_authorized")
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
