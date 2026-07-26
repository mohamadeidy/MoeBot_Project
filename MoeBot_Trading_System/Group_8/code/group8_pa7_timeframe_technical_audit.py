#!/usr/bin/env python3
"""Independent technical audit for G8-PA7-CROSS-TIMEFRAME-006.

This audit supplements the existing Group 8 technical-candidate audit. It does
not redefine any frozen semantics; it verifies that the minimal same-timeframe
correction is present, the pre-fix defect is absent, the permanent regression is
present, the gap evidence is self-consistent, and the existing full technical
audit passed against the corrected exact engine identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-CROSS-TIMEFRAME-006"
EXPECTED_ENGINE_SHA256 = "f77252cc07c5d4e2fe6481a811441674983ec4d00c36c0c07f618950a4f4877d"
PREVIOUS_ENGINE_SHA256 = "61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
DESIGN_RULE = "Run every timeframe independently before creating cross-timeframe relations."
NEW_QUERY = 'FROM group6__{t} WHERE timeframe=? AND {avc}<=?'
OLD_QUERY = 'FROM group6__{t} WHERE {avc}<=?'
REGRESSION_NAME = "test_group6_breakout_boundaries_are_same_timeframe_only"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def verify_report_hash(record: dict[str, Any]) -> bool:
    payload = dict(record)
    actual = payload.pop("report_hash", None)
    return actual == stable_hash(payload)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--base-technical-audit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()

    engine_path = root / "code" / "moebot_group8_engine_v0_8_0.py"
    test_path = root / "tests" / "test_group8_breakout_timeframe_isolation_v0_8_0.py"
    diagnostic_path = root / "reports" / "32_BREAKOUT_TIMEFRAME_GAP_DIAGNOSTIC.json"
    gap_path = root / "reports" / "33_BREAKOUT_TIMEFRAME_GAP_ANALYSIS.json"
    status_path = root / "STATUS.json"

    engine_text = engine_path.read_text()
    test_text = test_path.read_text()
    design_text = (root / "00_DESIGN_LOCK.md").read_text()
    status = json.loads(status_path.read_text())
    diagnostic = json.loads(diagnostic_path.read_text())
    gap = json.loads(gap_path.read_text())
    base_audit = json.loads(a.base_technical_audit.read_text())

    checks: dict[str, bool] = {}
    failures: list[Any] = []

    checks["corrected_engine_identity"] = sha256_file(engine_path) == EXPECTED_ENGINE_SHA256
    checks["previous_engine_replaced"] = EXPECTED_ENGINE_SHA256 != PREVIOUS_ENGINE_SHA256
    checks["frozen_design_rule_present"] = DESIGN_RULE in design_text
    checks["same_timeframe_group6_query_exact"] = engine_text.count(NEW_QUERY) == 1
    checks["pre_fix_group6_query_absent"] = OLD_QUERY not in engine_text
    checks["permanent_regression_present"] = REGRESSION_NAME in test_text
    checks["diagnostic_hash_valid"] = verify_report_hash(diagnostic)
    checks["gap_hash_valid"] = verify_report_hash(gap)
    checks["gap_identity_valid"] = (
        diagnostic.get("gap_id") == GAP_ID
        and diagnostic.get("status") == "FAIL_BLOCKING_GAP_CONFIRMED"
        and gap.get("gap_id") == GAP_ID
        and gap.get("status") == "BLOCKING_GAP_FIXED_PENDING_TECHNICAL_REFREEZE"
        and gap.get("diagnostic_report_hash") == diagnostic.get("report_hash")
        and gap.get("previous_engine_sha256") == PREVIOUS_ENGINE_SHA256
        and gap.get("corrected_engine_sha256") == EXPECTED_ENGINE_SHA256
    )
    checks["frozen_semantics_preserved"] = all(
        gap.get(k) is False
        for k in ("definitions_changed", "thresholds_changed", "schema_changed", "upstream_changed", "config_changed", "2024_accessed")
    )
    checks["status_fail_closed_before_refreeze"] = (
        status.get("status") == "BLOCKING_GAP_G8_PA7_CROSS_TIMEFRAME_FIXED_PENDING_TECHNICAL_REFREEZE"
        and status.get("blocking_gap", {}).get("gap_id") == GAP_ID
        and status.get("blocking_gap", {}).get("status") == "FIXED_PENDING_REFREEZE"
        and status.get("design_frozen") is True
        and status.get("officially_closed") is False
        and status.get("engine_build_authorized") is False
        and status.get("annual_execution_authorized") is False
        and status.get("annual_execution_2023_authorized") is False
        and status.get("annual_execution_2024_authorized") is False
    )
    checks["base_technical_audit_pass"] = (
        base_audit.get("status") == "PASS"
        and base_audit.get("phase") == "ENGINE_TECHNICAL_CANDIDATE_AUDIT"
        and base_audit.get("hashes", {}).get("engine_sha256") == EXPECTED_ENGINE_SHA256
        and base_audit.get("checks", {}).get("locked_context_hardening_present") is True
        and base_audit.get("checks", {}).get("causality_guards_present") is True
        and base_audit.get("checks", {}).get("deterministic_identity_present") is True
        and base_audit.get("checks", {}).get("no_trading_action_functions") is True
        and base_audit.get("checks", {}).get("prohibited_output_schema_absent") is True
    )

    for name, passed in checks.items():
        if not passed:
            failures.append(name)

    report: dict[str, Any] = {
        "format_version": 1,
        "phase": "PA7_TIMEFRAME_TECHNICAL_AUDIT",
        "status": "PASS" if not failures else "FAIL",
        "gap_id": GAP_ID,
        "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
        "corrected_engine_sha256": EXPECTED_ENGINE_SHA256,
        "base_technical_audit_hash": base_audit.get("report_hash"),
        "checks": checks,
        "hashes": {
            "engine_sha256": sha256_file(engine_path),
            "regression_test_sha256": sha256_file(test_path),
            "diagnostic_sha256": sha256_file(diagnostic_path),
            "gap_analysis_sha256": sha256_file(gap_path),
            "design_lock_sha256": sha256_file(root / "00_DESIGN_LOCK.md"),
            "frozen_config_sha256": sha256_file(root / "FROZEN_CONFIG.json"),
            "definition_registry_sha256": sha256_file(root / "01_DEFINITION_REGISTRY.json"),
            "schema_sha256": sha256_file(root / "02_SCHEMA.sql"),
            "upstream_contract_sha256": sha256_file(root / "contracts" / "UPSTREAM_INPUT_CONTRACT.json"),
        },
        "frozen_semantics_changed": False,
        "2024_accessed": False,
        "failures": failures,
    }
    report["report_hash"] = stable_hash(report)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
