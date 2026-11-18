#!/usr/bin/env python3
"""Group 9 deterministic projection and shard-scope sizing, NO execution.

Consumes immutable reports and exact aggregate scopes. No root re-extraction.
The scope plan is a planning artifact, not an executable root-to-shard catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

GIB = 1024 ** 3
SOFT_SHARD = 1_500_000_000
HARD_SHARD = 2_500_000_000


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_hashed(path: Path, hash_field: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    actual = data.get(hash_field)
    if actual is None:
        raise ValueError(f"missing_{hash_field}:{path}")
    payload = dict(data)
    payload.pop(hash_field)
    if stable(payload) != actual:
        raise ValueError(f"hash_mismatch:{path}")
    if data.get("status") != "PASS":
        raise ValueError(f"not_pass:{path}")
    return data


def power2_at_least(n: int) -> int:
    return 1 << (max(n, 1) - 1).bit_length()


def make_plan(inventory: dict, benchmark: dict, c_free: int, d_free: int) -> dict:
    if inventory["report_hash"] != benchmark["inventory_report_hash"]:
        raise ValueError("inventory_lineage_mismatch")
    if inventory["semantic_registry_hash"] != benchmark["semantic_registry_hash"]:
        raise ValueError("semantic_registry_mismatch")
    count = int(inventory["candidate_count"])
    if count != int(benchmark["candidate_population"]):
        raise ValueError("population_mismatch")
    if sum(int(x["candidate_count"]) for x in inventory["scopes"]) != count:
        raise ValueError("inventory_scope_count_mismatch")
    family_pop = sum(int(v["population"]) for v in benchmark["family_stats"].values())
    if family_pop != count:
        raise ValueError("family_population_mismatch")
    if benchmark.get("outcome_data_accessed") or benchmark.get("trade_policy_accessed"):
        raise ValueError("outcome_or_policy_contamination")
    if benchmark.get("definition_version") != "G9-SSI-1.0.0":
        raise ValueError("unexpected_definition_version")
    projected_output = int(benchmark["projected_output_bytes"])
    projected_seconds = float(benchmark["projected_total_seconds"])
    if projected_output <= 0 or projected_seconds <= 0:
        raise ValueError("invalid_projection")
    # Scope proportions are known exactly; bytes are statistical estimates, not
    # actual per-family/per-shard measurements. Include 25% planning reserve.
    avg_bytes = projected_output / count
    reserve = 1.25
    scopes = []
    total_buckets = 0
    total_projected = 0
    for item in sorted(inventory["scopes"], key=lambda r:
                       (int(r["dataset_year"]), str(r["symbol"]), str(r["timeframe"]), str(r["root_month"]))):
        n = int(item["candidate_count"])
        if n <= 0:
            raise ValueError("empty_scope")
        projected = math.ceil(n * avg_bytes * reserve)
        buckets = power2_at_least(math.ceil(projected / SOFT_SHARD))
        # For a preflight-only estimate, even bucket skew is NOT proven here.
        estimate = math.ceil(projected / buckets)
        if estimate > SOFT_SHARD:
            raise ValueError("shard_projection_exceeds_soft_target")
        scopes.append({
            "year": int(item["dataset_year"]),
            "symbol": str(item["symbol"]),
            "timeframe": str(item["timeframe"]),
            "root_month": str(item["root_month"]),
            "candidate_count": n,
            "projected_bytes_with_reserve": projected,
            "bucket_count": buckets,
            "estimated_average_bucket_bytes": estimate,
        })
        total_buckets += buckets
        total_projected += projected
    c_floor = 120 * GIB
    free_after_floor = max(0, int(c_free) - c_floor)
    largest_restore = int(benchmark["largest_stage5_restore_bytes"])
    gates = {
        "exact_inventory_reconciled": True,
        "benchmark_below_48_hours": projected_seconds <= 48 * 3600,
        "disk_c_floor_120gib": c_free >= c_floor,
        "scratch_d_can_fit_largest_restore": d_free > largest_restore + HARD_SHARD,
        "estimated_bucket_soft_target": all(s["estimated_average_bucket_bytes"] <= SOFT_SHARD for s in scopes),
    }
    out = {
        "format_version": 1,
        "scope": "GROUP9_REAL_PROJECTION_SCOPE_SHARD_PLAN",
        "status": "PROJECTION_PASS" if all(gates.values()) else "BLOCKED",
        "yearly_candidate_count": inventory["counts_by_year"],
        "candidate_count": count,
        "definition_version": benchmark["definition_version"],
        "semantic_registry_hash": benchmark["semantic_registry_hash"],
        "inventory_report_hash": inventory["report_hash"],
        "benchmark_report_hash": benchmark["report_hash"],
        "projected_annual_hours_serial": projected_seconds / 3600,
        "runtime_target_24h_met": projected_seconds <= 24 * 3600,
        "hard_runtime_48h_met": gates["benchmark_below_48_hours"],
        "projected_output_bytes": projected_output,
        "output_reserve_factor": reserve,
        "projected_output_with_reserve_bytes": total_projected,
        "estimated_scope_bucket_count": total_buckets,
        "scopes": scopes,
        "storage": {
            "c_free_bytes": int(c_free),
            "c_floor_bytes": c_floor,
            "c_usable_above_floor_bytes": free_after_floor,
            "d_free_bytes": int(d_free),
            "largest_upstream_restore_bytes": largest_restore,
            "raw_shard_hard_guard_bytes": HARD_SHARD,
        },
        "gates": gates,
        "limits": [
            "Scope-level byte estimates, not measured exact shard cardinalities",
            "No per-bucket hash occupancy audit performed",
            "Family-specific distribution within scopes is not measured",
            "Annual shard materializer, resume, streaming union and parity not verified",
        ],
        "exact_shard_plan_authorized": False,
        "real_annual_execution_authorized": False,
        "upstream_read_only": True,
        "trade_policy_accessed": False,
        "outcome_data_accessed": False,
    }
    out["report_hash"] = stable(out)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--benchmark", type=Path, required=True)
    p.add_argument("--c-path", type=Path, required=True)
    p.add_argument("--d-path", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    inventory = load_hashed(a.inventory, "report_hash")
    benchmark = load_hashed(a.benchmark, "report_hash")
    c = shutil.disk_usage(a.c_path)
    d = shutil.disk_usage(a.d_path)
    result = make_plan(inventory, benchmark, c.free, d.free)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "scope_count": len(result["scopes"]),
        "estimated_scope_bucket_count": result["estimated_scope_bucket_count"],
        "projected_annual_hours_serial": result["projected_annual_hours_serial"],
        "runtime_target_24h_met": result["runtime_target_24h_met"],
        "gates": result["gates"],
        "exact_shard_plan_authorized": False,
        "real_annual_execution_authorized": False,
        "report": str(a.report),
    }, indent=2, sort_keys=True))
    return 0 if result["status"] == "PROJECTION_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
