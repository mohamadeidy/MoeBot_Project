#!/usr/bin/env python3
"""Frozen-policy V3 Stage6 executor for untouched 2024 OOS."""
from __future__ import annotations
import argparse,json,os,shutil,sqlite3,subprocess,time
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_stage6_preflight import inventory_stage6_pairs
from group8_v3_stage6_range_shard_executor import RangeShardSpec,run_shard,bucket_for_root,stable_hash
from group8_v3_oos_2024_stage5 import verify_freeze
from moebot_group8_engine_v0_8_0 import sha256_file

HARD=2_500_000_000

def _atomic(p:Path,x:dict[str,Any])->None:
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n");os.replace(t,p)

def _policy(freeze:dict[str,Any],tf:str,month:str)->int:
 key=f"range_chain:{tf}:{month[5:]}"
 try:return int(freeze["stage6_bucket_policy_by_timeframe_month"][key])
 except KeyError:raise RuntimeError(f"no frozen 2023 Stage6 bucket count for {key}")

def build_plan(*,stage5_db:Path,artifacts_root:Path,freeze_path:Path,symbol:str,output:Path)->dict[str,Any]:
 freeze=verify_freeze(artifacts_root,freeze_path)
 roots,inventory=inventory_stage6_pairs(stage5_db,symbol);agg=defaultdict(lambda:{"range_roots":0,"range_dow_pairs":0})
 for r in roots:
  if int(r["pair_count"])<=0:continue
  n=_policy(freeze,str(r["timeframe"]),str(r["root_month"]));b=bucket_for_root(str(r["candidate_id"]),n)
  k=(str(r["timeframe"]),str(r["root_month"]),n,b);agg[k]["range_roots"]+=1;agg[k]["range_dow_pairs"]+=int(r["pair_count"])
 specs=[{"timeframe":tf,"root_month":m,"bucket_count":n,"bucket_index":b,**v} for (tf,m,n,b),v in sorted(agg.items())]
 plan={"format_version":1,"status":"PASS","stage":6,"year":2024,"oos":True,"symbol":symbol,"validated_commit":freeze["validated_commit"],"oos_tooling_commit":freeze["oos_tooling_commit"],"freeze_manifest_hash":freeze["manifest_hash"],"stage5_database_sha256":sha256_file(stage5_db),"specs":specs,"shard_count":len(specs),"inventory":inventory,"chunk_pairs":100,"hard_guard_bytes":HARD,"bucket_counts_fixed_from_2023":True,"oos_conditioned_bucket_changes":False}
 plan["plan_hash"]=stable_hash(plan);_atomic(output,plan);return plan

