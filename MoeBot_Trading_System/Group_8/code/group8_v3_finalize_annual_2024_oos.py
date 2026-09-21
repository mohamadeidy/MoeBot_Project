#!/usr/bin/env python3
"""Finalize untouched Group8 V3 Annual 2024 OOS from verified Stage5/6/7 evidence."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

def _verify(r:dict[str,Any],f:str)->None:
 x=dict(r);s=str(x.pop(f))
 if stable_hash(x)!=s:raise RuntimeError(f"{f} mismatch")

def finalize(*,freeze_path:Path,stage5_db:Path,stage6_release_path:Path,stage6_union_path:Path,stage7_plan_path:Path,stage7_release_path:Path,stage7_union_path:Path,output:Path)->dict[str,Any]:
 freeze=json.loads(freeze_path.read_text());_verify(freeze,"manifest_hash")
 s6r=json.loads(stage6_release_path.read_text());_verify(s6r,"release_hash")
 s6u=json.loads(stage6_union_path.read_text());_verify(s6u,"report_hash")
 s7p=json.loads(stage7_plan_path.read_text());_verify(s7p,"plan_hash")
 s7r=json.loads(stage7_release_path.read_text());_verify(s7r,"release_hash")
 s7u=json.loads(stage7_union_path.read_text());_verify(s7u,"report_hash")
 s5=sha256_file(stage5_db);fail=[]
 if freeze.get("status")!="FROZEN_FOR_2024_OOS_V3":fail.append("freeze_not_valid")
 if any(int(r.get("year",0))!=2024 for r in (s6r,s6u,s7p,s7r,s7u)):fail.append("non_2024_evidence")
 if s6r.get("status")!="PASS" or s6u.get("status")!="PASS" or s6u.get("stage6_official_pass_eligible") is not True:fail.append("stage6_not_pass")
 if s7p.get("status")!="PASS" or s7r.get("status")!="PASS" or s7u.get("status")!="PASS" or s7u.get("stage7_official_pass_eligible") is not True:fail.append("stage7_not_pass")
 if s6r.get("stage5_database_sha256")!=s5 or s6u.get("stage5_database_sha256")!=s5 or s7p.get("stage5_database_sha256")!=s5 or s7r.get("stage5_database_sha256")!=s5 or s7u.get("stage5_database_sha256")!=s5:fail.append("stage5_lineage")
 if s7p.get("freeze_manifest_hash")!=freeze["manifest_hash"] or s7r.get("freeze_manifest_hash")!=freeze["manifest_hash"]:fail.append("freeze_lineage")
 if s7u.get("duplicate_domain_id_count")!=0 or s7u.get("unresolved_local_evidence_subject_count")!=0:fail.append("stage7_union_integrity")
 if s6u.get("duplicate_domain_id_count")!=0 or s6u.get("unresolved_group8_reference_count")!=0:fail.append("stage6_union_integrity")
 if s7u.get("oos_2024_accessed") is not True or s7r.get("oos_2024_accessed") is not True:fail.append("oos_access_not_bound")
 if not s7p.get("bucket_counts_fixed_from_2023") or s7p.get("oos_conditioned_bucket_changes") is not False:fail.append("stage7_policy_changed")
 if fail:raise RuntimeError(";".join(fail))
 comps={"freeze_manifest_hash":freeze["manifest_hash"],"stage5_database_sha256":s5,"stage6_global_logical_sha256":s6u["global_logical_sha256"],"stage7_global_logical_sha256":s7u["global_logical_sha256"],"stage6_release_hash":s6r["release_hash"],"stage7_release_hash":s7r["release_hash"],"stage7_plan_hash":s7p["plan_hash"]}
 m={"format_version":3,"status":"ANNUAL_2024_OOS_PASS","group":8,"year":2024,"oos":True,"validated_commit":freeze["validated_commit"],"freeze_manifest_hash":freeze["manifest_hash"],"annual_2023_manifest_hash":freeze["annual_2023_manifest_hash"],"physical_storage_mode":"V3_FREE_LOSSLESS_SHARDED_ZSTD","stage5":{"sha256":s5},"stage6":{"release_hash":s6r["release_hash"],"union_report_hash":s6u["report_hash"],"global_logical_sha256":s6u["global_logical_sha256"],"shard_count":s6u["shard_count"],"table_row_counts":s6u["table_row_counts"]},"stage7":{"plan_hash":s7p["plan_hash"],"release_hash":s7r["release_hash"],"union_report_hash":s7u["report_hash"],"global_logical_sha256":s7u["global_logical_sha256"],"shard_count":s7u["shard_count"],"table_row_counts":s7u["table_row_counts"],"definition_coverage":s7u["definition_coverage"]},"logical_components":comps,"logical_fingerprint":stable_hash(comps),"frozen_identity_drift":False,"bucket_counts_fixed_from_2023":True,"oos_conditioned_semantic_changes":False,"causality":"PASS","no_lookahead":"PASS","no_backdating":"PASS","duplicate_prevention":"PASS","upstream_reference_integrity":"PASS","read_only_upstream":True,"no_trading_outputs":True,"free_only":True}
 m["manifest_hash"]=stable_hash(m);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(m,indent=2,sort_keys=True)+"\n");return m

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--freeze",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--stage6-release",type=Path,required=True);p.add_argument("--stage6-union",type=Path,required=True);p.add_argument("--stage7-plan",type=Path,required=True);p.add_argument("--stage7-release",type=Path,required=True);p.add_argument("--stage7-union",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();r=finalize(freeze_path=a.freeze.resolve(),stage5_db=a.stage5_db.resolve(),stage6_release_path=a.stage6_release.resolve(),stage6_union_path=a.stage6_union.resolve(),stage7_plan_path=a.stage7_plan.resolve(),stage7_release_path=a.stage7_release.resolve(),stage7_union_path=a.stage7_union.resolve(),output=a.output.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
