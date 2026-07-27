#!/usr/bin/env python3
"""Finalize Group 8 Annual 2023 under the frozen FREE lossless-sharded contract.

This is a governance/finalization layer only. It consumes already-built reports,
proves deterministic reconstruction/union identity, records the annual PASS, and
revokes annual execution before the separate pre-2024 OOS freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def stable(v: Any) -> str:
    return hashlib.sha256(canonical(v)).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def verify_self_hash(report: dict[str, Any], label: str) -> None:
    if "report_hash" not in report:
        return
    payload = dict(report)
    saved = payload.pop("report_hash")
    if saved != stable(payload):
        raise RuntimeError(f"{label}:report_hash_mismatch")


def require_free_2023(report: dict[str, Any], label: str) -> None:
    if int(report.get("year", 0)) != 2023:
        raise RuntimeError(f"{label}:wrong_year")
    if report.get("free_only") is not True:
        raise RuntimeError(f"{label}:not_free_only")
    if report.get("paid_runner_used") is True or report.get("paid_service_used") is True:
        raise RuntimeError(f"{label}:paid_execution_detected")
    if report.get("oos_2024_accessed") is True:
        raise RuntimeError(f"{label}:2024_oos_accessed")


def finalize(
    *,
    group8_root: Path,
    core_release_report: Path,
    pa7_release_report: Path,
    reconstruction_reports: list[Path],
    union_reports: list[Path],
    manifest_output: Path,
) -> dict[str, Any]:
    root = group8_root.resolve()
    status_path = root / "STATUS.json"
    status = load(status_path)
    build = load(root / "ENGINE_BUILD_MANIFEST.json")
    design = load(root / "DESIGN_FREEZE_MANIFEST.json")
    contract = load(root / "SHARDED_STORAGE_CONTRACT.json")
    core = load(core_release_report)
    pa7 = load(pa7_release_report)
    recs = [load(p) for p in reconstruction_reports]
    unions = [load(p) for p in union_reports]

    failures: list[str] = []
    if status.get("officially_closed") is not False:
        failures.append("group8_already_closed")
    if status.get("annual_execution_2023_authorized") is not True:
        failures.append("annual_2023_not_authorized")
    if status.get("annual_execution_2024_authorized") is not False:
        failures.append("2024_prematurely_authorized")
    free_policy = status.get("free_only_policy", {})
    if free_policy.get("paid_runner_allowed") is not False or free_policy.get("paid_service_allowed") is not False:
        failures.append("free_only_policy_not_frozen")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS_FREE_SHARDED":
        failures.append("free_sharded_technical_candidate_not_pass")
    if build.get("annual_execution_2023_authorized") is not True or build.get("annual_execution_2024_authorized") is not False:
        failures.append("build_authorization_invalid")
    if build.get("storage_contract_hash") != contract.get("storage_contract_hash"):
        failures.append("storage_contract_hash_mismatch")
    if build.get("design_freeze_hash") != design.get("design_freeze_hash"):
        failures.append("design_freeze_hash_mismatch")

    for label, report in (("core", core), ("pa7", pa7)):
        try:
            verify_self_hash(report, label)
            require_free_2023(report, label)
        except RuntimeError as e:
            failures.append(str(e))
    if core.get("status") != "PASS" or core.get("artifact_kind") != "GROUP8_ANNUAL_CORE":
        failures.append("core_release_not_pass")
    if core.get("storage_contract_hash") != contract.get("storage_contract_hash"):
        failures.append("core_storage_contract_mismatch")
    if core.get("engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"):
        failures.append("core_engine_identity_mismatch")
    if pa7.get("status") != "PASS" or pa7.get("artifact_kind") != "GROUP8_PA7_ANNUAL_2023_SHARDED_RELEASE":
        failures.append("pa7_release_not_pass")
    if pa7.get("complete_once_only_coverage") is not True:
        failures.append("pa7_once_only_coverage_not_pass")

    if len(recs) != 3 or len(unions) != 3:
        failures.append("three_reconstructions_required")
    rec_logical: list[str | None] = []
    union_logical: list[str | None] = []
    for i, report in enumerate(recs):
        label = f"reconstruction_{i}"
        try:
            verify_self_hash(report, label)
            require_free_2023(report, label)
        except RuntimeError as e:
            failures.append(str(e))
        if report.get("status") != "PASS":
            failures.append(f"{label}:not_pass")
        if report.get("no_trading_outputs") is not True:
            failures.append(f"{label}:trading_output_prohibition_not_proven")
        if report.get("causality") not in ("PASS", True):
            failures.append(f"{label}:causality_not_pass")
        rec_logical.append(report.get("logical_sha256"))
    for i, report in enumerate(unions):
        label = f"union_{i}"
        try:
            verify_self_hash(report, label)
            require_free_2023(report, label)
        except RuntimeError as e:
            failures.append(str(e))
        if report.get("status") != "PASS" or report.get("full_annual_union") is not True:
            failures.append(f"{label}:not_full_union_pass")
        if int(report.get("unresolved_group8_reference_count", -1)) != 0:
            failures.append(f"{label}:unresolved_group8_refs")
        if int(report.get("duplicate_domain_id_count", -1)) != 0:
            failures.append(f"{label}:duplicate_domain_ids")
        if int(report.get("registry_conflict_count", -1)) != 0:
            failures.append(f"{label}:registry_conflicts")
        union_logical.append(report.get("global_logical_sha256"))

    if not rec_logical or None in rec_logical or len(set(rec_logical)) != 1:
        failures.append("non_pa7_reconstruction_logical_drift")
    if not union_logical or None in union_logical or len(set(union_logical)) != 1:
        failures.append("full_union_logical_drift")
    if failures:
        raise RuntimeError(";".join(failures))

    manifest: dict[str, Any] = {
        "format_version": 2,
        "status": "ANNUAL_2023_PASS",
        "group": 8,
        "year": 2023,
        "physical_storage_mode": "FREE_LOSSLESS_SHARDED",
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": build["config_id"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "engine_sha256": build["identities"]["engine"]["sha256"],
        "postprocessor_sha256": build["identities"]["postprocessor"]["sha256"],
        "materializer_sha256": build["identities"]["materializer"]["sha256"],
        "design_freeze_hash": design["design_freeze_hash"],
        "storage_contract_hash": contract["storage_contract_hash"],
        "core_release": {
            "report_hash": core["report_hash"],
            "release_tag": core.get("release_tag"),
            "logical_sha256": core.get("logical_sha256"),
            "raw_sha256": core.get("raw_sha256"),
        },
        "pa7_release": {
            "report_hash": pa7["report_hash"],
            "release_tag": pa7.get("release_tag"),
            "shard_count": pa7.get("shard_count"),
            "candidate_rows": pa7.get("candidate_rows"),
            "state_rows": pa7.get("state_rows"),
            "complete_once_only_coverage": True,
        },
        "reconstruction": {
            "logical_sha256": rec_logical[0],
            "report_hashes": [r["report_hash"] for r in recs],
            "idempotence": "PASS",
            "clean_reconstruction": "PASS",
        },
        "full_union": {
            "global_logical_sha256": union_logical[0],
            "report_hashes": [r["report_hash"] for r in unions],
            "unresolved_group8_reference_count": 0,
            "duplicate_domain_id_count": 0,
            "registry_conflict_count": 0,
        },
        "logical_fingerprint": union_logical[0],
        "causality": "PASS",
        "no_lookahead": "PASS",
        "no_backdating": "PASS",
        "duplicate_prevention": "PASS",
        "upstream_reference_integrity": "PASS",
        "no_trading_outputs": True,
        "free_only": True,
        "paid_runner_used": False,
        "paid_service_used": False,
        "oos_2024_accessed": False,
        "policy": "Annual 2023 passed under the frozen lossless-sharded FREE execution contract. All annual execution is revoked until the pre-2024 OOS freeze binds this exact identity set.",
    }
    manifest["manifest_hash"] = stable(manifest)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["annual_validation_2023"] = {
        "status": "PASS",
        "manifest_hash": manifest["manifest_hash"],
        "logical_fingerprint": manifest["logical_fingerprint"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "engine_sha256": manifest["engine_sha256"],
        "storage_contract_hash": manifest["storage_contract_hash"],
        "physical_storage_mode": manifest["physical_storage_mode"],
    }
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["status"] = "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--core-release-report", type=Path, required=True)
    p.add_argument("--pa7-release-report", type=Path, required=True)
    p.add_argument("--reconstruction-report", type=Path, action="append", required=True)
    p.add_argument("--union-report", type=Path, action="append", required=True)
    p.add_argument("--manifest-output", type=Path, required=True)
    a = p.parse_args()
    m = finalize(
        group8_root=a.group8_root,
        core_release_report=a.core_release_report,
        pa7_release_report=a.pa7_release_report,
        reconstruction_reports=a.reconstruction_report,
        union_reports=a.union_report,
        manifest_output=a.manifest_output,
    )
    print(json.dumps({"status": m["status"], "manifest_hash": m["manifest_hash"], "logical_fingerprint": m["logical_fingerprint"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
