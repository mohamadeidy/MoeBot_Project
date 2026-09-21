#!/usr/bin/env python3
"""Freeze exact V3 Group8 identities before any 2024 OOS access.

The freeze is intentionally 2024-data-blind. It binds frozen semantic artifacts,
all V3 physical execution/validation tools, the Annual 2023 logical fingerprint,
and the 2023-derived Stage6/Stage7 bucket-count policy. Only after this manifest
exists may a separate OOS materializer read 2024 inputs.
"""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

TOOLS=[
"00_DESIGN_LOCK.md","01_DEFINITION_REGISTRY.json","02_SCHEMA.sql","FROZEN_CONFIG.json",
"DESIGN_FREEZE_MANIFEST.json","SHARDED_STORAGE_CONTRACT.json","UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
"UPSTREAM_ADAPTER_MAP.json","UPSTREAM_VALUE_BINDINGS.json","UPSTREAM_REFERENCE_RESOLUTION.json",
"code/moebot_group8_engine_v0_8_0.py","code/group8_postprocess_v0_8_0.py","code/group8_materialize_inputs.py",
"code/group8_segmented_annual_core.py","code/group8_v3_stage6_range_shard_executor.py","code/group8_v3_stage6_preflight.py",
"code/group8_v3_stage6_union_validator.py","code/group8_v3_stage7_shard_executor.py","code/group8_v3_stage7_plan.py",
"code/group8_v3_stage7_union_validator.py","code/group8_v3_finalize_annual_2023.py",
"code/group8_v3_archive_stage5.py","code/group8_v3_freeze_oos_2024.py",
"code/group8_v3_oos_2024_stage5.py","code/group8_v3_oos_2024_stage6.py","code/group8_v3_oos_2024_stage7.py",
"code/group8_v3_finalize_annual_2024_oos.py","code/group8_v3_cross_year_validate.py","code/group8_v3_close_group8.py","code/group8_v3_full_continuation.py",
]

def _verify(rec:dict[str,Any],field:str)->None:
 x=dict(rec);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{field} mismatch")

def _head(root:Path)->str:
 repo=root.resolve().parent.parent
 return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()

def _identity(root:Path,rel:str)->dict[str,Any]:
 p=root/rel
 if not p.is_file():raise RuntimeError(f"missing frozen identity:{rel}")
 return {"path":rel,"size_bytes":p.stat().st_size,"sha256":sha256_file(p)}

def _bucket_policy(plan:dict[str,Any])->dict[str,Any]:
 policy={}
 for s in plan["shards"]:
  key=f"{s['family']}:{s['timeframe']}:{str(s['root_month'])[5:]}"
  n=int(s["bucket_count"])
  if key in policy and policy[key]!=n:raise RuntimeError(f"inconsistent 2023 bucket count:{key}")
  policy[key]=n
 return dict(sorted(policy.items()))

def freeze(*,artifacts_root:Path,annual_manifest_path:Path,stage6_plan_path:Path,stage7_plan_path:Path,stage5_archive_report_path:Path,expected_commit:str,output:Path)->dict[str,Any]:
 if _head(artifacts_root)!=expected_commit:raise RuntimeError("Git HEAD mismatch for OOS freeze")
 annual=json.loads(annual_manifest_path.read_text());_verify(annual,"manifest_hash")
 s6=json.loads(stage6_plan_path.read_text());_verify(s6,"plan_hash")
 s7=json.loads(stage7_plan_path.read_text());_verify(s7,"plan_hash")
 arc=json.loads(stage5_archive_report_path.read_text());_verify(arc,"report_hash")
 if annual.get("status")!="ANNUAL_2023_PASS" or annual.get("oos_2024_accessed") is not False:raise RuntimeError("Annual 2023 not clean PASS")
 if arc.get("status")!="PASS" or arc.get("lossless_roundtrip_verified") is not True or arc.get("raw_sha256")!=annual["stage5"]["sha256"]:raise RuntimeError("Stage5 archive not lossless PASS")
 if s6.get("status")!="PASS" or int(s6.get("year",0))!=2023:raise RuntimeError("Stage6 2023 plan invalid")
 if s7.get("status")!="PASS" or int(s7.get("year",0))!=2023:raise RuntimeError("Stage7 2023 plan invalid")
 design=json.loads((artifacts_root/"DESIGN_FREEZE_MANIFEST.json").read_text());contract=json.loads((artifacts_root/"SHARDED_STORAGE_CONTRACT.json").read_text())
 identities={rel:_identity(artifacts_root,rel) for rel in TOOLS}
 manifest={
  "format_version":1,"status":"FROZEN_FOR_2024_OOS_V3","group":8,"oos_year":2024,"training_validation_year":2023,
  "validated_commit":expected_commit,"annual_2023_manifest_hash":annual["manifest_hash"],"annual_2023_logical_fingerprint":annual["logical_fingerprint"],
  "design_freeze_hash":design["design_freeze_hash"],"storage_contract_hash":contract["storage_contract_hash"],
  "stage5_2023_archive_report_hash":arc["report_hash"],"stage5_2023_archive_sha256":arc["archive_sha256"],
  "stage6_2023_plan_hash":s6["plan_hash"],"stage7_2023_plan_hash":s7["plan_hash"],
  "stage6_bucket_policy_by_timeframe_month":_bucket_policy({"shards":[{**x,"family":"range_chain"} for x in s6["specs"]]}),
  "stage7_bucket_policy_by_family_timeframe_month":_bucket_policy(s7),
  "identities":identities,
  "immutability_policy":{"semantic_artifact_changes_forbidden":True,"engine_changes_forbidden":True,"definition_changes_forbidden":True,"schema_changes_forbidden":True,"config_changes_forbidden":True,"threshold_changes_forbidden":True,"upstream_lineage_changes_forbidden":True,"storage_contract_changes_forbidden":True,"bucket_counts_from_2024_observations_forbidden":True,"2023_result_conditioned_semantic_changes_forbidden":True},
  "authorization":{"2023":False,"2024_oos":True},"free_only":True,"paid_runner_allowed":False,"paid_service_allowed":False,
  "oos_2024_accessed_during_freeze":False,
  "policy":"Untouched 2024 OOS may start only with these exact identities and the 2023-derived bucket-count policy; 2024 observations cannot alter semantics or partition counts.",
 }
 manifest["manifest_hash"]=stable_hash(manifest);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n");return manifest

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--annual-manifest",type=Path,required=True);p.add_argument("--stage6-plan",type=Path,required=True);p.add_argument("--stage7-plan",type=Path,required=True);p.add_argument("--stage5-archive-report",type=Path,required=True);p.add_argument("--expected-commit",required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();m=freeze(artifacts_root=a.artifacts_root.resolve(),annual_manifest_path=a.annual_manifest.resolve(),stage6_plan_path=a.stage6_plan.resolve(),stage7_plan_path=a.stage7_plan.resolve(),stage5_archive_report_path=a.stage5_archive_report.resolve(),expected_commit=a.expected_commit,output=a.output.resolve());print(json.dumps(m,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
