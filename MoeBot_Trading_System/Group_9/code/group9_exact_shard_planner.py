#!/usr/bin/env python3
"""Exact Group 9 root-to-shard occupancy planner, without materialization.

Read-only roots. Deterministic setup_id derivation matches frozen benchmark.
Shard occupancy is exact; byte forecasts remain estimates until measured output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

SOFT_BYTES = 1_500_000_000
HARD_BYTES = 2_500_000_000
GROUP9_VERSION = "G9-SSI-1.0.0"


def stable(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_report(path, hash_key="report_hash"):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    actual = data.get(hash_key)
    body = dict(data)
    body.pop(hash_key, None)
    if not actual or stable(body) != actual:
        raise ValueError("report_hash_invalid:" + str(path))
    return data


def setup_id(family, symbol, timeframe, direction, source_type, source_id, version):
    if direction not in ("bullish", "bearish"):
        raise ValueError("invalid_direction")
    return "g9s_" + stable({
        "family": family,
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": direction,
        "root_subject_type": source_type,
        "root_subject_id": str(source_id),
        "definition_version": version,
    })


def hash_bucket(sid, count):
    if count < 1 or count & (count - 1):
        raise ValueError("bucket_count_not_power_of_two")
    return int.from_bytes(hashlib.sha256(sid.encode()).digest()[:8], "big") % count


def exact_plan(con, inventory, benchmark, projection):
    if projection["status"] != "PROJECTION_PASS":
        raise ValueError("projection_not_pass")
    if projection["inventory_report_hash"] != inventory["report_hash"]:
        raise ValueError("projection_inventory_mismatch")
    if projection["benchmark_report_hash"] != benchmark["report_hash"]:
        raise ValueError("projection_benchmark_mismatch")
    if inventory["candidate_count"] != benchmark["candidate_population"]:
        raise ValueError("candidate_population_mismatch")
    family_weight = {}
    overhead = float(benchmark["sqlite_overhead_factor"])
    for family, stat in benchmark["family_stats"].items():
        family_weight[family] = float(stat["projected_family_logical_bytes"]) / int(stat["population"]) * overhead
    if sum(int(x["population"]) for x in benchmark["family_stats"].values()) != inventory["candidate_count"]:
        raise ValueError("family_counts_mismatch")
    scopes = {}
    for x in projection["scopes"]:
        key = (int(x["year"]), x["symbol"], x["timeframe"], x["root_month"])
        if key in scopes:
            raise ValueError("duplicate_scope")
        scopes[key] = x
    # SQLite is opened read-only by the caller; full pass is sequential.
    # Retain only one per-bucket accumulator, never root rows or output shards.
    occupancy = defaultdict(lambda: [0, 0.0])
    total = 0
    scope_counts = defaultdict(int)
    families = defaultdict(int)
    # Sequential table scan avoids millions of random lookups through the scope
    # index. Occupancy counts are commutative; report keys sort explicitly.
    q = """SELECT dataset_year,symbol,timeframe,root_month,setup_family,
                  source_type,source_id,direction FROM root_candidate"""
    for year, sym, tf, month, family, source_type, source_id, direction in con.execute(q):
        scope_key = (int(year), sym, tf, month)
        info = scopes.get(scope_key)
        if info is None:
            raise ValueError("inventory_scope_absent_in_projection:" + str(scope_key))
        if family not in family_weight:
            raise ValueError("unknown_setup_family:" + family)
        sid = setup_id(family, sym, tf, direction, source_type, source_id, GROUP9_VERSION)
        bucket = hash_bucket(sid, int(info["bucket_count"]))
        slot = occupancy[(scope_key, bucket)]
        slot[0] += 1
        slot[1] += family_weight[family]
        scope_counts[scope_key] += 1
        families[family] += 1
        total += 1
    if total != int(inventory["candidate_count"]):
        raise ValueError("global_candidate_count_mismatch")
    for key, x in scopes.items():
        if scope_counts[key] != int(x["candidate_count"]):
            raise ValueError("exact_scope_count_mismatch:" + str(key))
    for family, stat in benchmark["family_stats"].items():
        if families[family] != int(stat["population"]):
            raise ValueError("exact_family_count_mismatch:" + family)
    buckets = []
    for (scope, bucket), (n, measured_weight) in sorted(occupancy.items()):
        year, sym, tf, month = scope
        # Size extrapolation uses family-specific sample weights plus 25% reserve.
        estimated_bytes = math.ceil(measured_weight * 1.25)
        buckets.append({
            "year": year,
            "symbol": sym,
            "timeframe": tf,
            "root_month": month,
            "bucket_index": bucket,
            "bucket_count": int(scopes[scope]["bucket_count"]),
            "candidate_count_exact": n,
            "estimated_bytes_with_25pct_reserve": estimated_bytes,
            "shard_key": f"g9_{year}_{sym}_{tf}_{month}_b{bucket:04d}of{int(scopes[scope]['bucket_count']):04d}",
        })
    max_bytes = max((b["estimated_bytes_with_25pct_reserve"] for b in buckets), default=0)
    oversized = [b["shard_key"] for b in buckets if b["estimated_bytes_with_25pct_reserve"] > SOFT_BYTES]
    gates = {
        "all_root_assignments_unique_and_complete": True,
        "scope_counts_exact": True,
        "family_counts_exact": True,
        "estimated_shard_soft_limit": not oversized,
        "estimated_shard_hard_limit": max_bytes <= HARD_BYTES,
    }
    result = {
        "format_version": 1,
        "scope": "GROUP9_EXACT_SHARD_OCCUPANCY",
        "status": "EXACT_COUNTS_PASS_ESTIMATED_SIZES" if all(gates.values()) else "REVISE_SHARD_BUCKETS",
        "inventory_report_hash": inventory["report_hash"],
        "benchmark_report_hash": benchmark["report_hash"],
        "projection_report_hash": projection["report_hash"],
        "definition_version": GROUP9_VERSION,
        "candidate_count": total,
        "exact_nonempty_shards": len(buckets),
        "max_estimated_shard_bytes": max_bytes,
        "oversized_shard_count": len(oversized),
        "oversized_shard_keys": oversized[:25],
        "gates": gates,
        "shards": buckets,
        "upstream_read_only": True,
        "actual_shard_bytes_verified": False,
        "actual_shard_materializer_tested": False,
        "real_annual_execution_authorized": False,
        "note": "Exact deterministic ID bucket occupancy. Estimated bytes are NOT actual measured raw SQLite shard bytes.",
    }
    result["report_hash"] = stable(result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inventory-report", type=Path, required=True)
    p.add_argument("--benchmark", type=Path, required=True)
    p.add_argument("--projection", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    inv = load_report(a.inventory_report)
    bench = load_report(a.benchmark)
    projection = load_report(a.projection)
    db = Path(inv["inventory_db_path"])
    if not db.is_file() or db.stat().st_size != int(inv["inventory_db_bytes"]):
        raise ValueError("inventory_database_missing_or_size_changed")
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        result = exact_plan(con, inv, bench, projection)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "candidate_count": result["candidate_count"],
        "exact_nonempty_shards": result["exact_nonempty_shards"],
        "max_estimated_shard_bytes": result["max_estimated_shard_bytes"],
        "oversized_shard_count": result["oversized_shard_count"],
        "real_annual_execution_authorized": False,
        "report": str(a.report),
    }, indent=2))
    return 0 if result["status"] == "EXACT_COUNTS_PASS_ESTIMATED_SIZES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
