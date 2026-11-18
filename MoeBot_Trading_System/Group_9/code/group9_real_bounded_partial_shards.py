#!/usr/bin/env python3
"""Group 9 bounded REAL-DATA partial-shard validation, never an annual runner.

Selects deterministic subsets of two frozen planned buckets from the EXISTING
12,000-root benchmark sample, reproduces their reference rows using the frozen
schema, records measured SQLite sizes, validates restart and bounded union.
No Group 8 writes. The sample index is not full annual evidence coverage.
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
from group9_exact_shard_planner import hash_bucket, setup_id
from group9_bounded_materializer_smoke import readonly, rows_for_setup

TABLES = ("setup_instance", "setup_component_evidence", "setup_transition")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_manifest(mfile: Path, dbfile: Path, plan_hash: str, expected: list[str]) -> dict:
    if not mfile.is_file() or not dbfile.is_file():
        raise RuntimeError("partial_shard_manifest_or_database_missing:" + dbfile.name)
    m = json.loads(mfile.read_text(encoding="utf-8"))
    h = m.pop("manifest_hash", None)
    if not h or fingerprint(m) != h:
        raise RuntimeError("partial_shard_manifest_hash_mismatch")
    m["manifest_hash"] = h
    if m["plan_report_hash"] != plan_hash or m["setup_ids"] != expected:
        raise RuntimeError("partial_shard_identity_or_membership_mismatch")
    if dbfile.stat().st_size != int(m["raw_size_bytes"]) or sha_file(dbfile) != m["raw_sha256"]:
        raise RuntimeError("partial_shard_raw_sha_or_size_mismatch")
    with closing(readonly(dbfile)) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("partial_shard_integrity_check_failed")
        if c.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("partial_shard_foreign_key_check_failed")
        ids = [r[0] for r in c.execute("SELECT setup_id FROM setup_instance ORDER BY setup_id")]
        if ids != expected:
            raise RuntimeError("partial_shard_setup_membership_mismatch")
        counts = {t: c.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in TABLES}
        if counts != m["row_counts"]:
            raise RuntimeError("partial_shard_row_count_mismatch")
    return m


def bounded_selection(idx: sqlite3.Connection, *, year: int, tf: str, month: str,
                      bucket: int, plan_bucket_count: int, limit: int) -> list[tuple[str, sqlite3.Row]]:
    if not (1 <= limit <= 64):
        raise ValueError("invalid_bounded_limit")
    found = []
    for r in idx.execute("SELECT * FROM benchmark_sample WHERE dataset_year=? AND timeframe=?",
                         (year, tf)):
        utc_month = time.strftime("%Y-%m", time.gmtime(int(r["event_time"])))
        if utc_month != month:
            continue
        sid = setup_id(str(r["setup_family"]), str(r["symbol"]), str(r["timeframe"]),
                       str(r["direction"]), str(r["source_type"]), str(r["source_id"]),
                       "G9-SSI-1.0.0")
        if hash_bucket(sid, plan_bucket_count) == bucket:
            found.append((sid, r))
    found.sort(key=lambda p: p[0])
    if len(found) < limit:
        raise RuntimeError("insufficient_sample_roots_for_selected_real_bucket:"
                           + str(bucket) + ":" + str(len(found)))
    return found[:limit]


def run(args: argparse.Namespace) -> dict:
    plan = load_hashed(args.exact_plan)
    inv = load_hashed(args.inventory)
    bench = load_hashed(args.benchmark)
    if plan["status"] != "EXACT_COUNTS_PASS_ESTIMATED_SIZES":
        raise RuntimeError("exact_plan_not_pass")
    if plan["inventory_report_hash"] != inv["report_hash"] or plan["benchmark_report_hash"] != bench["report_hash"]:
        raise RuntimeError("plan_source_lineage_mismatch")
    if plan["candidate_count"] != inv["candidate_count"]:
        raise RuntimeError("plan_candidate_count_mismatch")
    if args.bucket_a == args.bucket_b:
        raise ValueError("must_select_two_distinct_buckets")
    wanted = (args.bucket_a, args.bucket_b)
    records = {}
    for s in plan["shards"]:
        if (int(s["year"]) == args.year and s["symbol"] == args.symbol and
            s["timeframe"] == args.timeframe and s["root_month"] == args.month and
            int(s["bucket_index"]) in wanted):
            records[int(s["bucket_index"])] = s
    if set(records) != set(wanted):
        raise RuntimeError("selected_buckets_missing_from_frozen_exact_plan")
    if int(records[wanted[0]]["bucket_count"]) != int(records[wanted[1]]["bucket_count"]):
        raise RuntimeError("inconsistent_scope_bucket_count")
    if args.work_root.exists() and not args.work_root.is_dir():
        raise RuntimeError("work_root_not_directory")
    args.work_root.mkdir(parents=True, exist_ok=True)
    selected_by_bucket = {}
    completed = []
    started = time.perf_counter()
    with closing(readonly(args.support_index)) as idx, closing(readonly(args.reference)) as ref:
        for bucket in wanted:
            entry = records[bucket]
            selected = bounded_selection(idx, year=args.year, tf=args.timeframe,
                                         month=args.month, bucket=bucket,
                                         plan_bucket_count=int(entry["bucket_count"]),
                                         limit=args.limit)
            ids = [x[0] for x in selected]
            selected_by_bucket[bucket] = ids
            shard_name = str(entry["shard_key"]) + "_bounded_sample"
            db = args.work_root / (shard_name + ".sqlite")
            mf = args.work_root / (shard_name + ".manifest.json")
            if db.exists() or mf.exists():
                manifest = verify_manifest(mf, db, plan["report_hash"], ids)
                mode = "verified_resume_skip"
            else:
                tmp = db.with_suffix(".sqlite.incomplete")
                if tmp.exists():
                    raise RuntimeError("incomplete_partial_shard_requires_manual_review:" + str(tmp))
                out = init_sample_output(tmp, args.schema)
                stats = defaultdict(lambda: {
                    "roots": 0, "setup_rows": 0, "evidence_rows": 0,
                    "transition_rows": 0, "logical_bytes": 0,
                })
                try:
                    out.execute("PRAGMA foreign_keys=ON")
                    for sid, sample in selected:
                        materialize_one(idx, out, sample, "G9-SSI-1.0.0", stats)
                        for table in TABLES:
                            if rows_for_setup(out, table, sid) != rows_for_setup(ref, table, sid):
                                raise RuntimeError("reference_row_parity_mismatch:" + table + ":" + sid)
                    out.commit()
                    if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("output_quick_check_failed")
                    if out.execute("PRAGMA foreign_key_check").fetchall():
                        raise RuntimeError("output_foreign_key_check_failed")
                    counts = {t: out.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in TABLES}
                finally:
                    out.close()
                os.replace(tmp, db)
                manifest = {
                    "format_version": 1,
                    "status": "PASS_BOUNDED_SAMPLE",
                    "scope": "GROUP9_REAL_DATA_PARTIAL_SHARD",
                    "shard_key": entry["shard_key"],
                    "full_shard_candidate_count": int(entry["candidate_count_exact"]),
                    "sample_candidate_count": len(ids),
                    "bucket_index": bucket,
                    "bucket_count": int(entry["bucket_count"]),
                    "setup_ids": ids,
                    "row_counts": counts,
                    "raw_size_bytes": db.stat().st_size,
                    "raw_sha256": sha_file(db),
                    "plan_report_hash": plan["report_hash"],
                    "source_benchmark_report_hash": bench["report_hash"],
                    "real_annual_execution_authorized": False,
                }
                manifest["manifest_hash"] = fingerprint(manifest)
                atomic_json(mf, manifest)
                verify_manifest(mf, db, plan["report_hash"], ids)
                mode = "created_and_verified"
            completed.append({"shard_key": entry["shard_key"], "mode": mode,
                              "sample_roots": len(ids), "full_shard_roots": int(entry["candidate_count_exact"]),
                              "sqlite_bytes": manifest["raw_size_bytes"],
                              "sha256": manifest["raw_sha256"]})
        if set(selected_by_bucket[wanted[0]]) & set(selected_by_bucket[wanted[1]]):
            raise RuntimeError("bounded_union_duplicate_setup_ids")
        # Actual bounded union validation, not a full annual release.
        combined = {}
        row_counts = defaultdict(int)
        for bucket in wanted:
            db = args.work_root / (str(records[bucket]["shard_key"]) + "_bounded_sample.sqlite")
            with closing(readonly(db)) as c:
                for table in TABLES:
                    for row in c.execute("SELECT * FROM " + table + " ORDER BY 1"):
                        rid = str(row[0])
                        key = (table, rid)
                        if key in combined:
                            raise RuntimeError("bounded_union_duplicate_row_identity:" + rid)
                        combined[key] = tuple(row)
                        row_counts[table] += 1
        for bucket in wanted:
            for sid in selected_by_bucket[bucket]:
                for table in TABLES:
                    actual = [row for (t, _), row in combined.items() if t == table and row[2] == sid] if table != "setup_instance" else [row for (t, rid), row in combined.items() if t == table and rid == sid]
                    expected = rows_for_setup(ref, table, sid)
                    if sorted(actual) != sorted(expected):
                        raise RuntimeError("bounded_union_reference_parity_mismatch:" + table + ":" + sid)
    record = {
        "format_version": 1,
        "scope": "GROUP9_TWO_REAL_DATA_PARTIAL_SHARDS_AND_BOUNDED_UNION",
        "status": "PASS_BOUNDED_ONLY",
        "plan_report_hash": plan["report_hash"],
        "year": args.year, "symbol": args.symbol, "timeframe": args.timeframe,
        "month": args.month, "sample_limit_per_bucket": args.limit,
        "shards": completed,
        "bounded_union_setup_count": len(selected_by_bucket[wanted[0]]) + len(selected_by_bucket[wanted[1]]),
        "bounded_union_row_counts": dict(row_counts),
        "bounded_union_parity_to_existing_reference": True,
        "actual_sqlite_shard_sizes_measured": True,
        "all_annual_roots_covered": False,
        "annual_union_verified": False,
        "production_materializer_verified": False,
        "real_annual_execution_authorized": False,
        "elapsed_seconds": time.perf_counter() - started,
    }
    record["report_hash"] = fingerprint(record)
    # Unique run report: never overwrite prior frozen evidence.
    if args.report.exists():
        raise FileExistsError("bounded_report_already_exists")
    atomic_json(args.report, record)
    return record


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exact-plan", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--benchmark", type=Path, required=True)
    p.add_argument("--support-index", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--symbol", default="XAUUSD_")
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--month", default="2023-05")
    p.add_argument("--bucket-a", type=int, default=0)
    p.add_argument("--bucket-b", type=int, default=1)
    p.add_argument("--limit", type=int, default=24)
    a = p.parse_args()
    r = run(a)
    print(json.dumps({k: r[k] for k in ("status", "bounded_union_setup_count",
                                      "bounded_union_row_counts", "shards",
                                      "bounded_union_parity_to_existing_reference",
                                      "real_annual_execution_authorized")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
