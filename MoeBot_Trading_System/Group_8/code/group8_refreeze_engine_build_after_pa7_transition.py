#!/usr/bin/env python3
"""Exact technical re-freeze after the approved PA7 transition-event amendment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from moebot_group8_engine_v0_8_0 import ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, sha256_file, stable_hash

GAP_ID = "G8-PA7-ENUMERATION-EXPLOSION-007"
ENGINE_SHA = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"
AMENDMENT_REPORT_HASH = "591fff2d535cd27326f37a97ae4278c2a20505101ad8a032804dc657f1866996"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--base-technical-audit", type=Path, required=True)
    p.add_argument("--pa7-transition-audit", type=Path, required=True)
    p.add_argument("--manifest-output", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    status = json.loads(status_path.read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    old_manifest = json.loads(a.manifest_output.read_text())
    amendment = json.loads((root / "reports/37_PA7_TRANSITION_EVENT_DESIGN_AMENDMENT.json").read_text())
    base = json.loads(a.base_technical_audit.read_text())
    pa7 = json.loads(a.pa7_transition_audit.read_text())

    if status.get("design_frozen") is not True or status.get("officially_closed") is not False:
        raise SystemExit("invalid Group 8 phase")
    if status.get("status") != "PA7_TRANSITION_EVENT_DESIGN_AMENDMENT_APPLIED_PENDING_TECHNICAL_REFREEZE":
        raise SystemExit("wrong pre-refreeze status")
    blocking = status.get("blocking_gap", {})
    if blocking.get("gap_id") != GAP_ID or blocking.get("status") != "FIXED_PENDING_TECHNICAL_REFREEZE" or blocking.get("decision_required") is not False:
        raise SystemExit("Gap 007 is not fixed-pending-refreeze")
    if any(status.get(k) for k in ("engine_build_authorized", "annual_execution_authorized", "annual_execution_2023_authorized", "annual_execution_2024_authorized")):
        raise SystemExit("execution must remain fail-closed before refreeze")
    if blocking.get("amended_engine_sha256") != ENGINE_SHA or blocking.get("amended_definition_registry_hash") != REGISTRY_HASH or blocking.get("amended_design_freeze_hash") != FREEZE_HASH:
        raise SystemExit("amended identities mismatch")
    if blocking.get("oos_2024_accessed") is not False or amendment.get("oos_2024_accessed") is not False:
        raise SystemExit("2024 was accessed")
    if amendment.get("report_hash") != AMENDMENT_REPORT_HASH:
        raise SystemExit("design amendment report identity mismatch")
    if freeze.get("design_freeze_hash") != FREEZE_HASH or freeze.get("definition_registry_hash") != REGISTRY_HASH:
        raise SystemExit("amended frozen design identity mismatch")
    if base.get("status") != "PASS" or base.get("phase") != "ENGINE_TECHNICAL_CANDIDATE_AUDIT" or base.get("hashes", {}).get("engine_sha256") != ENGINE_SHA:
        raise SystemExit("base technical audit not PASS on amended engine")
    if pa7.get("status") != "PASS" or pa7.get("phase") != "PA7_TRANSITION_EVENT_TECHNICAL_AUDIT" or pa7.get("gap_id") != GAP_ID or pa7.get("engine_sha256") != ENGINE_SHA:
        raise SystemExit("PA7 transition technical audit not PASS")
    if pa7.get("base_technical_audit_hash") != base.get("report_hash") or pa7.get("design_amendment_report_hash") != AMENDMENT_REPORT_HASH:
        raise SystemExit("technical audit lineage mismatch")

    files = {
        "engine": "code/moebot_group8_engine_v0_8_0.py",
        "materializer": "code/group8_materialize_inputs.py",
        "postprocessor": "code/group8_postprocess_v0_8_0.py",
        "annual_validator": "code/group8_annual_validation.py",
        "tests": "tests/test_group8_engine_v0_8_0.py",
        "lifecycle_tests": "tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "pa7_timeframe_tests": "tests/test_group8_breakout_timeframe_isolation_v0_8_0.py",
        "pa7_transition_tests": "tests/test_group8_pa7_transition_event_v0_8_0.py",
        "technical_audit": "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json",
        "pa7_transition_technical_audit": "reports/38_PA7_TRANSITION_EVENT_TECHNICAL_AUDIT.json",
        "pa7_design_amendment": "reports/37_PA7_TRANSITION_EVENT_DESIGN_AMENDMENT.json",
        "pa7_enumeration_blocker": "reports/36_PA7_ENUMERATION_DESIGN_BLOCKER.json",
        "postfix_cardinality_diagnostic": "reports/35_POSTFIX_BREAKOUT_CARDINALITY_DIAGNOSTIC.json",
        "pa7_timeframe_technical_audit_historical": "reports/34_PA7_TIMEFRAME_TECHNICAL_AUDIT.json",
        "schema": "02_SCHEMA.sql",
        "definitions": "01_DEFINITION_REGISTRY.json",
        "design_freeze": "DESIGN_FREEZE_MANIFEST.json",
        "config": "FROZEN_CONFIG.json",
        "upstream_contract": "contracts/UPSTREAM_INPUT_CONTRACT.json",
    }
    identities = {name: {"path": rel, "sha256": sha256_file(root / rel), "size_bytes": (root / rel).stat().st_size} for name, rel in files.items()}
    if identities["engine"]["sha256"] != ENGINE_SHA:
        raise SystemExit("amended engine bytes drifted")
    if identities["technical_audit"]["sha256"] != sha256_file(a.base_technical_audit) or identities["pa7_transition_technical_audit"]["sha256"] != sha256_file(a.pa7_transition_audit):
        raise SystemExit("audit file path mismatch")

    previous_closed = old_manifest.get("closed_blocking_gap")
    if not isinstance(previous_closed, dict) or previous_closed.get("gap_id") != "G8-PA7-CROSS-TIMEFRAME-006":
        raise SystemExit("historical Gap006 closure lineage missing")

    manifest = {
        "format_version": 4,
        "status": "TECHNICAL_CANDIDATE_PASS",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": CONFIG_ID,
        "design_freeze_hash": FREEZE_HASH,
        "definition_registry_hash": REGISTRY_HASH,
        "upstream_contract_hash": freeze["upstream_contract_hash"],
        "technical_audit_hash": base["report_hash"],
        "supplemental_technical_audit_hash": pa7["report_hash"],
        "design_amendment_report_hash": AMENDMENT_REPORT_HASH,
        "identities": identities,
        "previous_closed_blocking_gap": previous_closed,
        "closed_blocking_gap": {
            "gap_id": GAP_ID,
            "classification": "FROZEN_DESIGN_CARDINALITY_CONTRADICTION",
            "resolution": "PA7_TRANSITION_EVENT_ENUMERATION",
            "design_amendment_report_hash": AMENDMENT_REPORT_HASH,
            "amended_engine_sha256": ENGINE_SHA,
            "amended_definition_registry_hash": REGISTRY_HASH,
            "amended_design_freeze_hash": FREEZE_HASH,
            "base_technical_audit_hash": base["report_hash"],
            "supplemental_technical_audit_hash": pa7["report_hash"],
        },
        "annual_execution_2023_authorized": True,
        "annual_execution_2024_authorized": False,
        "policy": "2023 engineering validation is re-authorized only after the approved PA7 transition-event Design Amendment, full legacy/lifecycle/timeframe/transition regressions, independent base audit, independent PA7 transition audit, and exact identity refreeze. 2024 remains forbidden until successful 2023 validation and explicit OOS freeze.",
    }
    manifest["manifest_hash"] = stable_hash(manifest)
    a.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["engine_build"] = {
        "status": "TECHNICAL_CANDIDATE_PASS",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": CONFIG_ID,
        "engine_sha256": ENGINE_SHA,
        "materializer_sha256": identities["materializer"]["sha256"],
        "postprocessor_sha256": identities["postprocessor"]["sha256"],
        "annual_validator_sha256": identities["annual_validator"]["sha256"],
        "technical_audit_hash": base["report_hash"],
        "supplemental_technical_audit_hash": pa7["report_hash"],
        "engine_build_manifest_hash": manifest["manifest_hash"],
        "closed_gap_id": GAP_ID,
    }
    status["blocking_gap"] = {
        **blocking,
        "status": "CLOSED_BY_TECHNICAL_REFREEZE",
        "technical_audit_hash": base["report_hash"],
        "supplemental_technical_audit_hash": pa7["report_hash"],
        "engine_build_manifest_hash": manifest["manifest_hash"],
    }
    status["engine_build_authorized"] = True
    status["annual_execution_authorized"] = True
    status["annual_execution_2023_authorized"] = True
    status["annual_execution_2024_authorized"] = False
    status["status"] = "ENGINE_TECHNICAL_CANDIDATE_PASS_2023_AUTHORIZED"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({"status": "PASS", "closed_gap_id": GAP_ID, "engine_sha256": ENGINE_SHA, "manifest_hash": manifest["manifest_hash"], "2023_authorized": True, "2024_authorized": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
