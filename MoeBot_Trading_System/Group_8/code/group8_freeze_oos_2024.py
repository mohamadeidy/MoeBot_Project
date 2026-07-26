#!/usr/bin/env python3
"""Create the immutable pre-2024 OOS freeze for MoeBot Group 8.

This tool is intentionally fail-closed. It may run only after a fully validated
2023 annual manifest has been merged and annual execution has been revoked. It
binds the exact frozen design, technical candidate, and 2023 validation identity,
then authorizes 2024 OOS only. It never changes engine/config/design content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


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

    status = json.loads(status_path.read_text())
    annual = json.loads(annual_path.read_text())
    build = json.loads(build_path.read_text())
    design = json.loads(design_path.read_text())
    config = json.loads(config_path.read_text())
    failures: list[str] = []

    if status.get("officially_closed") is not False: failures.append("group8_already_closed")
    if status.get("status") != "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED": failures.append("wrong_phase")
    if status.get("annual_execution_authorized") is not False: failures.append("annual_execution_not_revoked")
    if status.get("annual_execution_2023_authorized") is not False: failures.append("2023_execution_not_revoked")
    if status.get("annual_execution_2024_authorized") is not False: failures.append("2024_already_authorized")
    if annual.get("status") != "ANNUAL_2023_PASS": failures.append("annual_2023_manifest_not_pass")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS": failures.append("technical_candidate_not_pass")
    if design.get("status") != "FROZEN" or config.get("config_status") != "FROZEN": failures.append("design_or_config_not_frozen")

    av = status.get("annual_validation_2023", {})
    if av.get("manifest_hash") != annual.get("manifest_hash"): failures.append("status_annual_manifest_hash_mismatch")
    if av.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("status_build_manifest_hash_mismatch")
    if annual.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("annual_build_manifest_hash_mismatch")
    if annual.get("engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"): failures.append("annual_engine_identity_mismatch")
    if annual.get("postprocessor_sha256") != build.get("identities", {}).get("postprocessor", {}).get("sha256"): failures.append("annual_postprocessor_identity_mismatch")
    if annual.get("config_id") != build.get("config_id") or annual.get("config_id") != config.get("config_id"): failures.append("config_identity_mismatch")
    if build.get("design_freeze_hash") != design.get("design_freeze_hash"): failures.append("design_freeze_hash_mismatch")
    if build.get("annual_execution_2024_authorized") is not False: failures.append("technical_manifest_premature_2024_authorization")
    if annual.get("idempotence") != "PASS" or annual.get("clean_reconstruction") != "PASS": failures.append("2023_determinism_not_pass")
    if annual.get("causality") != "PASS" or annual.get("no_lookahead") != "PASS" or annual.get("no_backdating") != "PASS": failures.append("2023_causality_not_pass")
    if annual.get("duplicate_prevention") != "PASS" or annual.get("upstream_reference_integrity") != "PASS": failures.append("2023_integrity_not_pass")
    if annual.get("no_trading_outputs") is not True: failures.append("2023_trading_output_prohibition_not_pass")

    paths = [
        "00_DESIGN_LOCK.md", "01_DEFINITION_REGISTRY.json", "02_SCHEMA.sql", "FROZEN_CONFIG.json",
        "DESIGN_FREEZE_MANIFEST.json", "ENGINE_BUILD_MANIFEST.json", "ANNUAL_2023_VALIDATION_MANIFEST.json",
        "contracts/UPSTREAM_INPUT_CONTRACT.json", "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
        "UPSTREAM_ADAPTER_MAP.json", "UPSTREAM_VALUE_BINDINGS.json", "UPSTREAM_REFERENCE_RESOLUTION.json",
        "code/moebot_group8_engine_v0_8_0.py", "code/group8_materialize_inputs.py", "code/group8_postprocess_v0_8_0.py",
        "tests/test_group8_engine_v0_8_0.py", "tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json", "reports/30_ANNUAL_2023_MATERIALIZATION.json",
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
        "format_version": 1,
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
        "engine_sha256": annual["engine_sha256"],
        "postprocessor_sha256": annual["postprocessor_sha256"],
        "materializer_sha256": annual["materializer_sha256"],
        "logical_dependency_lineage_id": status["logical_dependency_lineage_id"],
        "annual_dependency_registry_hash": status["annual_dependency_registry_hash"],
        "identities": identities,
        "immutability_policy": {
            "engine_changes_before_2024_forbidden": True,
            "config_changes_before_2024_forbidden": True,
            "definition_changes_before_2024_forbidden": True,
            "schema_changes_before_2024_forbidden": True,
            "threshold_changes_before_2024_forbidden": True,
            "upstream_lineage_changes_before_2024_forbidden": True,
            "2023_result_conditioned_changes_forbidden": True,
        },
        "authorization": {"2023": False, "2024_oos": True},
        "policy": "2024 is a frozen out-of-sample evaluation. No post-2023 engine/config/design/schema/threshold/upstream mutation is permitted before or during 2024 execution.",
    }
    manifest["manifest_hash"] = hashlib.sha256(canonical(manifest)).hexdigest()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["oos_freeze_2024"] = {
        "status": "FROZEN_FOR_2024_OOS",
        "manifest_hash": manifest["manifest_hash"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "annual_2023_manifest_hash": annual["manifest_hash"],
        "engine_sha256": annual["engine_sha256"],
        "config_id": build["config_id"],
    }
    status["annual_execution_authorized"] = True
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = True
    status["status"] = "OOS_2024_FROZEN_AND_AUTHORIZED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": manifest["status"], "manifest_hash": manifest["manifest_hash"], "annual_2023_manifest_hash": annual["manifest_hash"], "engine_sha256": annual["engine_sha256"], "2024_oos_authorized": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
