#!/usr/bin/env python3
"""Independent technical audit for the approved PA7 transition-event amendment.

This binds the amended PA7E.2/A.2/P.2 frozen contract to the exact engine,
regressions and Gap 007 amendment evidence before 2023 may be re-authorized.
2024 OOS remains forbidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-ENUMERATION-EXPLOSION-007"
EXPECTED_ENGINE_SHA256 = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
EXPECTED_REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
EXPECTED_FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"
AMENDMENT_REPORT_HASH = "591fff2d535cd27326f37a97ae4278c2a20505101ad8a032804dc657f1866996"
STATE_KEY = ["symbol", "timeframe", "direction", "exact_boundary_identity", "pa7_variant"]
VERSIONS = {
    "pa_breakout_exact": "PA7E.2",
    "pa_breakout_atr_buffer": "PA7A.2",
    "pa_breakout_point_buffer": "PA7P.2",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def verify_report_hash(record: dict[str, Any]) -> bool:
    p = dict(record); actual = p.pop("report_hash", None)
    return actual == stable_hash(p)


def self_hash(record: dict[str, Any], field: str) -> str:
    p = dict(record); p.pop(field, None)
    return stable_hash(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group8-root", type=Path, required=True)
    ap.add_argument("--base-technical-audit", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    root = a.group8_root.resolve()

    engine_path = root / "code/moebot_group8_engine_v0_8_0.py"
    transition_test = root / "tests/test_group8_pa7_transition_event_v0_8_0.py"
    tf_test = root / "tests/test_group8_breakout_timeframe_isolation_v0_8_0.py"
    registry_path = root / "01_DEFINITION_REGISTRY.json"
    freeze_path = root / "DESIGN_FREEZE_MANIFEST.json"
    status_path = root / "STATUS.json"
    amendment_path = root / "reports/37_PA7_TRANSITION_EVENT_DESIGN_AMENDMENT.json"

    engine_text = engine_path.read_text()
    transition_text = transition_test.read_text()
    tf_text = tf_test.read_text()
    registry = json.loads(registry_path.read_text())
    freeze = json.loads(freeze_path.read_text())
    status = json.loads(status_path.read_text())
    amendment = json.loads(amendment_path.read_text())
    base = json.loads(a.base_technical_audit.read_text())

    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["exact_engine_identity"] = sha256_file(engine_path) == EXPECTED_ENGINE_SHA256
    checks["registry_identity"] = registry.get("registry_hash") == EXPECTED_REGISTRY_HASH and self_hash(registry, "registry_hash") == EXPECTED_REGISTRY_HASH
    checks["design_freeze_identity"] = freeze.get("design_freeze_hash") == EXPECTED_FREEZE_HASH and self_hash(freeze, "design_freeze_hash") == EXPECTED_FREEZE_HASH and freeze.get("definition_registry_hash") == EXPECTED_REGISTRY_HASH
    checks["amendment_evidence_valid"] = verify_report_hash(amendment) and amendment.get("report_hash") == AMENDMENT_REPORT_HASH and amendment.get("gap_id") == GAP_ID and amendment.get("approved_semantics") == "PA7_TRANSITION_EVENT_ENUMERATION" and amendment.get("oos_2024_accessed") is False

    variant_ok = True
    for definition_id, version in VERSIONS.items():
        d = registry.get("definitions", {}).get(definition_id, {})
        variant_ok = variant_ok and d.get("version") == version and d.get("state_key") == STATE_KEY and d.get("transition_rule") == "NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY only" and d.get("persistent_state_records_forbidden") is True and "rearm_rule" in d and "lifecycle_identity_rule" in d
    checks["three_independent_transition_variants_frozen"] = variant_ok

    markers = [
        "def _pa7_boundary_catalog", "def _pa7_boundary_active_at", "def _pa7_beyond",
        "def _pa7_state_boundary_identity", "def _pa7_emit_transition", "def _pa7_window",
        "transition_from", "NOT_BEYOND_BOUNDARY", "BEYOND_BOUNDARY",
        "previous_eligible_bar_id", "initialization_transition",
    ]
    checks["transition_engine_present"] = all(m in engine_text for m in markers)
    checks["persistent_nested_boundary_loop_removed"] = 'for bnd in self._boundary_rows_for_bar(bar):\n                    avail = max_time(bar.available_at' not in engine_text
    checks["same_timeframe_group6_guard_retained"] = 'FROM group6__{t} WHERE timeframe=?' in engine_text
    checks["regressions_present"] = all(x in transition_text for x in [
        "test_transition_only_rearm_variant_isolation_and_idempotence",
        "test_same_boundary_id_different_timeframe_has_different_state_key",
        "engine.process_breakouts()",
    ]) and "test_group6_breakout_boundaries_are_same_timeframe_only" in tf_text

    checks["base_technical_audit_pass"] = (
        base.get("status") == "PASS"
        and base.get("phase") == "ENGINE_TECHNICAL_CANDIDATE_AUDIT"
        and base.get("hashes", {}).get("engine_sha256") == EXPECTED_ENGINE_SHA256
        and base.get("checks", {}).get("frozen_identity") is True
        and base.get("checks", {}).get("causality_guards_present") is True
        and base.get("checks", {}).get("deterministic_identity_present") is True
        and base.get("checks", {}).get("no_trading_action_functions") is True
        and base.get("checks", {}).get("prohibited_output_schema_absent") is True
        and base.get("checks", {}).get("upstream_read_only_enforced") is True
    )

    blocking = status.get("blocking_gap", {})
    checks["fail_closed_pre_refreeze"] = (
        status.get("status") == "PA7_TRANSITION_EVENT_DESIGN_AMENDMENT_APPLIED_PENDING_TECHNICAL_REFREEZE"
        and blocking.get("gap_id") == GAP_ID
        and blocking.get("status") == "FIXED_PENDING_TECHNICAL_REFREEZE"
        and blocking.get("decision_required") is False
        and blocking.get("approved_design") == "PA7_TRANSITION_EVENT_ENUMERATION"
        and blocking.get("amended_engine_sha256") == EXPECTED_ENGINE_SHA256
        and blocking.get("amended_definition_registry_hash") == EXPECTED_REGISTRY_HASH
        and blocking.get("amended_design_freeze_hash") == EXPECTED_FREEZE_HASH
        and status.get("design_frozen") is True
        and status.get("officially_closed") is False
        and not status.get("engine_build_authorized")
        and not status.get("annual_execution_authorized")
        and not status.get("annual_execution_2023_authorized")
        and not status.get("annual_execution_2024_authorized")
    )
    checks["no_2024_access_or_logic"] = amendment.get("oos_2024_accessed") is False and blocking.get("oos_2024_accessed") is False and "year == 2024" not in engine_text and "year==2024" not in engine_text
    checks["upstream_lineage_unchanged"] = amendment.get("groups_1_7_changed") is False and amendment.get("upstream_lineage_changed") is False and freeze.get("logical_dependency_lineage_id") == "moebot-group8-upstream-corrected-v3-g7-v075-v1"
    checks["thresholds_schema_unchanged"] = amendment.get("thresholds_changed") is False and amendment.get("schema_changed") is False

    for name, ok in checks.items():
        if not ok:
            failures.append(name)

    report: dict[str, Any] = {
        "format_version": 1,
        "phase": "PA7_TRANSITION_EVENT_TECHNICAL_AUDIT",
        "status": "PASS" if not failures else "FAIL",
        "gap_id": GAP_ID,
        "engine_sha256": sha256_file(engine_path),
        "definition_registry_hash": registry.get("registry_hash"),
        "design_freeze_hash": freeze.get("design_freeze_hash"),
        "design_amendment_report_hash": amendment.get("report_hash"),
        "base_technical_audit_hash": base.get("report_hash"),
        "variant_versions": VERSIONS,
        "checks": checks,
        "hashes": {
            "engine_sha256": sha256_file(engine_path),
            "transition_regression_sha256": sha256_file(transition_test),
            "timeframe_regression_sha256": sha256_file(tf_test),
            "definition_registry_file_sha256": sha256_file(registry_path),
            "design_freeze_file_sha256": sha256_file(freeze_path),
            "amendment_report_file_sha256": sha256_file(amendment_path),
            "frozen_config_sha256": sha256_file(root / "FROZEN_CONFIG.json"),
            "schema_sha256": sha256_file(root / "02_SCHEMA.sql"),
            "upstream_contract_sha256": sha256_file(root / "contracts/UPSTREAM_INPUT_CONTRACT.json"),
        },
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
