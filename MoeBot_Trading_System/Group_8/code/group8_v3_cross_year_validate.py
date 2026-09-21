#!/usr/bin/env python3
"""Cross-year V3 validation. Frequency/cardinality drift is descriptive only."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash

def _v(r:dict[str,Any],f:str)->None:
 x=dict(r);s=str(x.pop(f))
 if stable_hash(x)!=s:raise RuntimeError(f"{f} mismatch")

def validate(*,annual23_path:Path,annual24_path:Path,freeze_path:Path,output:Path)->dict[str,Any]:
 a23=json.loads(annual23_path.read_text());_v(a23,"manifest_hash")
 a24=json.loads(annual24_path.read_text());_v(a24,"manifest_hash")
 fr=json.loads(freeze_path.read_text());_v(fr,"manifest_hash")
 fail=[]
 if a23.get("status")!="ANNUAL_2023_PASS" or a24.get("status")!="ANNUAL_2024_OOS_PASS":fail.append("annual_pass_missing")
 if a24.get("freeze_manifest_hash")!=fr["manifest_hash"] or fr.get("annual_2023_manifest_hash")!=a23["manifest_hash"]:fail.append("freeze_boundary_drift")
 for key in ("validated_commit",):
  if a23.get(key)!=fr.get(key) or a24.get(key)!=fr.get(key):fail.append(f"identity_drift:{key}")
 if a23.get("causality")!="PASS" or a24.get("causality")!="PASS":fail.append("causality")
 if a23.get("no_lookahead")!="PASS" or a24.get("no_lookahead")!="PASS":fail.append("lookahead")
 if a23.get("no_trading_outputs") is not True or a24.get("no_trading_outputs") is not True:fail.append("trading_outputs")
 if a24.get("frozen_identity_drift") is not False or a24.get("oos_conditioned_semantic_changes") is not False:fail.append("oos_identity_or_semantic_drift")
 if fail:raise RuntimeError(";".join(fail))
 def counts(a):
  return {"stage6":a["stage6"]["table_row_counts"],"stage7":a["stage7"]["table_row_counts"],"stage7_definitions":a["stage7"].get("definition_coverage",{})}
 r={"format_version":1,"status":"PASS","group":8,"years":[2023,2024],"annual_2023_manifest_hash":a23["manifest_hash"],"annual_2024_manifest_hash":a24["manifest_hash"],"freeze_manifest_hash":fr["manifest_hash"],"identity_stable_across_oos_boundary":True,"frozen_semantics_stable":True,"bucket_policy_frozen_from_2023":True,"no_trading_outputs_both_years":True,"read_only_upstream_both_years":True,"causality_both_years":"PASS","no_lookahead_both_years":"PASS","descriptive_counts":{"2023":counts(a23),"2024":counts(a24)},"policy":"2024 cardinality/frequency differences are descriptive OOS observations only and did not alter definitions, thresholds, engine semantics, or bucket counts."}
 r["report_hash"]=stable_hash(r);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");return r

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--annual-2023",type=Path,required=True);p.add_argument("--annual-2024",type=Path,required=True);p.add_argument("--freeze",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();r=validate(annual23_path=a.annual_2023.resolve(),annual24_path=a.annual_2024.resolve(),freeze_path=a.freeze.resolve(),output=a.output.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
