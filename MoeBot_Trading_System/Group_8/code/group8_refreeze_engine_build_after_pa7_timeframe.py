#!/usr/bin/env python3
"""Exact technical re-freeze after G8-PA7-CROSS-TIMEFRAME-006.

This tool is fail-closed. It may run only after the minimal PA7 same-timeframe
correction, full legacy technical regression, lifecycle/locked-context regression,
permanent PA7 isolation regression, the existing independent technical audit, and
the new PA7-specific independent audit all pass. Frozen design/config/schema and
upstream lineage remain unchanged. Only 2023 engineering validation is re-authorized;
2024 OOS remains forbidden.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from moebot_group8_engine_v0_8_0 import ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, sha256_file, stable_hash

GAP_ID = "G8-PA7-CROSS-TIMEFRAME-006"
PREVIOUS_ENGINE_SHA256 = "61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
CORRECTED_ENGINE_SHA256 = "f77252cc07c5d4e2fe6481a811441674983ec4d00c36c0c07f618950a4f4877d"
PREVIOUS_GAP_ID = "G8-ICT-LOCKED-CONTEXT-005"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--base-technical-audit", type=Path, required=True)
    p.add_argument("--pa7-technical-audit", type=Path, required=True)
    p.add_argument("--manifest-output", type=Path, required=True)
    a = p.parse_args()

    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    status = json.loads(status_path.read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    old_manifest = json.loads(a.manifest_output.read_text())
    gap = json.loads((root / "reports" / "33_BREAKOUT_TIMEFRAME_GAP_ANALYSIS.json").read_text())
    diagnostic = json.loads((root / "reports" / "32_BREAKOUT_TIMEFRAME_GAP_DIAGNOSTIC.json").read_text())
    base_audit = json.loads(a.base_technical_audit.read_text())
    pa7_audit = json.loads(a.pa7_technical_audit.read_text())

    if status.get("design_frozen") is not True or status.get("officially_closed") is not False:
        raise SystemExit("invalid Group 8 freeze/closure state")
    if status.get("status") != "BLOCKING_GAP_G8_PA7_CROSS_TIMEFRAME_FIXED_PENDING_TECHNICAL_REFREEZE":
        raise SystemExit("wrong pre-refreeze STATUS phase")
    blocking = status.get("blocking_gap", {})
    if blocking.get("gap_id") != GAP_ID or blocking.get("status") != "FIXED_PENDING_REFREEZE":
        raise SystemExit("blocking gap identity/state mismatch")
    if blocking.get("previous_engine_sha256") != PREVIOUS_ENGINE_SHA256 or blocking.get("corrected_engine_sha256") != CORRECTED_ENGINE_SHA256:
        raise SystemExit("blocking gap engine lineage mismatch")
    if blocking.get("previous_closed_gap_id") != PREVIOUS_GAP_ID:
        raise SystemExit("previous closed gap lineage mismatch")
    for key in ("definitions_changed", "thresholds_changed", "schema_changed", "upstream_changed", "config_changed"):
        if blocking.get(key) is not False or gap.get(key) is not False:
            raise SystemExit(f"frozen semantics mutation flag:{key}")
    if gap.get("2024_accessed") is not False:
        raise SystemExit("2024 was accessed before authorization")
    if gap.get("gap_id") != GAP_ID or gap.get("status") != "BLOCKING_GAP_FIXED_PENDING_TECHNICAL_REFREEZE":
        raise SystemExit("gap analysis identity/state mismatch")
    if diagnostic.get("gap_id") != GAP_ID or gap.get("diagnostic_report_hash") != diagnostic.get("report_hash"):
        raise SystemExit("diagnostic/gap lineage mismatch")
    if any(status.get(k) for k in ("engine_build_authorized", "annual_execution_authorized", "annual_execution_2023_authorized", "annual_execution_2024_authorized")):
        raise SystemExit("all execution authorization must remain revoked before refreeze")

    if base_audit.get("status") != "PASS" or base_audit.get("phase") != "ENGINE_TECHNICAL_CANDIDATE_AUDIT":
        raise SystemExit("base technical audit is not PASS")
    if pa7_audit.get("status") != "PASS" or pa7_audit.get("phase") != "PA7_TIMEFRAME_TECHNICAL_AUDIT" or pa7_audit.get("gap_id") != GAP_ID:
        raise SystemExit("PA7 technical audit is not PASS")
    if base_audit.get("hashes", {}).get("engine_sha256") != CORRECTED_ENGINE_SHA256:
        raise SystemExit("base audit engine identity mismatch")
    if pa7_audit.get("corrected_engine_sha256") != CORRECTED_ENGINE_SHA256 or pa7_audit.get("checks", {}).get("same_timeframe_group6_query_exact") is not True:
        raise SystemExit("PA7 audit corrected-engine proof missing")
    if pa7_audit.get("checks", {}).get("base_technical_audit_pass") is not True:
        raise SystemExit("PA7 audit did not bind to passing base technical audit")

    files = {
        "engine": "code/moebot_group8_engine_v0_8_0.py",
        "materializer": "code/group8_materialize_inputs.py",
        "postprocessor": "code/group8_postprocess_v0_8_0.py",
        "annual_validator": "code/group8_annual_validation.py",
        "tests": "tests/test_group8_engine_v0_8_0.py",
        "lifecycle_tests": "tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "pa7_timeframe_tests": "tests/test_group8_breakout_timeframe_isolation_v0_8_0.py",
        "technical_audit": "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json",
        "pa7_timeframe_technical_audit": "reports/34_PA7_TIMEFRAME_TECHNICAL_AUDIT.json",
        "locked_context_gap_analysis": "reports/28_LOCKED_CONTEXT_GAP_ANALYSIS.json",
        "locked_context_gap_diagnostic": "reports/27_LOCKED_CONTEXT_GAP_DIAGNOSTIC.json",
        "breakout_cardinality_diagnostic": "reports/31_BREAKOUT_CARDINALITY_DIAGNOSTIC.json",
        "pa7_timeframe_gap_diagnostic": "reports/32_BREAKOUT_TIMEFRAME_GAP_DIAGNOSTIC.json",
        "pa7_timeframe_gap_analysis": "reports/33_BREAKOUT_TIMEFRAME_GAP_ANALYSIS.json",
        "schema": "02_SCHEMA.sql",
        "definitions": "01_DEFINITION_REGISTRY.json",
        "config": "FROZEN_CONFIG.json",
        "upstream_contract": "contracts/UPSTREAM_INPUT_CONTRACT.json",
    }
    identities = {
        name: {
            "path": rel,
            "sha256": sha256_file(root / rel),
            "size_bytes": (root / rel).stat().st_size,
        }
        for name, rel in files.items()
    }
    if identities["engine"]["sha256"] != CORRECTED_ENGINE_SHA256:
        raise SystemExit("corrected engine bytes do not match audited identity")
    if identities["engine"]["sha256"] == PREVIOUS_ENGINE_SHA256:
        raise SystemExit("corrected engine did not change")
    if identities["technical_audit"]["sha256"] != sha256_file(a.base_technical_audit):
        raise SystemExit("base audit path mismatch")
    if identities["pa7_timeframe_technical_audit"]["sha256"] != sha256_file(a.pa7_technical_audit):
        raise SystemExit("PA7 audit path mismatch")

    previous_closed = old_manifest.get("closed_blocking_gap")
    if not isinstance(previous_closed, dict) or previous_closed.get("gap_id") != PREVIOUS_GAP_ID:
        raise SystemExit("previous engine manifest gap lineage missing")

    manifest = {
        "format_version": 3,
        "status": "TECHNICAL_CANDIDATE_PASS",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": CONFIG_ID,
        "design_freeze_hash": freeze["design_freeze_hash"],
        "definition_registry_hash": freeze["definition_registry_hash"],
        "upstream_contract_hash": freeze["upstream_contract_hash"],
        "technical_audit_hash": base_audit["report_hash"],
        "supplemental_technical_audit_hash": pa7_audit["report_hash"],
        "identities": identities,
        "previous_closed_blocking_gap": previous_closed,
        "closed_blocking_gap": {
            "gap_id": GAP_ID,
            "diagnostic_report_hash": diagnostic["report_hash"],
            "gap_analysis_report_hash": gap["report_hash"],
            "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
            "corrected_engine_sha256": CORRECTED_ENGINE_SHA256,
            "base_technical_audit_hash": base_audit["report_hash"],
            "supplemental_technical_audit_hash": pa7_audit["report_hash"],
        },
        "annual_execution_2023_authorized": True,
        "annual_execution_2024_authorized": False,
        "policy": "2023 in-sample engineering validation re-authorized only after PA7 cross-timeframe Group6 leakage was fixed, all prior technical/lifecycle regressions passed, the new same-timeframe regression passed, and exact corrected identities were independently audited and re-frozen. 2024 remains forbidden until post-2023 OOS freeze.",
    }
    manifest["manifest_hash"] = stable_hash(manifest)
    a.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["engine_build"] = {
        "status": "TECHNICAL_CANDIDATE_PASS",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": CONFIG_ID,
        "engine_sha256": identities["engine"]["sha256"],
        "materializer_sha256": identities["materializer"]["sha256"],
        "postprocessor_sha256": identities["postprocessor"]["sha256"],
        "annual_validator_sha256": identities["annual_validator"]["sha256"],
        "technical_audit_hash": base_audit["report_hash"],
        "supplemental_technical_audit_hash": pa7_audit["report_hash"],
        "engine_build_manifest_hash": manifest["manifest_hash"],
        "closed_gap_id": GAP_ID,
    }
    status["blocking_gap"] = {
        **blocking,
        "status": "CLOSED_BY_TECHNICAL_REFREEZE",
        "corrected_engine_sha256": identities["engine"]["sha256"],
        "technical_audit_hash": base_audit["report_hash"],
        "supplemental_technical_audit_hash": pa7_audit["report_hash"],
        "engine_build_manifest_hash": manifest["manifest_hash"],
    }
    status["engine_build_authorized"] = True
    status["annual_execution_authorized"] = True
    status["annual_execution_2023_authorized"] = True
    status["annual_execution_2024_authorized"] = False
    status["status"] = "ENGINE_TECHNICAL_CANDIDATE_PASS_2023_AUTHORIZED"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "status": "PASS",
        "closed_gap_id": GAP_ID,
        "engine_sha256": identities["engine"]["sha256"],
        "technical_audit_hash": base_audit["report_hash"],
        "supplemental_technical_audit_hash": pa7_audit["report_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "2023_authorized": True,
        "2024_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
