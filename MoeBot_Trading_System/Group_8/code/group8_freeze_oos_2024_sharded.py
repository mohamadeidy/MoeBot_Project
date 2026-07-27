#!/usr/bin/env python3
"""Freeze the exact FREE lossless-sharded Group 8 identity set before 2024 OOS.

This stage is intentionally data-blind with respect to 2024. It runs only after
Annual 2023 PASS, binds the physical execution/tooling identities and the bucket
plan selected from 2023 engineering evidence, then authorizes one frozen 2024 OOS
execution path. No 2024 database is read here.
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


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identity(root: Path, rel: str) -> dict[str, Any]:
    p = root / rel
    if not p.is_file():
        raise RuntimeError(f"missing_oos_identity:{rel}")
    return {"path": rel, "size_bytes": p.stat().st_size, "sha256": shaf(p)}


FROZEN_TOOLING = [
    "00_DESIGN_LOCK.md",
    "01_DEFINITION_REGISTRY.json",
    "02_SCHEMA.sql",
    "FROZEN_CONFIG.json",
    "DESIGN_FREEZE_MANIFEST.json",
    "ENGINE_BUILD_MANIFEST.json",
    "SHARDED_STORAGE_CONTRACT.json",
    "ANNUAL_2023_VALIDATION_MANIFEST.json",
    "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
    "UPSTREAM_ADAPTER_MAP.json",
    "UPSTREAM_VALUE_BINDINGS.json",
    "UPSTREAM_REFERENCE_RESOLUTION.json",
    "code/moebot_group8_engine_v0_8_0.py",
    "code/group8_postprocess_v0_8_0.py",
    "code/group8_materialize_inputs.py",
    "code/group8_pa7_materialize_inputs.py",
    "code/group8_annual_core_driver.py",
    "code/group8_context_rejection_fastpath.py",
    "code/group8_structural_narrative_fastpath.py",
    "code/group8_pa7_shard_executor.py",
    "code/group8_pa7_scoped_shard_executor.py",
    "code/group8_pa7_annual_shard_executor.py",
    "code/group8_pa7_root_window_inventory.py",
    "code/group8_pa7_catalog.py",
    "code/group8_pa7_derived_executor.py",
    "code/group8_global_finalizer.py",
    "code/group8_shard_union_validator.py",
    "code/group8_sqlite_fingerprint.py",
    "code/group8_finalize_annual_2023_sharded.py",
    "reports/51_PA7_2023_REAL_SIZING_AND_BUCKET_PLAN.json",
]

# Optional physical fast paths become mandatory identities when present at freeze.
OPTIONAL_FROZEN_TOOLING = [
    "code/group8_bounded_range_fastpath.py",
]


def freeze(*, group8_root: Path, output: Path) -> dict[str, Any]:
    root = group8_root.resolve()
    status_path = root / "STATUS.json"
    status = json.loads(status_path.read_text())
    annual = json.loads((root / "ANNUAL_2023_VALIDATION_MANIFEST.json").read_text())
    build = json.loads((root / "ENGINE_BUILD_MANIFEST.json").read_text())
    design = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    contract = json.loads((root / "SHARDED_STORAGE_CONTRACT.json").read_text())
    plan = json.loads((root / "reports/51_PA7_2023_REAL_SIZING_AND_BUCKET_PLAN.json").read_text())

    failures: list[str] = []
    if status.get("officially_closed") is not False:
        failures.append("group8_already_closed")
    if status.get("status") != "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED":
        failures.append("wrong_phase")
    if status.get("annual_execution_authorized") is not False:
        failures.append("annual_execution_not_revoked")
    if status.get("annual_execution_2023_authorized") is not False:
        failures.append("2023_execution_not_revoked")
    if status.get("annual_execution_2024_authorized") is not False:
        failures.append("2024_already_authorized")
    policy = status.get("free_only_policy", {})
    if policy.get("paid_runner_allowed") is not False or policy.get("paid_service_allowed") is not False:
        failures.append("free_only_policy_not_frozen")
    if annual.get("status") != "ANNUAL_2023_PASS" or int(annual.get("format_version", 0)) < 2:
        failures.append("annual_2023_sharded_manifest_not_pass")
    if annual.get("physical_storage_mode") != "FREE_LOSSLESS_SHARDED":
        failures.append("annual_2023_not_lossless_sharded")
    if annual.get("free_only") is not True or annual.get("paid_runner_used") is not False or annual.get("paid_service_used") is not False:
        failures.append("annual_2023_not_free_only")
    if annual.get("oos_2024_accessed") is not False:
        failures.append("annual_2023_reports_2024_access")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS_FREE_SHARDED" or int(build.get("format_version", 0)) < 6:
        failures.append("free_sharded_technical_candidate_not_pass")
    if annual.get("engine_build_manifest_hash") != build.get("manifest_hash"):
        failures.append("annual_build_manifest_mismatch")
    if annual.get("engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"):
        failures.append("annual_engine_identity_mismatch")
    if annual.get("design_freeze_hash") != design.get("design_freeze_hash"):
        failures.append("annual_design_freeze_mismatch")
    if annual.get("storage_contract_hash") != contract.get("storage_contract_hash") or build.get("storage_contract_hash") != contract.get("storage_contract_hash"):
        failures.append("storage_contract_identity_mismatch")
    if annual.get("no_trading_outputs") is not True or annual.get("causality") != "PASS" or annual.get("no_lookahead") != "PASS" or annual.get("no_backdating") != "PASS":
        failures.append("annual_2023_governance_not_pass")
    if annual.get("reconstruction", {}).get("idempotence") != "PASS" or annual.get("reconstruction", {}).get("clean_reconstruction") != "PASS":
        failures.append("annual_2023_determinism_not_pass")
    if annual.get("full_union", {}).get("unresolved_group8_reference_count") != 0 or annual.get("full_union", {}).get("duplicate_domain_id_count") != 0 or annual.get("full_union", {}).get("registry_conflict_count") != 0:
        failures.append("annual_2023_union_integrity_not_pass")
    if plan.get("status") != "PASS" or plan.get("free_only") is not True or plan.get("oos_2024_accessed") is not False:
        failures.append("2023_bucket_plan_not_frozen_free")
    if not isinstance(plan.get("frozen_bucket_plan"), dict) or not plan.get("frozen_bucket_plan"):
        failures.append("bucket_plan_missing")
    if failures:
        raise RuntimeError(";".join(failures))

    paths = list(FROZEN_TOOLING)
    for rel in OPTIONAL_FROZEN_TOOLING:
        if (root / rel).is_file():
            paths.append(rel)
    identities = {rel: identity(root, rel) for rel in paths}

    manifest: dict[str, Any] = {
        "format_version": 3,
        "status": "FROZEN_FOR_2024_OOS_FREE_SHARDED",
        "group": 8,
        "oos_year": 2024,
        "training_validation_year": 2023,
        "physical_storage_mode": "FREE_LOSSLESS_SHARDED",
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
        "storage_contract_hash": contract["storage_contract_hash"],
        "closed_blocking_gap": build.get("closed_blocking_gap"),
        "logical_dependency_lineage_id": status["logical_dependency_lineage_id"],
        "annual_dependency_registry_hash": status["annual_dependency_registry_hash"],
        "pa7_partition_policy": {
            "bucket_plan_source_year": 2023,
            "bucket_plan_report_hash": plan["report_hash"],
            "bucket_counts": plan["frozen_bucket_plan"],
            "root_window_rule": "enumerate every observed causal-root YYYY-MM using the frozen inventory algorithm; do not alter bucket counts from 2024 observations",
            "oos_conditioned_bucket_changes_forbidden": True,
        },
        "identities": identities,
        "immutability_policy": {
            "engine_changes_before_or_during_2024_forbidden": True,
            "postprocessor_changes_before_or_during_2024_forbidden": True,
            "config_changes_before_or_during_2024_forbidden": True,
            "definition_changes_before_or_during_2024_forbidden": True,
            "schema_changes_before_or_during_2024_forbidden": True,
            "threshold_changes_before_or_during_2024_forbidden": True,
            "upstream_lineage_changes_before_or_during_2024_forbidden": True,
            "storage_contract_changes_before_or_during_2024_forbidden": True,
            "bucket_count_changes_from_2024_observations_forbidden": True,
            "2023_result_conditioned_semantic_changes_forbidden": True,
        },
        "authorization": {"2023": False, "2024_oos": True},
        "free_only": True,
        "paid_runner_allowed": False,
        "paid_service_allowed": False,
        "oos_2024_accessed_during_freeze": False,
        "policy": "2024 is frozen OOS. The exact FREE lossless-sharded engine/config/storage/tooling identities and 2023-derived bucket counts are immutable before and during OOS execution.",
    }
    manifest["manifest_hash"] = stable(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["oos_freeze_2024"] = {
        "status": manifest["status"],
        "manifest_hash": manifest["manifest_hash"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "annual_2023_manifest_hash": annual["manifest_hash"],
        "engine_sha256": manifest["engine_sha256"],
        "storage_contract_hash": manifest["storage_contract_hash"],
        "bucket_plan_report_hash": plan["report_hash"],
        "config_id": build["config_id"],
    }
    status["annual_execution_authorized"] = True
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = True
    status["status"] = "OOS_2024_FROZEN_AND_AUTHORIZED_FREE_SHARDED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    m = freeze(group8_root=a.group8_root, output=a.output)
    print(json.dumps({"status": m["status"], "manifest_hash": m["manifest_hash"], "2024_oos_authorized": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
