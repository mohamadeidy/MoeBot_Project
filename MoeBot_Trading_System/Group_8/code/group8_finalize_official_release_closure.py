#!/usr/bin/env python3
"""Finalize official Group 8 closure only after release assets are verified."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELEASE_TAG = "moebot-group8-v0.8.0"


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    p=argparse.ArgumentParser();p.add_argument("--group8-root",type=Path,required=True);p.add_argument("--publication",type=Path,required=True);p.add_argument("--closure-output",type=Path,required=True);p.add_argument("--handoff-output",type=Path,required=True);a=p.parse_args()
    root=a.group8_root.resolve();status_path=root/"STATUS.json";status=load(status_path);candidate=load(root/"CLOSURE_CANDIDATE_MANIFEST.json");nextg_path=root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json";nextg=load(nextg_path);audit=load(root/"reports/51_FINAL_INDEPENDENT_AUDIT.json");a23=load(root/"ANNUAL_2023_VALIDATION_MANIFEST.json");a24=load(root/"ANNUAL_2024_OOS_VALIDATION_MANIFEST.json");pub=load(a.publication);fail=[]
    if status.get("officially_closed") is not False or status.get("status")!="CLOSURE_CANDIDATE_RELEASE_REQUIRED":fail.append("wrong_official_closure_phase")
    if candidate.get("status")!="CLOSURE_CANDIDATE_RELEASE_REQUIRED" or candidate.get("officially_closed") is not False:fail.append("invalid_closure_candidate")
    if audit.get("status")!="PASS":fail.append("final_audit_not_pass")
    if nextg.get("status")!="FROZEN_HANDOFF_PENDING_RELEASE_VERIFICATION":fail.append("handoff_not_pending_release")
    if pub.get("status")!="PASS" or pub.get("release_tag")!=RELEASE_TAG:fail.append("release_publication_not_verified")
    expected={"2023":a23["compressed_asset"],"2024":a24["compressed_asset"]}
    for year,exp in expected.items():
        got=pub.get("assets",{}).get(year,{})
        if got.get("name")!=exp.get("filename"):fail.append(f"release_asset_name:{year}")
        if int(got.get("size_bytes",-1))!=int(exp.get("size_bytes",-2)):fail.append(f"release_asset_size:{year}")
        if got.get("sha256")!=exp.get("sha256"):fail.append(f"release_asset_sha:{year}")
        if got.get("download_verified") is not True:fail.append(f"release_redownload_not_verified:{year}")
    if pub.get("candidate_hash")!=candidate.get("candidate_hash"):fail.append("publication_candidate_hash_mismatch")
    if pub.get("pre_release_next_group_manifest_hash")!=nextg.get("manifest_hash"):fail.append("publication_handoff_hash_mismatch")
    if pub.get("final_audit_hash")!=audit.get("report_hash"):fail.append("publication_final_audit_hash_mismatch")
    if fail:raise SystemExit(";".join(sorted(set(fail))))

    nextg["status"]="FROZEN_HANDOFF";nextg["release_publication_verified"]=True;nextg["release_publication_report_hash"]=pub["report_hash"];nextg["release_url"]=pub.get("release_url");nextg.pop("manifest_hash",None);nextg["manifest_hash"]=hashlib.sha256(canonical(nextg)).hexdigest();nextg_path.write_text(json.dumps(nextg,indent=2,sort_keys=True)+"\n")
    closure={"format_version":1,"status":"OFFICIALLY_CLOSED","group":8,"name":status.get("name"),"engine_version":a23["engine_version"],"schema_version":a23["schema_version"],"config_id":a23["config_id"],"release_tag":RELEASE_TAG,"release_url":pub.get("release_url"),"release_publication_report_hash":pub["report_hash"],"closure_candidate_hash":candidate["candidate_hash"],"final_audit_hash":audit["report_hash"],"annual_2023_manifest_hash":a23["manifest_hash"],"annual_2024_oos_manifest_hash":a24["manifest_hash"],"next_group_dependency_manifest_hash":nextg["manifest_hash"],"annual_execution_authorized":False,"next_group_start_authorized":True,"large_assets_release_verified":True};closure["closure_manifest_hash"]=hashlib.sha256(canonical(closure)).hexdigest();a.closure_output.write_text(json.dumps(closure,indent=2,sort_keys=True)+"\n")
    a.handoff_output.write_text(f"# MoeBot Group 8 — Official Handoff Requirements\n\nStatus: **OFFICIALLY CLOSED**.\n\nRelease tag: `{RELEASE_TAG}`\n\nRelease publication hash: `{pub['report_hash']}`\n\nNext-group dependency manifest hash: `{nextg['manifest_hash']}`\n\nAll later groups must verify and consume `NEXT_GROUP_DEPENDENCY_MANIFEST.json` read-only. The 2023 and 2024 annual SQLite outputs are the exact verified assets under the release tag above; do not rebuild or substitute them.\n")
    status["officially_closed"]=True;status["annual_execution_authorized"]=False;status["annual_execution_2023_authorized"]=False;status["annual_execution_2024_authorized"]=False;status["next_group_start_authorized"]=True;status["closure"]={"status":"OFFICIALLY_CLOSED","closure_manifest_hash":closure["closure_manifest_hash"],"release_publication_report_hash":pub["report_hash"],"next_group_dependency_manifest_hash":nextg["manifest_hash"],"release_tag":RELEASE_TAG};status["status"]="OFFICIALLY_CLOSED";status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":"OFFICIALLY_CLOSED","closure_manifest_hash":closure["closure_manifest_hash"],"next_group_manifest_hash":nextg["manifest_hash"],"release_tag":RELEASE_TAG},indent=2,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
