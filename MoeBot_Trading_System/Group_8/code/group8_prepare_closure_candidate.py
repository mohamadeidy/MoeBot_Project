#!/usr/bin/env python3
"""Prepare Group 8 closure candidate and immutable next-group handoff.

This stage is deliberately NOT official closure. It runs after 2023 PASS,
pre-2024 OOS freeze, 2024 OOS PASS, and cross-year PASS. It prepares final
audit/handoff identities while keeping `officially_closed=false` until the two
annual SQLite release assets are published and independently verified.
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


def ident(root: Path, rel: str) -> dict[str, Any]:
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"missing closure candidate file: {rel}")
    return {"path": rel, "size_bytes": p.stat().st_size, "sha256": shaf(p)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--cross-year", type=Path, required=True)
    p.add_argument("--final-audit-output", type=Path, required=True)
    p.add_argument("--next-group-output", type=Path, required=True)
    p.add_argument("--candidate-output", type=Path, required=True)
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
    if status.get("status") != "ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED": failures.append("wrong_candidate_phase")
    if any(status.get(k) for k in ("annual_execution_authorized","annual_execution_2023_authorized","annual_execution_2024_authorized")): failures.append("annual_execution_not_revoked")
    if design.get("status") != "FROZEN": failures.append("design_not_frozen")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS": failures.append("technical_candidate_not_pass")
    if annual23.get("status") != "ANNUAL_2023_PASS": failures.append("annual_2023_not_pass")
    if oos.get("status") != "FROZEN_FOR_2024_OOS": failures.append("oos_freeze_not_pass")
    if annual24.get("status") != "ANNUAL_2024_OOS_PASS": failures.append("annual_2024_oos_not_pass")
    if cross.get("status") != "PASS": failures.append("cross_year_not_pass")
    if cross.get("identity_stable_across_oos_boundary") is not True: failures.append("identity_not_stable")
    if cross.get("no_trading_outputs_both_years") is not True: failures.append("trading_output_prohibition_failure")
    if cross.get("read_only_upstream_both_years") is not True: failures.append("read_only_upstream_failure")

    engine_sha = build.get("identities", {}).get("engine", {}).get("sha256")
    if annual23.get("engine_build_manifest_hash") != build.get("manifest_hash") or annual24.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("annual_build_identity_drift")
    if annual23.get("engine_sha256") != engine_sha or annual24.get("engine_sha256") != engine_sha: failures.append("annual_engine_identity_drift")
    if annual23.get("config_id") != build.get("config_id") or annual24.get("config_id") != build.get("config_id"): failures.append("annual_config_identity_drift")
    if oos.get("annual_2023_manifest_hash") != annual23.get("manifest_hash"): failures.append("oos_2023_manifest_drift")
    if annual24.get("oos_freeze_manifest_hash") != oos.get("manifest_hash"): failures.append("2024_oos_freeze_drift")

    required = [
        "00_DESIGN_LOCK.md","01_DEFINITION_REGISTRY.json","02_SCHEMA.sql","FROZEN_CONFIG.json",
        "DESIGN_FREEZE_MANIFEST.json","ENGINE_BUILD_MANIFEST.json","ANNUAL_2023_VALIDATION_MANIFEST.json",
        "OOS_FREEZE_MANIFEST.json","ANNUAL_2024_OOS_VALIDATION_MANIFEST.json",
        "contracts/UPSTREAM_INPUT_CONTRACT.json","UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json","UPSTREAM_ADAPTER_MAP.json","UPSTREAM_VALUE_BINDINGS.json","UPSTREAM_REFERENCE_RESOLUTION.json",
        "code/moebot_group8_engine_v0_8_0.py","code/group8_materialize_inputs.py","code/group8_postprocess_v0_8_0.py",
        "tests/test_group8_engine_v0_8_0.py","tests/test_group8_lifecycle_persistence_v0_8_0.py",
        "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json",
        "reports/30_ANNUAL_2023_MATERIALIZATION.json","reports/31_ANNUAL_2023_ENGINE_AUDIT.json","reports/32_ANNUAL_2023_VALIDATION.json","reports/33_ANNUAL_2023_OUTPUT_FINGERPRINT.json","reports/34_ANNUAL_2023_CLEAN_RECONSTRUCTION.json",
        "reports/40_ANNUAL_2024_MATERIALIZATION.json","reports/41_ANNUAL_2024_ENGINE_AUDIT.json","reports/42_ANNUAL_2024_OOS_VALIDATION.json","reports/43_ANNUAL_2024_OUTPUT_FINGERPRINT.json","reports/44_ANNUAL_2024_CLEAN_RECONSTRUCTION.json","reports/50_CROSS_YEAR_VALIDATION.json",
    ]
    identities: dict[str, Any] = {}
    if not failures:
        for rel in required: identities[rel] = ident(root, rel)

    for year, annual in (("2023",annual23),("2024",annual24)):
        for kind in ("database","compressed_asset"):
            rec=annual.get(kind,{})
            if not rec.get("filename") or not rec.get("sha256") or not rec.get("size_bytes"): failures.append(f"{year}_{kind}_identity_missing")

    if failures: raise SystemExit(";".join(sorted(set(failures))))

    audit = {
        "format_version":1,"status":"PASS","group":8,"phase":"FINAL_INDEPENDENT_AUDIT_PRE_RELEASE",
        "design_freeze_hash":design["design_freeze_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":engine_sha,"config_id":build["config_id"],
        "annual_2023_manifest_hash":annual23["manifest_hash"],"oos_freeze_manifest_hash":oos["manifest_hash"],"annual_2024_oos_manifest_hash":annual24["manifest_hash"],"cross_year_report_hash":cross["report_hash"],
        "checks":{"design_frozen":True,"technical_candidate_pass":True,"2023_pass":True,"oos_freeze_pass":True,"2024_oos_pass":True,"cross_year_pass":True,"identity_stable":True,"no_trading_outputs":True,"read_only_upstream":True,"annual_execution_revoked":True},
        "release_publication_required_before_official_closure":True,
    }
    audit["report_hash"]=hashlib.sha256(canonical(audit)).hexdigest();a.final_audit_output.parent.mkdir(parents=True,exist_ok=True);a.final_audit_output.write_text(json.dumps(audit,indent=2,sort_keys=True)+"\n")
    identities[str(a.final_audit_output.relative_to(root))]=ident(root,str(a.final_audit_output.relative_to(root)))

    next_group={
        "format_version":1,"status":"FROZEN_HANDOFF_PENDING_RELEASE_VERIFICATION","source_group":8,"source_group_name":status.get("name"),
        "engine_version":build["engine_version"],"schema_version":build["schema_version"],"config_id":build["config_id"],"logical_dependency_lineage_id":status["logical_dependency_lineage_id"],
        "design_freeze_hash":design["design_freeze_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":engine_sha,
        "annual_2023_manifest_hash":annual23["manifest_hash"],"annual_2024_oos_manifest_hash":annual24["manifest_hash"],"cross_year_report_hash":cross["report_hash"],"final_audit_hash":audit["report_hash"],
        "required_release_tag":RELEASE_TAG,
        "annual_database_assets":{
            "2023":{"release_asset_name":annual23["compressed_asset"]["filename"],"compressed_size_bytes":annual23["compressed_asset"]["size_bytes"],"compressed_sha256":annual23["compressed_asset"]["sha256"],"database_filename":annual23["database"]["filename"],"database_size_bytes":annual23["database"]["size_bytes"],"database_sha256":annual23["database"]["sha256"],"database_logical_sha256":annual23["database"]["logical_sha256"],"source_workflow_run_id":annual23["validation_run_id"],"source_artifact_name":annual23["artifact_name"]},
            "2024":{"release_asset_name":annual24["compressed_asset"]["filename"],"compressed_size_bytes":annual24["compressed_asset"]["size_bytes"],"compressed_sha256":annual24["compressed_asset"]["sha256"],"database_filename":annual24["database"]["filename"],"database_size_bytes":annual24["database"]["size_bytes"],"database_sha256":annual24["database"]["sha256"],"database_logical_sha256":annual24["database"]["logical_sha256"],"source_workflow_run_id":annual24["validation_run_id"],"source_artifact_name":annual24["artifact_name"]},
        },
        "repository_files":identities,
        "consumption_policy":{"read_only":True,"verify_sha256_before_use":True,"verify_release_tag":RELEASE_TAG,"do_not_rebuild_group8_semantics":True,"do_not_modify_group8_outputs":True,"preserve_causal_timestamps":True,"trading_outputs_not_present":True},
    }
    next_group["manifest_hash"]=hashlib.sha256(canonical(next_group)).hexdigest();a.next_group_output.write_text(json.dumps(next_group,indent=2,sort_keys=True)+"\n")

    candidate={"format_version":1,"status":"CLOSURE_CANDIDATE_RELEASE_REQUIRED","group":8,"release_tag":RELEASE_TAG,"engine_build_manifest_hash":build["manifest_hash"],"annual_2023_manifest_hash":annual23["manifest_hash"],"annual_2024_oos_manifest_hash":annual24["manifest_hash"],"cross_year_report_hash":cross["report_hash"],"final_audit_hash":audit["report_hash"],"next_group_dependency_manifest_hash":next_group["manifest_hash"],"officially_closed":False,"release_publication_verified":False}
    candidate["candidate_hash"]=hashlib.sha256(canonical(candidate)).hexdigest();a.candidate_output.write_text(json.dumps(candidate,indent=2,sort_keys=True)+"\n")

    handoff=f"""# MoeBot Group 8 — Handoff Candidate\n\nGroup 8 has passed design, technical, 2023, frozen 2024 OOS, cross-year, and final pre-release audit gates. **It is not officially closed until the annual database assets are published and verified under GitHub Release `{RELEASE_TAG}`.**\n\nFuture groups must consume `NEXT_GROUP_DEPENDENCY_MANIFEST.json` read-only and verify every repository file/release asset before use.\n\nExpected release assets:\n- `{annual23['compressed_asset']['filename']}`\n- `{annual24['compressed_asset']['filename']}`\n""";a.handoff_output.write_text(handoff)

    status["officially_closed"]=False;status["next_group_start_authorized"]=False;status["closure_candidate"]={"status":candidate["status"],"candidate_hash":candidate["candidate_hash"],"final_audit_hash":audit["report_hash"],"next_group_dependency_manifest_hash":next_group["manifest_hash"],"required_release_tag":RELEASE_TAG};status["status"]="CLOSURE_CANDIDATE_RELEASE_REQUIRED";status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":candidate["status"],"candidate_hash":candidate["candidate_hash"],"release_tag":RELEASE_TAG,"officially_closed":False},indent=2,sort_keys=True));return 0


if __name__=="__main__": raise SystemExit(main())
