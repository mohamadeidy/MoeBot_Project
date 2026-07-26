#!/usr/bin/env python3
"""Create the immutable pre-2024 OOS freeze for MoeBot Group 8.

Fail closed. This stage runs only after authoritative 2023 annual PASS and binds
all technical identities required for 2024 OOS, including the strengthened
annual validator and the closed locked-context gap evidence. It never changes
frozen definitions, thresholds, schema, config, engine semantics, or upstream
lineage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

LOCKED_CONTEXT_GAP_ID = "G8-ICT-LOCKED-CONTEXT-005"
LOCKED_CONTEXT_DIAGNOSTIC_HASH = "78ff7696f1140a7dc60b7f495db8898eba341201c1ae5036c37b771039915e81"


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def identity(root: Path, rel: str) -> dict[str, Any]:
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"missing OOS freeze identity file: {rel}")
    return {"path": rel, "size_bytes": p.stat().st_size, "sha256": shaf(p)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    annual_path = root / "ANNUAL_2023_VALIDATION_MANIFEST.json"
    build_path = root / "ENGINE_BUILD_MANIFEST.json"
    design_path = root / "DESIGN_FREEZE_MANIFEST.json"
    config_path = root / "FROZEN_CONFIG.json"
    validation_2023_path = root / "reports/32_ANNUAL_2023_VALIDATION.json"

    status = json.loads(status_path.read_text())
    annual = json.loads(annual_path.read_text())
    build = json.loads(build_path.read_text())
    design = json.loads(design_path.read_text())
    config = json.loads(config_path.read_text())
    validation_2023 = json.loads(validation_2023_path.read_text())
    failures: list[str] = []

    if status.get("officially_closed") is not False: failures.append("group8_already_closed")
    if status.get("status") != "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED": failures.append("wrong_phase")
    if status.get("annual_execution_authorized") is not False: failures.append("annual_execution_not_revoked")
    if status.get("annual_execution_2023_authorized") is not False: failures.append("2023_execution_not_revoked")
    if status.get("annual_execution_2024_authorized") is not False: failures.append("2024_already_authorized")
    if annual.get("status") != "ANNUAL_2023_PASS": failures.append("annual_2023_manifest_not_pass")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS" or int(build.get("format_version", 0)) < 2: failures.append("technical_candidate_v2_not_pass")
    if design.get("status") != "FROZEN" or config.get("config_status") != "FROZEN": failures.append("design_or_config_not_frozen")

    av = status.get("annual_validation_2023", {})
    if av.get("manifest_hash") != annual.get("manifest_hash"): failures.append("status_annual_manifest_hash_mismatch")
    if av.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("status_build_manifest_hash_mismatch")
    if annual.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("annual_build_manifest_hash_mismatch")
    if annual.get("engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"): failures.append("annual_engine_identity_mismatch")
    if annual.get("postprocessor_sha256") != build.get("identities", {}).get("postprocessor", {}).get("sha256"): failures.append("annual_postprocessor_identity_mismatch")
    if annual.get("materializer_sha256") != build.get("identities", {}).get("materializer", {}).get("sha256"): failures.append("annual_materializer_identity_mismatch")
    if annual.get("config_id") != build.get("config_id") or annual.get("config_id") != config.get("config_id"): failures.append("config_identity_mismatch")
    if build.get("design_freeze_hash") != design.get("design_freeze_hash"): failures.append("design_freeze_hash_mismatch")
    if build.get("annual_execution_2024_authorized") is not False: failures.append("technical_manifest_premature_2024_authorization")

    annual_validator = build.get("identities", {}).get("annual_validator", {})
    if not annual_validator.get("sha256") or annual_validator.get("path") != "code/group8_annual_validation.py": failures.append("annual_validator_identity_not_frozen")
    else:
        vp = root / annual_validator["path"]
        if not vp.is_file() or vp.stat().st_size != int(annual_validator["size_bytes"]) or shaf(vp) != annual_validator["sha256"]:
            failures.append("annual_validator_identity_drift")

    closed_gap = build.get("closed_blocking_gap", {})
    status_gap = status.get("blocking_gap", {})
    if closed_gap.get("gap_id") != LOCKED_CONTEXT_GAP_ID: failures.append("locked_context_gap_not_bound_in_build")
    if closed_gap.get("diagnostic_report_hash") != LOCKED_CONTEXT_DIAGNOSTIC_HASH: failures.append("locked_context_diagnostic_hash_mismatch")
    if status_gap.get("gap_id") != LOCKED_CONTEXT_GAP_ID or status_gap.get("status") != "CLOSED_BY_TECHNICAL_REFREEZE": failures.append("locked_context_gap_not_closed_in_status")
    if status_gap.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("locked_context_gap_build_hash_mismatch")
    if closed_gap.get("corrected_engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"): failures.append("locked_context_corrected_engine_mismatch")

    if annual.get("idempotence") != "PASS" or annual.get("clean_reconstruction") != "PASS": failures.append("2023_determinism_not_pass")
    if annual.get("causality") != "PASS" or annual.get("no_lookahead") != "PASS" or annual.get("no_backdating") != "PASS": failures.append("2023_causality_not_pass")
    if annual.get("duplicate_prevention") != "PASS" or annual.get("upstream_reference_integrity") != "PASS": failures.append("2023_integrity_not_pass")
    if annual.get("no_trading_outputs") is not True: failures.append("2023_trading_output_prohibition_not_pass")
    if validation_2023.get("status") != "PASS" or validation_2023.get("failures"): failures.append("2023_independent_validation_not_pass")
    if int(validation_2023.get("locked_context_violations", -1)) != 0: failures.append("2023_locked_context_violations_not_zero")

    paths = [
        "00_DESIGN_LOCK.md", "01_DEFINITION_REGISTRY.json", "02_SCHEMA.sql", "FROZEN_CONFIG.json",
        "DESIGN_FREEZE_MANIFEST.json", "ENGINE_BUILD_MANIFEST.json", "ANNUAL_2023_VALIDATION_MANIFEST.json",
        "contracts/UPSTREAM_INPUT_CONTRACT.json", "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
        "UPSTREAM_ADAPTER_MAP.json", "UPSTREAM_VALUE_BINDINGS.json", "UPSTREAM_REFERENCE_RESOLUTION.json",
        "code/moebot_group8_engine_v0_8_0.py", "code/group8_materialize_inputs.py", "code/group8_postprocess_v0_8_0.py",
        "code/group8_annual_validation.py",
        "tests/test_group8_engine_v0_8_0.py", "tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json", "reports/27_LOCKED_CONTEXT_GAP_DIAGNOSTIC.json",
        "reports/28_LOCKED_CONTEXT_GAP_ANALYSIS.json", "reports/30_ANNUAL_2023_MATERIALIZATION.json",
        "reports/31_ANNUAL_2023_ENGINE_AUDIT.json", "reports/32_ANNUAL_2023_VALIDATION.json",
        "reports/33_ANNUAL_2023_OUTPUT_FINGERPRINT.json", "reports/34_ANNUAL_2023_CLEAN_RECONSTRUCTION.json",
    ]
    identities: dict[str, Any] = {}
    if not failures:
        for rel in paths:
            identities[rel] = identity(root, rel)

    if failures:
        raise SystemExit(";".join(failures))

    manifest = {
        "format_version": 2,
        "status": "FROZEN_FOR_2024_OOS",
        "group": 8,
        "oos_year": 2024,
        "training_validation_year": 2023,
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": build["config_id"],
        "design_freeze_hash": design["design_freeze_hash"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "annual_2023_manifest_hash": annual["manifest_hash"],
        "annual_2023_logical_fingerprint": annual["logical_fingerprint"],
        "engine_sha256": build["identities"]["engine"]["sha256"],
        "postprocessor_sha256": build["identities"]["postprocessor"]["sha256"],
        "materializer_sha256": build["identities"]["materializer"]["sha256"],
        "annual_validator_sha256": annual_validator["sha256"],
        "closed_blocking_gap": {
            "gap_id": LOCKED_CONTEXT_GAP_ID,
            "diagnostic_report_hash": LOCKED_CONTEXT_DIAGNOSTIC_HASH,
            "gap_analysis_report_hash": closed_gap["gap_analysis_report_hash"],
            "corrected_engine_sha256": closed_gap["corrected_engine_sha256"],
            "2023_locked_context_violations": 0,
        },
        "logical_dependency_lineage_id": status["logical_dependency_lineage_id"],
        "annual_dependency_registry_hash": status["annual_dependency_registry_hash"],
        "identities": identities,
        "immutability_policy": {
            "engine_changes_before_2024_forbidden": True,
            "postprocessor_changes_before_2024_forbidden": True,
            "annual_validator_changes_before_2024_forbidden": True,
            "config_changes_before_2024_forbidden": True,
            "definition_changes_before_2024_forbidden": True,
            "schema_changes_before_2024_forbidden": True,
            "threshold_changes_before_2024_forbidden": True,
            "upstream_lineage_changes_before_2024_forbidden": True,
            "locked_context_fix_changes_before_2024_forbidden": True,
            "2023_result_conditioned_changes_forbidden": True,
        },
        "authorization": {"2023": False, "2024_oos": True},
        "policy": "2024 is a frozen out-of-sample evaluation. No post-2023 engine/postprocessor/annual-validator/config/design/schema/threshold/upstream or locked-context-fix mutation is permitted before or during 2024 execution.",
    }
    manifest["manifest_hash"] = hashlib.sha256(canonical(manifest)).hexdigest()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["oos_freeze_2024"] = {
        "status": "FROZEN_FOR_2024_OOS",
        "manifest_hash": manifest["manifest_hash"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "annual_2023_manifest_hash": annual["manifest_hash"],
        "engine_sha256": manifest["engine_sha256"],
        "annual_validator_sha256": manifest["annual_validator_sha256"],
        "closed_gap_id": LOCKED_CONTEXT_GAP_ID,
        "config_id": build["config_id"],
    }
    status["annual_execution_authorized"] = True
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = True
    status["status"] = "OOS_2024_FROZEN_AND_AUTHORIZED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": manifest["status"], "manifest_hash": manifest["manifest_hash"], "annual_2023_manifest_hash": annual["manifest_hash"], "engine_sha256": manifest["engine_sha256"], "annual_validator_sha256": manifest["annual_validator_sha256"], "closed_gap_id": LOCKED_CONTEXT_GAP_ID, "2024_oos_authorized": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
