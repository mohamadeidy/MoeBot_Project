#!/usr/bin/env python3
"""Finalize official MoeBot Group 8 closure and next-group handoff.

Runs only after 2023 PASS, immutable pre-2024 OOS freeze, frozen 2024 OOS PASS,
and independent cross-year PASS. It creates permanent closure/audit/handoff
manifests and marks Group 8 officially closed. Large annual databases are
referenced as immutable GitHub Release assets by exact SHA/size.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELEASE_TAG = "moebot-group8-v0.8.0"


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def file_identity(root: Path, rel: str) -> dict[str, Any]:
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"missing closure file: {rel}")
    return {"path": rel, "size_bytes": p.stat().st_size, "sha256": shaf(p)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--cross-year", type=Path, required=True)
    p.add_argument("--final-audit-output", type=Path, required=True)
    p.add_argument("--next-group-output", type=Path, required=True)
    p.add_argument("--closure-output", type=Path, required=True)
    p.add_argument("--handoff-output", type=Path, required=True)
    a = p.parse_args()

    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    status = load(status_path)
    design = load(root / "DESIGN_FREEZE_MANIFEST.json")
    build = load(root / "ENGINE_BUILD_MANIFEST.json")
    annual23 = load(root / "ANNUAL_2023_VALIDATION_MANIFEST.json")
    oos = load(root / "OOS_FREEZE_MANIFEST.json")
    annual24 = load(root / "ANNUAL_2024_OOS_VALIDATION_MANIFEST.json")
    cross = load(a.cross_year)
    failures: list[str] = []

    if status.get("officially_closed") is not False: failures.append("already_officially_closed")
    if status.get("status") != "ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED": failures.append("wrong_closure_phase")
    if status.get("annual_execution_authorized") or status.get("annual_execution_2023_authorized") or status.get("annual_execution_2024_authorized"):
        failures.append("annual_execution_not_revoked")
    if design.get("status") != "FROZEN": failures.append("design_not_frozen")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS": failures.append("technical_candidate_not_pass")
    if annual23.get("status") != "ANNUAL_2023_PASS": failures.append("annual_2023_not_pass")
    if oos.get("status") != "FROZEN_FOR_2024_OOS": failures.append("oos_freeze_not_pass")
    if annual24.get("status") != "ANNUAL_2024_OOS_PASS": failures.append("annual_2024_oos_not_pass")
    if cross.get("status") != "PASS": failures.append("cross_year_not_pass")
    if cross.get("identity_stable_across_oos_boundary") is not True: failures.append("cross_year_identity_instability")
    if cross.get("no_trading_outputs_both_years") is not True: failures.append("trading_output_prohibition_failure")
    if cross.get("read_only_upstream_both_years") is not True: failures.append("read_only_upstream_failure")

    expected = {
        "design_freeze_hash": design.get("design_freeze_hash"),
        "engine_build_manifest_hash": build.get("manifest_hash"),
        "engine_sha256": build.get("identities", {}).get("engine", {}).get("sha256"),
        "config_id": build.get("config_id"),
    }
    if annual23.get("engine_build_manifest_hash") != expected["engine_build_manifest_hash"]: failures.append("2023_build_identity_drift")
    if annual24.get("engine_build_manifest_hash") != expected["engine_build_manifest_hash"]: failures.append("2024_build_identity_drift")
    if annual23.get("engine_sha256") != expected["engine_sha256"] or annual24.get("engine_sha256") != expected["engine_sha256"]: failures.append("annual_engine_identity_drift")
    if annual23.get("config_id") != expected["config_id"] or annual24.get("config_id") != expected["config_id"]: failures.append("annual_config_identity_drift")
    if oos.get("engine_build_manifest_hash") != expected["engine_build_manifest_hash"]: failures.append("oos_build_identity_drift")
    if oos.get("annual_2023_manifest_hash") != annual23.get("manifest_hash"): failures.append("oos_2023_identity_drift")
    if annual24.get("oos_freeze_manifest_hash") != oos.get("manifest_hash"): failures.append("2024_oos_freeze_identity_drift")

    permanent_files = [
        "00_DESIGN_LOCK.md", "01_DEFINITION_REGISTRY.json", "02_SCHEMA.sql", "FROZEN_CONFIG.json",
        "DESIGN_FREEZE_MANIFEST.json", "ENGINE_BUILD_MANIFEST.json", "ANNUAL_2023_VALIDATION_MANIFEST.json",
        "OOS_FREEZE_MANIFEST.json", "ANNUAL_2024_OOS_VALIDATION_MANIFEST.json",
        "contracts/UPSTREAM_INPUT_CONTRACT.json", "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
        "UPSTREAM_ADAPTER_MAP.json", "UPSTREAM_VALUE_BINDINGS.json", "UPSTREAM_REFERENCE_RESOLUTION.json",
        "code/moebot_group8_engine_v0_8_0.py", "code/group8_materialize_inputs.py", "code/group8_postprocess_v0_8_0.py",
        "tests/test_group8_engine_v0_8_0.py", "tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json",
        "reports/30_ANNUAL_2023_MATERIALIZATION.json", "reports/31_ANNUAL_2023_ENGINE_AUDIT.json",
        "reports/32_ANNUAL_2023_VALIDATION.json", "reports/33_ANNUAL_2023_OUTPUT_FINGERPRINT.json",
        "reports/34_ANNUAL_2023_CLEAN_RECONSTRUCTION.json",
        "reports/40_ANNUAL_2024_MATERIALIZATION.json", "reports/41_ANNUAL_2024_ENGINE_AUDIT.json",
        "reports/42_ANNUAL_2024_OOS_VALIDATION.json", "reports/43_ANNUAL_2024_OUTPUT_FINGERPRINT.json",
        "reports/44_ANNUAL_2024_CLEAN_RECONSTRUCTION.json", "reports/50_CROSS_YEAR_VALIDATION.json",
    ]
    identities: dict[str, Any] = {}
    if not failures:
        for rel in permanent_files:
            identities[rel] = file_identity(root, rel)

    for label, annual in (("2023", annual23), ("2024", annual24)):
        comp = annual.get("compressed_asset", {})
        db = annual.get("database", {})
        if not comp.get("filename") or not comp.get("sha256") or not comp.get("size_bytes"): failures.append(f"{label}_compressed_asset_identity_missing")
        if not db.get("filename") or not db.get("sha256") or not db.get("logical_sha256"): failures.append(f"{label}_database_identity_missing")

    checks = {
        "design_frozen": design.get("status") == "FROZEN",
        "technical_candidate_pass": build.get("status") == "TECHNICAL_CANDIDATE_PASS",
        "annual_2023_pass": annual23.get("status") == "ANNUAL_2023_PASS",
        "pre_2024_oos_freeze_pass": oos.get("status") == "FROZEN_FOR_2024_OOS",
        "annual_2024_oos_pass": annual24.get("status") == "ANNUAL_2024_OOS_PASS",
        "cross_year_pass": cross.get("status") == "PASS",
        "oos_identity_stable": cross.get("identity_stable_across_oos_boundary") is True,
        "causal_and_no_trading_outputs": cross.get("no_trading_outputs_both_years") is True,
        "read_only_upstream": cross.get("read_only_upstream_both_years") is True,
        "annual_execution_revoked": not any([status.get("annual_execution_authorized"), status.get("annual_execution_2023_authorized"), status.get("annual_execution_2024_authorized")]),
        "no_blocking_failures": not failures,
    }
    if not all(checks.values()):
        failures.extend([f"final_check:{k}" for k, v in checks.items() if not v])
    if failures:
        raise SystemExit(";".join(sorted(set(failures))))

    audit = {
        "format_version": 1,
        "status": "PASS",
        "group": 8,
        "phase": "FINAL_INDEPENDENT_AUDIT",
        "checks": checks,
        "design_freeze_hash": expected["design_freeze_hash"],
        "engine_build_manifest_hash": expected["engine_build_manifest_hash"],
        "engine_sha256": expected["engine_sha256"],
        "config_id": expected["config_id"],
        "annual_2023_manifest_hash": annual23["manifest_hash"],
        "oos_freeze_manifest_hash": oos["manifest_hash"],
        "annual_2024_oos_manifest_hash": annual24["manifest_hash"],
        "cross_year_report_hash": cross["report_hash"],
        "official_closure_authorized": True,
    }
    audit["report_hash"] = hashlib.sha256(canonical(audit)).hexdigest()
    a.final_audit_output.parent.mkdir(parents=True, exist_ok=True)
    a.final_audit_output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    identities["reports/51_FINAL_INDEPENDENT_AUDIT.json"] = file_identity(root, str(a.final_audit_output.relative_to(root)))

    next_group = {
        "format_version": 1,
        "status": "FROZEN_HANDOFF",
        "source_group": 8,
        "source_group_name": status.get("name"),
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": expected["config_id"],
        "logical_dependency_lineage_id": status["logical_dependency_lineage_id"],
        "design_freeze_hash": expected["design_freeze_hash"],
        "engine_build_manifest_hash": expected["engine_build_manifest_hash"],
        "engine_sha256": expected["engine_sha256"],
        "annual_2023_manifest_hash": annual23["manifest_hash"],
        "annual_2024_oos_manifest_hash": annual24["manifest_hash"],
        "cross_year_report_hash": cross["report_hash"],
        "final_audit_hash": audit["report_hash"],
        "required_release_tag": RELEASE_TAG,
        "annual_database_assets": {
            "2023": {
                "release_asset_name": annual23["compressed_asset"]["filename"],
                "compressed_size_bytes": annual23["compressed_asset"]["size_bytes"],
                "compressed_sha256": annual23["compressed_asset"]["sha256"],
                "database_filename": annual23["database"]["filename"],
                "database_size_bytes": annual23["database"]["size_bytes"],
                "database_sha256": annual23["database"]["sha256"],
                "database_logical_sha256": annual23["database"]["logical_sha256"],
            },
            "2024": {
                "release_asset_name": annual24["compressed_asset"]["filename"],
                "compressed_size_bytes": annual24["compressed_asset"]["size_bytes"],
                "compressed_sha256": annual24["compressed_asset"]["sha256"],
                "database_filename": annual24["database"]["filename"],
                "database_size_bytes": annual24["database"]["size_bytes"],
                "database_sha256": annual24["database"]["sha256"],
                "database_logical_sha256": annual24["database"]["logical_sha256"],
            },
        },
        "repository_files": identities,
        "consumption_policy": {
            "read_only": True,
            "verify_sha256_before_use": True,
            "verify_release_tag": RELEASE_TAG,
            "do_not_rebuild_group8_semantics": True,
            "do_not_modify_group8_outputs": True,
            "preserve_causal_timestamps": True,
            "trading_outputs_not_present": True,
        },
        "purpose": "Authoritative Group 8 dependency handoff for all later MoeBot groups. Small artifacts live in GitHub repository; annual SQLite outputs live as immutable release assets referenced by exact SHA/size.",
    }
    next_group["manifest_hash"] = hashlib.sha256(canonical(next_group)).hexdigest()
    a.next_group_output.write_text(json.dumps(next_group, indent=2, sort_keys=True) + "\n")

    closure = {
        "format_version": 1,
        "status": "OFFICIALLY_CLOSED",
        "group": 8,
        "name": status.get("name"),
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": expected["config_id"],
        "release_tag": RELEASE_TAG,
        "design_freeze_hash": expected["design_freeze_hash"],
        "engine_build_manifest_hash": expected["engine_build_manifest_hash"],
        "annual_2023_manifest_hash": annual23["manifest_hash"],
        "oos_freeze_manifest_hash": oos["manifest_hash"],
        "annual_2024_oos_manifest_hash": annual24["manifest_hash"],
        "cross_year_report_hash": cross["report_hash"],
        "final_audit_hash": audit["report_hash"],
        "next_group_dependency_manifest_hash": next_group["manifest_hash"],
        "annual_execution_authorized": False,
        "next_group_start_authorized": True,
        "large_assets_release_required": True,
    }
    closure["closure_manifest_hash"] = hashlib.sha256(canonical(closure)).hexdigest()
    a.closure_output.write_text(json.dumps(closure, indent=2, sort_keys=True) + "\n")

    handoff = f"""# MoeBot Group 8 — Official Handoff Requirements\n\nStatus: **OFFICIALLY CLOSED** after Design Freeze, lifecycle hardening, 2023 validation, immutable pre-2024 OOS freeze, frozen 2024 OOS validation, cross-year validation, and final independent audit.\n\n## Authoritative identities\n\n- Engine version: `{build['engine_version']}`\n- Schema version: `{build['schema_version']}`\n- Config ID: `{expected['config_id']}`\n- Engine SHA-256: `{expected['engine_sha256']}`\n- Design Freeze hash: `{expected['design_freeze_hash']}`\n- Engine Build manifest hash: `{expected['engine_build_manifest_hash']}`\n- 2023 annual manifest hash: `{annual23['manifest_hash']}`\n- 2024 OOS annual manifest hash: `{annual24['manifest_hash']}`\n- Cross-year report hash: `{cross['report_hash']}`\n- Final audit hash: `{audit['report_hash']}`\n- Next-group manifest hash: `{next_group['manifest_hash']}`\n\n## Large annual databases\n\nThe authoritative Group 8 annual SQLite outputs are **not stored as Git blobs**. They must be published under GitHub Release tag `{RELEASE_TAG}` and consumed only after SHA-256/size verification using `NEXT_GROUP_DEPENDENCY_MANIFEST.json`.\n\n- 2023: `{annual23['compressed_asset']['filename']}`\n- 2024: `{annual24['compressed_asset']['filename']}`\n\n## Rules for later groups\n\n1. Treat all Group 8 repository artifacts and annual SQLite outputs as read-only.\n2. Verify every required repository file and release asset against `NEXT_GROUP_DEPENDENCY_MANIFEST.json` before use.\n3. Do not rebuild or reinterpret Group 8 definitions, thresholds, lifecycle semantics, or causal timestamps.\n4. Do not use Group 8 as a BUY/SELL, entry/exit, PnL, or profitability engine.\n5. Preserve the frozen logical dependency lineage `{status['logical_dependency_lineage_id']}`.\n6. A later group may start only from the official closure manifest and verified release assets.\n"""
    a.handoff_output.write_text(handoff)

    status["officially_closed"] = True
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["next_group_start_authorized"] = True
    status["closure"] = {
        "status": "OFFICIALLY_CLOSED",
        "closure_manifest_hash": closure["closure_manifest_hash"],
        "final_audit_hash": audit["report_hash"],
        "next_group_dependency_manifest_hash": next_group["manifest_hash"],
        "release_tag": RELEASE_TAG,
    }
    status["status"] = "OFFICIALLY_CLOSED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "OFFICIALLY_CLOSED", "closure_manifest_hash": closure["closure_manifest_hash"], "final_audit_hash": audit["report_hash"], "next_group_manifest_hash": next_group["manifest_hash"], "release_tag": RELEASE_TAG}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
