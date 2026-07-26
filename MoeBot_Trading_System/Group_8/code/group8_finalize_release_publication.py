#!/usr/bin/env python3
"""Finalize verified GitHub Release publication evidence for MoeBot Group 8.

This tool does not upload assets. The workflow must first download the exact
2023/2024 Actions artifacts, verify their expected SHA/size, publish or locate
the immutable Group 8 release, re-download both release assets, and verify them
again. This finalizer converts that evidence into a deterministic manifest that
is required before official closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELEASE_TAG = "moebot-group8-v0.8.0"
LOCKED_CONTEXT_GAP_ID = "G8-ICT-LOCKED-CONTEXT-005"


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


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--group8-root",type=Path,required=True)
    p.add_argument("--release-url",required=True)
    p.add_argument("--release-target-sha",required=True)
    p.add_argument("--asset-2023",type=Path,required=True)
    p.add_argument("--asset-2024",type=Path,required=True)
    p.add_argument("--redownload-2023",type=Path,required=True)
    p.add_argument("--redownload-2024",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    root=a.group8_root.resolve();status=load(root/"STATUS.json");candidate=load(root/"CLOSURE_CANDIDATE_MANIFEST.json");nextg=load(root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json");audit=load(root/"reports/51_FINAL_INDEPENDENT_AUDIT.json");build=load(root/"ENGINE_BUILD_MANIFEST.json")
    failures=[]
    if status.get("officially_closed") is not False or status.get("status")!="CLOSURE_CANDIDATE_RELEASE_REQUIRED":failures.append("wrong_release_publication_phase")
    if candidate.get("status")!="CLOSURE_CANDIDATE_RELEASE_REQUIRED" or candidate.get("officially_closed") is not False:failures.append("invalid_closure_candidate")
    if nextg.get("status")!="FROZEN_HANDOFF_PENDING_RELEASE_VERIFICATION":failures.append("handoff_not_pending_release")
    if audit.get("status")!="PASS":failures.append("final_audit_not_pass")
    if candidate.get("release_tag")!=RELEASE_TAG or nextg.get("required_release_tag")!=RELEASE_TAG:failures.append("release_tag_contract_mismatch")
    engine_sha=build.get("identities",{}).get("engine",{}).get("sha256");validator_sha=build.get("identities",{}).get("annual_validator",{}).get("sha256")
    for label,obj in (("candidate",candidate),("next_group",nextg),("audit",audit)):
        if obj.get("engine_sha256")!=engine_sha:failures.append(f"{label}_engine_identity_drift")
        if obj.get("annual_validator_sha256")!=validator_sha:failures.append(f"{label}_annual_validator_identity_drift")
    if candidate.get("closed_blocking_gap_id")!=LOCKED_CONTEXT_GAP_ID or nextg.get("closed_blocking_gap_id")!=LOCKED_CONTEXT_GAP_ID or audit.get("closed_blocking_gap_id")!=LOCKED_CONTEXT_GAP_ID:failures.append("locked_context_gap_identity_drift")
    if candidate.get("next_group_dependency_manifest_hash")!=nextg.get("manifest_hash"):failures.append("candidate_handoff_hash_mismatch")
    if candidate.get("final_audit_hash")!=audit.get("report_hash"):failures.append("candidate_audit_hash_mismatch")

    supplied={"2023":(a.asset_2023,a.redownload_2023),"2024":(a.asset_2024,a.redownload_2024)};assets={}
    for year,(source,redownload) in supplied.items():
        expected=nextg.get("annual_database_assets",{}).get(year,{})
        name=expected.get("release_asset_name");size=int(expected.get("compressed_size_bytes",-1));sha=expected.get("compressed_sha256")
        if not name or size<0 or not sha:failures.append(f"expected_asset_identity_missing:{year}");continue
        if source.name!=name:failures.append(f"source_asset_name:{year}")
        if redownload.name!=name:failures.append(f"redownload_asset_name:{year}")
        if not source.is_file() or source.stat().st_size!=size or shaf(source)!=sha:failures.append(f"source_asset_identity:{year}")
        if not redownload.is_file() or redownload.stat().st_size!=size or shaf(redownload)!=sha:failures.append(f"redownload_asset_identity:{year}")
        assets[year]={"name":name,"size_bytes":size,"sha256":sha,"source_workflow_run_id":str(expected.get("source_workflow_run_id")),"source_artifact_name":expected.get("source_artifact_name"),"source_verified":True,"download_verified":True}
    if failures:raise SystemExit(";".join(sorted(set(failures))))

    manifest={
        "format_version":2,"status":"PASS","group":8,"phase":"RELEASE_PUBLICATION_VERIFICATION",
        "release_tag":RELEASE_TAG,"release_url":a.release_url,"release_target_sha":a.release_target_sha,
        "candidate_hash":candidate["candidate_hash"],"pre_release_next_group_manifest_hash":nextg["manifest_hash"],"final_audit_hash":audit["report_hash"],
        "engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":engine_sha,"annual_validator_sha256":validator_sha,"closed_blocking_gap_id":LOCKED_CONTEXT_GAP_ID,
        "assets":assets,"all_release_assets_redownload_verified":True,
        "policy":"Both Group 8 annual compressed SQLite outputs were verified before publication and independently re-downloaded from the immutable GitHub Release with identical SHA-256 and size. No asset substitution is permitted.",
    }
    manifest["report_hash"]=hashlib.sha256(canonical(manifest)).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":"PASS","report_hash":manifest["report_hash"],"release_tag":RELEASE_TAG,"release_url":a.release_url,"assets":assets},indent=2,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
