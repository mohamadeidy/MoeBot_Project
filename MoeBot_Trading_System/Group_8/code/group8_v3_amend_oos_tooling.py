#!/usr/bin/env python3
"""Create a disclosed post-freeze physical-tooling amendment for 2024 OOS.

This is intentionally narrow. It may rebind exact physical executor identities
after OOS access only when frozen semantics, definitions, schema, config,
thresholds, upstream lineage, and 2023-derived bucket policies remain unchanged.
The prior pre-OOS freeze remains cryptographically linked and is never erased.
"""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_freeze_oos_2024 import TOOLS,_bucket_policy,_identity,_verify
from moebot_group8_engine_v0_8_0 import sha256_file

def _head(root:Path)->str:
 repo=root.resolve().parent.parent
 return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()

def amend(*,artifacts_root:Path,prior_freeze_path:Path,annual_manifest_path:Path,stage6_plan_path:Path,stage7_plan_path:Path,stage5_archive_report_path:Path,zstd_exe:Path,expected_commit:str,output:Path)->dict[str,Any]:
 if _head(artifacts_root)!=expected_commit:raise RuntimeError("Git HEAD mismatch for OOS tooling amendment")
 prior=json.loads(prior_freeze_path.read_text());_verify(prior,"manifest_hash")
 annual=json.loads(annual_manifest_path.read_text());_verify(annual,"manifest_hash")
 s6=json.loads(stage6_plan_path.read_text());_verify(s6,"plan_hash")
 s7=json.loads(stage7_plan_path.read_text());_verify(s7,"plan_hash")
 arc=json.loads(stage5_archive_report_path.read_text());_verify(arc,"report_hash")
 if prior.get("status")!="FROZEN_FOR_2024_OOS_V3":raise RuntimeError("prior OOS freeze invalid")
 if annual.get("status")!="ANNUAL_2023_PASS" or annual.get("oos_2024_accessed") is not False:raise RuntimeError("Annual 2023 lineage invalid")
 if prior.get("annual_2023_manifest_hash")!=annual["manifest_hash"]:raise RuntimeError("prior freeze/Annual 2023 drift")
 if prior.get("validated_commit")!=annual.get("validated_commit"):raise RuntimeError("prior semantic commit drift")
 if arc.get("status")!="PASS" or arc.get("lossless_roundtrip_verified") is not True:raise RuntimeError("Stage5 archive invalid")
 if not zstd_exe.is_file():raise RuntimeError("zstd missing")

 s6pol=_bucket_policy({"shards":[{**x,"family":"range_chain"} for x in s6["specs"]]})
 s7pol=_bucket_policy(s7)
 if s6pol!=prior.get("stage6_bucket_policy_by_timeframe_month"):raise RuntimeError("Stage6 bucket policy changed")
 if s7pol!=prior.get("stage7_bucket_policy_by_family_timeframe_month"):raise RuntimeError("Stage7 bucket policy changed")

 design=json.loads((artifacts_root/"DESIGN_FREEZE_MANIFEST.json").read_text())
 contract=json.loads((artifacts_root/"SHARDED_STORAGE_CONTRACT.json").read_text())
 if design.get("design_freeze_hash")!=prior.get("design_freeze_hash"):raise RuntimeError("design freeze changed")
 if contract.get("storage_contract_hash")!=prior.get("storage_contract_hash"):raise RuntimeError("storage contract changed")

 identities={rel:_identity(artifacts_root,rel) for rel in TOOLS}
 external_tooling={"zstd":{"path":str(zstd_exe),"size_bytes":zstd_exe.stat().st_size,"sha256":sha256_file(zstd_exe)}}
 amendment={
  "type":"POST_FREEZE_PHYSICAL_TOOLING_REPAIR",
  "reason":"Annual boundary shard validation must permit the natural next-January close timestamp of a bar opened inside the frozen annual dataset.",
  "prior_freeze_manifest_hash":prior["manifest_hash"],
  "prior_oos_tooling_commit":prior.get("oos_tooling_commit"),
  "new_oos_tooling_commit":expected_commit,
  "oos_2024_accessed_before_amendment":True,
  "semantic_changes":False,
  "definition_changes":False,
  "schema_changes":False,
  "config_changes":False,
  "threshold_changes":False,
  "upstream_lineage_changes":False,
  "bucket_policy_changes":False,
  "observed_2024_values_used_for_tuning":False,
  "repair_scope":"physical shard calendar-boundary validation only",
 }
 manifest={
  "format_version":2,"status":"FROZEN_FOR_2024_OOS_V3","group":8,"oos_year":2024,"training_validation_year":2023,
  "validated_commit":prior["validated_commit"],"oos_tooling_commit":expected_commit,
  "annual_2023_manifest_hash":annual["manifest_hash"],"annual_2023_logical_fingerprint":annual["logical_fingerprint"],
  "design_freeze_hash":prior["design_freeze_hash"],"storage_contract_hash":prior["storage_contract_hash"],
  "stage5_2023_archive_report_hash":arc["report_hash"],"stage5_2023_archive_sha256":arc["archive_sha256"],
  "stage6_2023_plan_hash":s6["plan_hash"],"stage7_2023_plan_hash":s7["plan_hash"],
  "stage6_bucket_policy_by_timeframe_month":s6pol,
  "stage7_bucket_policy_by_family_timeframe_month":s7pol,
  "identities":identities,"external_tooling":external_tooling,
  "immutability_policy":prior["immutability_policy"],
  "authorization":{"2023":False,"2024_oos":True},
  "free_only":True,"paid_runner_allowed":False,"paid_service_allowed":False,
  "oos_2024_accessed_during_freeze":False,
  "oos_2024_accessed_before_amendment":True,
  "post_freeze_physical_tooling_amendment":amendment,
  "policy":"This amended freeze preserves the exact pre-OOS semantic identity and 2023-derived bucket policy while disclosing a post-access physical executor boundary-validation repair. No 2024 observation may change trading semantics, thresholds, definitions, upstream lineage, or partition counts.",
 }
 manifest["manifest_hash"]=stable_hash(manifest)
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
 return manifest

def main()->int:
 p=argparse.ArgumentParser()
 p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--prior-freeze",type=Path,required=True)
 p.add_argument("--annual-manifest",type=Path,required=True);p.add_argument("--stage6-plan",type=Path,required=True)
 p.add_argument("--stage7-plan",type=Path,required=True);p.add_argument("--stage5-archive-report",type=Path,required=True)
 p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--expected-commit",required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();m=amend(artifacts_root=a.artifacts_root.resolve(),prior_freeze_path=a.prior_freeze.resolve(),annual_manifest_path=a.annual_manifest.resolve(),stage6_plan_path=a.stage6_plan.resolve(),stage7_plan_path=a.stage7_plan.resolve(),stage5_archive_report_path=a.stage5_archive_report.resolve(),zstd_exe=a.zstd_exe.resolve(),expected_commit=a.expected_commit,output=a.output.resolve());print(json.dumps(m,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
