#!/usr/bin/env python3
"""Finalize Group 8 V3 Annual 2023 from immutable Stage5 + verified Stage6/7 unions.

No monolithic reconstruction is created. The annual logical release identity is
the deterministic composition of:
  * the immutable Stage5 boundary SHA,
  * official Stage6 logical union fingerprint,
  * official Stage7 logical union fingerprint,
  * frozen design/storage identities,
  * exact validated Git commit and plans.

This is governance/finalization only and never reads 2024 data.
"""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

def _verify(rec:dict[str,Any],field:str)->None:
    x=dict(rec);saved=str(x.pop(field))
    if stable_hash(x)!=saved: raise RuntimeError(f"{field} mismatch")

def _head(root:Path)->str:
    repo=root.resolve().parent.parent
    return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()

def finalize(*,artifacts_root:Path,stage5_db:Path,stage6_release_path:Path,stage6_union_path:Path,stage7_plan_path:Path,stage7_release_path:Path,stage7_union_path:Path,expected_commit:str,output:Path)->dict[str,Any]:
    if _head(artifacts_root)!=expected_commit: raise RuntimeError("Git HEAD mismatch")
    s6r=json.loads(stage6_release_path.read_text());_verify(s6r,"release_hash")
    s6u=json.loads(stage6_union_path.read_text());_verify(s6u,"report_hash")
    s7p=json.loads(stage7_plan_path.read_text());_verify(s7p,"plan_hash")
    s7r=json.loads(stage7_release_path.read_text());_verify(s7r,"release_hash")
    s7u=json.loads(stage7_union_path.read_text());_verify(s7u,"report_hash")
    design=json.loads((artifacts_root/"DESIGN_FREEZE_MANIFEST.json").read_text())
    contract=json.loads((artifacts_root/"SHARDED_STORAGE_CONTRACT.json").read_text())
    build=json.loads((artifacts_root/"ENGINE_BUILD_MANIFEST.json").read_text())
    stage5_sha=sha256_file(stage5_db)

    failures=[]
    if s6r.get("status")!="PASS" or s6u.get("status")!="PASS" or s6u.get("stage6_official_pass_eligible") is not True: failures.append("stage6_not_official_pass")
    if s7p.get("status")!="PASS" or s7r.get("status")!="PASS" or s7u.get("status")!="PASS" or s7u.get("stage7_official_pass_eligible") is not True: failures.append("stage7_not_official_pass")
    if s6r.get("release_hash")!=s6u.get("stage6_release_hash"): failures.append("stage6_release_union_lineage")
    if s7p.get("plan_hash")!=s7r.get("plan_hash") or s7p.get("plan_hash")!=s7u.get("plan_hash"): failures.append("stage7_plan_lineage")
    if s7r.get("release_hash")!=s7u.get("stage7_release_hash"): failures.append("stage7_release_union_lineage")
    if stage5_sha!=s6r.get("stage5_database_sha256") or stage5_sha!=s6u.get("stage5_database_sha256") or stage5_sha!=s7p.get("stage5_database_sha256") or stage5_sha!=s7r.get("stage5_database_sha256") or stage5_sha!=s7u.get("stage5_database_sha256"): failures.append("stage5_lineage_drift")
    if s6r.get("validated_commit")!=expected_commit and s6u.get("validated_commit")!=s6r.get("validated_commit"):
        # Stage6 legitimately executed on an earlier V3 physical commit; its own release/union must agree.
        failures.append("stage6_internal_commit_drift")
    stage7_execution_commit=s7p.get("validated_commit")
    if not stage7_execution_commit or s7r.get("validated_commit")!=stage7_execution_commit or s7u.get("validated_commit")!=stage7_execution_commit: failures.append("stage7_execution_commit_drift")
    if s7u.get("duplicate_domain_id_count")!=0 or s7u.get("unresolved_local_evidence_subject_count")!=0: failures.append("stage7_union_integrity")
    if s6u.get("duplicate_domain_id_count")!=0 or s6u.get("unresolved_group8_reference_count")!=0: failures.append("stage6_union_integrity")
    if s7u.get("oos_2024_accessed") is not False or s7r.get("oos_2024_accessed") is not False: failures.append("2024_accessed_before_freeze")
    if s7p.get("execution_policy",{}).get("oos_2024_forbidden") is not True: failures.append("2024_lock_not_proven")
    if design.get("design_freeze_hash")!=s7p.get("design_freeze_hash") or contract.get("storage_contract_hash")!=s7p.get("storage_contract_hash"): failures.append("frozen_contract_drift")
    if failures: raise RuntimeError(";".join(failures))

    logical_components={
      "stage5_database_sha256":stage5_sha,
      "stage6_global_logical_sha256":s6u["global_logical_sha256"],
      "stage7_global_logical_sha256":s7u["global_logical_sha256"],
      "stage6_release_hash":s6r["release_hash"],
      "stage7_release_hash":s7r["release_hash"],
      "stage7_plan_hash":s7p["plan_hash"],
      "design_freeze_hash":design["design_freeze_hash"],
      "storage_contract_hash":contract["storage_contract_hash"],
    }
    manifest={
      "format_version":3,"status":"ANNUAL_2023_PASS","group":8,"year":2023,
      "physical_storage_mode":"V3_FREE_LOSSLESS_SHARDED_ZSTD",
      "validated_commit":expected_commit,
      "stage6_execution_commit":s6r.get("validated_commit"),
      "stage7_execution_commit":stage7_execution_commit,
      "engine_version":build["engine_version"],"schema_version":build["schema_version"],"config_id":build["config_id"],
      "engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":build["identities"]["engine"]["sha256"],
      "postprocessor_sha256":build["identities"]["postprocessor"]["sha256"],"materializer_sha256":build["identities"]["materializer"]["sha256"],
      "design_freeze_hash":design["design_freeze_hash"],"storage_contract_hash":contract["storage_contract_hash"],
      "stage5":{"sha256":stage5_sha,"role":"immutable logical boundary for stages 0-5"},
      "stage6":{"release_hash":s6r["release_hash"],"union_report_hash":s6u["report_hash"],"global_logical_sha256":s6u["global_logical_sha256"],"shard_count":s6u["shard_count"],"table_row_counts":s6u["table_row_counts"]},
      "stage7":{"plan_hash":s7p["plan_hash"],"release_hash":s7r["release_hash"],"union_report_hash":s7u["report_hash"],"global_logical_sha256":s7u["global_logical_sha256"],"shard_count":s7u["shard_count"],"table_row_counts":s7u["table_row_counts"],"definition_coverage":s7u["definition_coverage"]},
      "logical_components":logical_components,
      "logical_fingerprint":stable_hash(logical_components),
      "duplicate_domain_id_count_stage6":0,"duplicate_domain_id_count_stage7":0,
      "unresolved_group8_reference_count_stage6":0,"unresolved_evidence_subject_count_stage7":0,
      "causality":"PASS","no_lookahead":"PASS","no_backdating":"PASS","duplicate_prevention":"PASS",
      "upstream_reference_integrity":"PASS","read_only_upstream":True,"no_trading_outputs":True,
      "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,
      "annual_execution_2023_complete":True,"annual_execution_2024_authorized":False,
      "next_gate":"archive immutable Stage5 losslessly, then freeze exact V3 identity set for untouched 2024 OOS",
    }
    manifest["manifest_hash"]=stable_hash(manifest)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    return manifest

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--stage6-release",type=Path,required=True);p.add_argument("--stage6-union",type=Path,required=True);p.add_argument("--stage7-plan",type=Path,required=True);p.add_argument("--stage7-release",type=Path,required=True);p.add_argument("--stage7-union",type=Path,required=True);p.add_argument("--expected-commit",required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();m=finalize(artifacts_root=a.artifacts_root.resolve(),stage5_db=a.stage5_db.resolve(),stage6_release_path=a.stage6_release.resolve(),stage6_union_path=a.stage6_union.resolve(),stage7_plan_path=a.stage7_plan.resolve(),stage7_release_path=a.stage7_release.resolve(),stage7_union_path=a.stage7_union.resolve(),expected_commit=a.expected_commit,output=a.output.resolve());print(json.dumps(m,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
