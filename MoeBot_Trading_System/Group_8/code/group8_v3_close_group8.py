#!/usr/bin/env python3
"""Prepare compact official Group8 V3 closure and Group9 handoff."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash

def _v(r:dict[str,Any],f:str)->None:
 x=dict(r);s=str(x.pop(f))
 if stable_hash(x)!=s:raise RuntimeError(f"{f} mismatch")

def close(*,annual23_path:Path,annual24_path:Path,freeze_path:Path,cross_path:Path,stage6_2023_union_path:Path,stage7_2023_union_path:Path,stage6_2024_union_path:Path,stage7_2024_union_path:Path,output:Path,handoff:Path)->dict[str,Any]:
 a23=json.loads(annual23_path.read_text());_v(a23,"manifest_hash");a24=json.loads(annual24_path.read_text());_v(a24,"manifest_hash");fr=json.loads(freeze_path.read_text());_v(fr,"manifest_hash");cr=json.loads(cross_path.read_text());_v(cr,"report_hash")
 unions=[]
 for p in (stage6_2023_union_path,stage7_2023_union_path,stage6_2024_union_path,stage7_2024_union_path):
  x=json.loads(p.read_text());_v(x,"report_hash");unions.append(x)
 if cr.get("status")!="PASS" or not cr.get("identity_stable_across_oos_boundary"):raise RuntimeError("cross-year not PASS")
 if any(x.get("status")!="PASS" for x in unions):raise RuntimeError("union not PASS")
 if any(int(x.get("duplicate_domain_id_count",-1))!=0 for x in unions):raise RuntimeError("duplicate IDs in union")
 c={"format_version":1,"status":"OFFICIALLY_CLOSED_V3","group":8,"officially_closed":True,"group9_authorized":True,"validated_commit":fr["validated_commit"],"annual_2023_manifest_hash":a23["manifest_hash"],"oos_freeze_manifest_hash":fr["manifest_hash"],"annual_2024_oos_manifest_hash":a24["manifest_hash"],"cross_year_report_hash":cr["report_hash"],"annual_2023_logical_fingerprint":a23["logical_fingerprint"],"annual_2024_logical_fingerprint":a24["logical_fingerprint"],"storage_mode":"lossless shard-aware V3","consumption_policy":{"read_only":True,"verify_manifest_hashes":True,"preserve_causal_timestamps":True,"do_not_rebuild_group8_semantics":True,"groups9_15_use_shard_aware_adapter_or_verified_union":True},"large_artifact_policy":"Large SQLite/zstd shard data remains server-side; GitHub stores compact manifests, hashes, tests, and closure evidence."}
 c["closure_hash"]=stable_hash(c);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(c,indent=2,sort_keys=True)+"\n")
 h={"format_version":1,"status":"FROZEN_HANDOFF","source_group":8,"target_group":9,"closure_hash":c["closure_hash"],"validated_commit":fr["validated_commit"],"annual_2023_manifest_hash":a23["manifest_hash"],"annual_2024_oos_manifest_hash":a24["manifest_hash"],"cross_year_report_hash":cr["report_hash"],"storage_mode":c["storage_mode"],"consumption_policy":c["consumption_policy"]}
 h["manifest_hash"]=stable_hash(h);handoff.parent.mkdir(parents=True,exist_ok=True);handoff.write_text(json.dumps(h,indent=2,sort_keys=True)+"\n");return c

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--annual-2023",type=Path,required=True);p.add_argument("--annual-2024",type=Path,required=True);p.add_argument("--freeze",type=Path,required=True);p.add_argument("--cross-year",type=Path,required=True);p.add_argument("--stage6-2023-union",type=Path,required=True);p.add_argument("--stage7-2023-union",type=Path,required=True);p.add_argument("--stage6-2024-union",type=Path,required=True);p.add_argument("--stage7-2024-union",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--handoff",type=Path,required=True)
 a=p.parse_args();r=close(annual23_path=a.annual_2023.resolve(),annual24_path=a.annual_2024.resolve(),freeze_path=a.freeze.resolve(),cross_path=a.cross_year.resolve(),stage6_2023_union_path=a.stage6_2023_union.resolve(),stage7_2023_union_path=a.stage7_2023_union.resolve(),stage6_2024_union_path=a.stage6_2024_union.resolve(),stage7_2024_union_path=a.stage7_2024_union.resolve(),output=a.output.resolve(),handoff=a.handoff.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