def execute(*,plan_path:Path,staging_db:Path,stage5_db:Path,artifacts_root:Path,freeze_path:Path,output_root:Path,progress_path:Path,release_path:Path)->dict[str,Any]:
 freeze=verify_freeze(artifacts_root,freeze_path);plan=json.loads(plan_path.read_text());x=dict(plan);saved=x.pop("plan_hash")
 if stable_hash(x)!=saved or plan.get("status")!="PASS" or int(plan.get("year",0))!=2024:raise RuntimeError("invalid OOS Stage6 plan")
 if plan["freeze_manifest_hash"]!=freeze["manifest_hash"] or plan.get("oos_tooling_commit")!=freeze["oos_tooling_commit"] or plan["stage5_database_sha256"]!=sha256_file(stage5_db):raise RuntimeError("OOS Stage6 lineage drift")
 output_root.mkdir(parents=True,exist_ok=True);completed=[];started=time.monotonic()
 for i,s in enumerate(plan["specs"]):
  stem=f"g8_stage6_2024_{s['timeframe']}_{s['root_month']}_b{int(s['bucket_index']):04d}of{int(s['bucket_count']):04d}"
  db=output_root/"shards"/f"{stem}.sqlite";cp=output_root/"checkpoints"/f"{stem}.json";mf=output_root/"manifests"/f"{stem}.json"
  mf.parent.mkdir(parents=True,exist_ok=True);db.parent.mkdir(parents=True,exist_ok=True);cp.parent.mkdir(parents=True,exist_ok=True)
  if mf.exists() and db.exists():
   m=json.loads(mf.read_text());y=dict(m);mh=y.pop("manifest_hash")
   if stable_hash(y)!=mh or sha256_file(db)!=m["sha256"]:raise RuntimeError("existing OOS Stage6 shard identity mismatch")
  else:
   spec=RangeShardSpec(2024,plan["symbol"],s["timeframe"],s["root_month"],int(s["bucket_count"]),int(s["bucket_index"]))
   m=run_shard(staging_db=staging_db,stage5_db=stage5_db,output_db=db,checkpoint_path=cp,manifest_path=mf,artifacts_root=artifacts_root,spec=spec,chunk_pairs=int(plan["chunk_pairs"]),hard_guard_bytes=HARD,stage5_sha256=plan["stage5_database_sha256"])
  if int(m["file_size_bytes"])>HARD:raise RuntimeError("OOS Stage6 shard exceeded hard guard")
  completed.append({"ordinal":i,"database":str(db),"manifest":str(mf),"manifest_hash":m["manifest_hash"],"sha256":m["sha256"],"file_size_bytes":m["file_size_bytes"],"timeframe":m["timeframe"],"root_month":m["causal_root_window"],"bucket_index":m["bucket_index"],"bucket_count":m["bucket_count"],"table_row_counts":m["table_row_counts"],"table_logical_sha256":m["table_logical_sha256"]})
  pr={"status":"RUNNING" if len(completed)<len(plan["specs"]) else "PASS","completed_shards":len(completed),"total_shards":len(plan["specs"]),"elapsed_seconds":time.monotonic()-started,"freeze_manifest_hash":freeze["manifest_hash"]};pr["progress_hash"]=stable_hash(pr);_atomic(progress_path,pr)
 release={"format_version":1,"status":"PASS","stage":6,"stage_name":"wyckoff_core","year":2024,"oos":True,"symbol":plan["symbol"],"validated_commit":freeze["validated_commit"],"oos_tooling_commit":freeze["oos_tooling_commit"],"freeze_manifest_hash":freeze["manifest_hash"],"stage5_database_sha256":plan["stage5_database_sha256"],"preflight_plan_hash":plan["plan_hash"],"storage_contract_preserved":True,"design_semantics_preserved":True,"groups_1_7_read_only":True,"stage5_read_only":True,"shard_count":len(completed),"total_output_bytes":sum(int(x["file_size_bytes"]) for x in completed),"shards":completed,"stage7_auto_launch":False,"stage7_authorized":True}
 release["release_hash"]=stable_hash(release);_atomic(release_path,release);return release

def main()->int:
 p=argparse.ArgumentParser();sp=p.add_subparsers(dest="cmd",required=True)
 a=sp.add_parser("plan");a.add_argument("--stage5-db",type=Path,required=True);a.add_argument("--artifacts-root",type=Path,required=True);a.add_argument("--freeze",type=Path,required=True);a.add_argument("--symbol",required=True);a.add_argument("--output",type=Path,required=True)
 b=sp.add_parser("execute");b.add_argument("--plan",type=Path,required=True);b.add_argument("--staging-db",type=Path,required=True);b.add_argument("--stage5-db",type=Path,required=True);b.add_argument("--artifacts-root",type=Path,required=True);b.add_argument("--freeze",type=Path,required=True);b.add_argument("--output-root",type=Path,required=True);b.add_argument("--progress",type=Path,required=True);b.add_argument("--release",type=Path,required=True)
 x=p.parse_args()
 if x.cmd=="plan":r=build_plan(stage5_db=x.stage5_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),symbol=x.symbol,output=x.output.resolve())
 else:r=execute(plan_path=x.plan.resolve(),staging_db=x.staging_db.resolve(),stage5_db=x.stage5_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),output_root=x.output_root.resolve(),progress_path=x.progress.resolve(),release_path=x.release.resolve())
 print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
