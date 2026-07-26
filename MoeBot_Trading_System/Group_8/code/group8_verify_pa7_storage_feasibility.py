#!/usr/bin/env python3
"""Independent verifier for report 43 PA7 storage feasibility evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ENGINE_SHA = "44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b"
COUNT = 54_413_814
FIXED_BYTES = 401
STANDARD_STORAGE_BYTES = 14_000_000_000


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    source = json.loads(args.report.read_text())
    payload = dict(source)
    saved = payload.pop("report_hash", None)

    checks: dict[str, bool] = {}
    checks["source_report_self_hash"] = saved == stable_hash(payload)
    checks["source_status_pass"] = source.get("status") == "PASS"
    checks["engine_identity"] = source.get("engine_sha256") == ENGINE_SHA
    checks["partial_count_identity"] = int(source.get("partial_transition_count", -1)) == COUNT

    bound = source.get("structural_text_lower_bound", {})
    per = int(bound.get("bytes_per_transition", -1))
    total = int(bound.get("total_bytes", -1))
    checks["fixed_bytes_per_transition"] = per == FIXED_BYTES
    checks["bound_recomputes"] = total == COUNT * FIXED_BYTES

    runner = source.get("standard_public_github_runner", {})
    storage = int(runner.get("documented_storage_bytes", -1))
    checks["documented_standard_storage_identity"] = storage == STANDARD_STORAGE_BYTES
    checks["structural_bound_exceeds_standard_storage"] = total > storage
    checks["reported_storage_comparison_consistent"] = runner.get("structural_bound_exceeds_documented_storage") is True

    mandatory = source.get("mandatory_contract_checks", {})
    checks["mandatory_contract_checks_all_pass"] = bool(mandatory) and all(v is True for v in mandatory.values())

    empirical = source.get("empirical_frozen_engine_text_payload", {})
    empirical_rows = int(empirical.get("sample_transition_rows", 0))
    empirical_min = int(empirical.get("combined_text_bytes_min_per_transition", 0))
    empirical_projection = int(empirical.get("projected_partial_bytes_using_sample_min", 0))
    checks["empirical_rows_present"] = empirical_rows > 0
    checks["empirical_text_payload_stricter_than_structural_bound"] = empirical_min > FIXED_BYTES
    checks["empirical_projection_recomputes"] = empirical_projection == COUNT * empirical_min

    conclusion = source.get("conclusion", {})
    checks["single_sqlite_path_recorded"] = conclusion.get("current_engine_uses_single_output_sqlite") is True
    checks["standard_runner_infeasible_recorded"] = conclusion.get("standard_public_runner_can_materialize_current_single_sqlite_path") is False
    checks["capacity_resolution_required_recorded"] = conclusion.get("infrastructure_or_storage_contract_change_required") is True

    obs = source.get("observations", {})
    checks["no_2024_access"] = obs.get("oos_2024_accessed") is False
    checks["no_frozen_mutation"] = not any(bool(obs.get(k)) for k in ("engine_changed", "definitions_changed", "thresholds_changed", "schema_changed", "upstream_changed", "authorization_changed"))

    failures = [name for name, passed in checks.items() if not passed]
    report: dict[str, Any] = {
        "format_version": 1,
        "phase": "PA7_STORAGE_FEASIBILITY_INDEPENDENT_VERIFICATION",
        "status": "PASS" if not failures else "FAIL",
        "source_report_hash": saved,
        "checks": checks,
        "recomputed": {
            "partial_transition_count": COUNT,
            "fixed_text_bytes_per_transition": FIXED_BYTES,
            "structural_lower_bound_bytes": COUNT * FIXED_BYTES,
            "documented_standard_runner_storage_bytes": STANDARD_STORAGE_BYTES,
            "structural_excess_bytes": COUNT * FIXED_BYTES - STANDARD_STORAGE_BYTES,
            "empirical_min_text_bytes_per_transition": empirical_min,
            "empirical_min_projection_bytes": COUNT * empirical_min,
        },
        "failures": failures,
    }
    report["report_hash"] = stable_hash(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
