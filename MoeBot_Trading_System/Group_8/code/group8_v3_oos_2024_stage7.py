#!/usr/bin/env python3
"""Frozen-policy V3 Stage7 executor for untouched 2024 OOS."""
from __future__ import annotations
import argparse,bisect,json,math,os,sqlite3,time
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_oos_2024_stage5 import verify_freeze
from group8_v3_stage6_range_shard_executor import bucket_for_root,epoch_month,stable_hash
from group8_v3_stage7_plan import _range_roots
from group8_v3_stage7_shard_executor import _qualified_root
from group8_v3_stage7_shard_executor import Stage7ShardSpec,Stage7RangeChainEngine,Stage7SchoolCoreEngine,build_manifest,compress_verified_shard
from moebot_group8_engine_v0_8_0 import sha256_file

HARD=2_500_000_000

def _atomic(p:Path,x:dict[str,Any])->None:
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n");os.replace(t,p)

def _policy(freeze:dict[str,Any],family:str,tf:str,month:str)->int:
 key=f"{family}:{tf}:{month[5:]}"
 try:return int(freeze["stage7_bucket_policy_by_family_timeframe_month"][key])
 except KeyError:raise RuntimeError(f"no frozen 2023 Stage7 bucket count for {key}")

def build_plan(*,staging_db:Path,stage5_db:Path,artifacts_root:Path,freeze_path:Path,work_root:Path,symbol:str,output:Path)->dict[str,Any]:
 freeze=verify_freeze(artifacts_root,freeze_path)
 stage5=sqlite3.connect(f"file:{stage5_db.resolve()}?mode=ro&immutable=1",uri=True);stage5.row_factory=sqlite3.Row
 staging=sqlite3.connect(f"file:{staging_db.resolve()}?mode=ro&immutable=1",uri=True);staging.row_factory=sqlite3.Row
 try:rr=_range_roots(staging=staging,stage5=stage5,symbol=symbol)
 finally:stage5.close();staging.close()
 # Enumerate frozen school-core actions with a genuine 2024 constructor.
 scratch=work_root/"oos2024_school_inventory.sqlite";scratch_cp=work_root/"oos2024_school_inventory.checkpoint.json"
 for p in (scratch,scratch_cp):
  if p.exists():p.unlink()
 spec0=Stage7ShardSpec("school_core",2024,symbol,"M1","2024-01",1,0)
 eng0=Stage7SchoolCoreEngine(staging_db=staging_db,output_db=scratch,artifacts_root=artifacts_root,year=2024,symbol=symbol,stage5_db=stage5_db,checkpoint_path=scratch_cp,shard_spec=spec0,hard_guard_bytes=HARD)
 grouped={}
 try:
  eng0.verify_stage5_boundary();eng0._belongs=lambda root_key,timeframe,root_time: True
  for definition,kwargs in eng0._iter_actions():
   refs=list(kwargs["upstream_refs"])
   if not refs:raise RuntimeError(f"{definition} emitted no mandatory evidence")
   first=refs[0];root_id=f"{first['source_group']}:{first['source_type']}:{first['source_id']}"
   rt=first.get("event_time") if first.get("event_time") is not None else kwargs["event_time"]
   tf=str(first.get("timeframe") or kwargs["timeframe"]);month=epoch_month(int(rt));key=(tf,month,root_id)
   z=grouped.setdefault(key,{"root_id":root_id,"interpretations":0,"evidence_chain_rows":0});z["interpretations"]+=1;z["evidence_chain_rows"]+=len(refs)
 finally:
  eng0.close(commit=False)
  for p in (scratch,scratch_cp):
   if p.exists():p.unlink()
 sr=defaultdict(list)
 for (tf,month,_),rec in grouped.items():sr[(tf,month)].append(rec)
 shards=[];ri=re=si=se=0
 for family,groups in (("range_chain",rr),("school_core",sr)):
  for (tf,month),roots in sorted(groups.items()):
   n=_policy(freeze,family,tf,month);agg=defaultdict(lambda:{"interpretations":0,"evidence_chain_rows":0})
   for r in roots:
    b=bucket_for_root(str(r["root_id"]),n);agg[b]["interpretations"]+=int(r["interpretations"]);agg[b]["evidence_chain_rows"]+=int(r["evidence_chain_rows"])
   for b,v in sorted(agg.items()):
    if int(v["interpretations"])<=0:continue
    shards.append({"family":family,"year":2024,"symbol":symbol,"timeframe":tf,"root_month":month,"bucket_count":n,"bucket_index":b,**v})
    if family=="range_chain":ri+=int(v["interpretations"]);re+=int(v["evidence_chain_rows"])
    else:si+=int(v["interpretations"]);se+=int(v["evidence_chain_rows"])
 plan={"format_version":1,"status":"PASS","stage":7,"year":2024,"oos":True,"symbol":symbol,"validated_commit":freeze["validated_commit"],"freeze_manifest_hash":freeze["manifest_hash"],"stage5_database_sha256":sha256_file(stage5_db),"shard_count":len(shards),"range_chain_shard_count":sum(s["family"]=="range_chain" for s in shards),"school_core_shard_count":sum(s["family"]=="school_core" for s in shards),"shards":shards,"expected_cardinality":{"premium_discount_interpretations":ri,"school_core_interpretations":si,"total_stage7_interpretations":ri+si,"evidence_chain_rows":re+se},"bucket_counts_fixed_from_2023":True,"oos_conditioned_bucket_changes":False,"hard_guard_bytes":HARD,"execution_policy":{"one_raw_shard_at_a_time":True,"zstd_level":6,"delete_raw_only_after_roundtrip_sha_match":True}}
 plan["plan_hash"]=stable_hash(plan);_atomic(output,plan);return plan

def _run_one(*,staging_db:Path,stage5_db:Path,artifacts_root:Path,freeze:dict[str,Any],s:dict[str,Any],raw:Path,cp:Path,mf:Path,chunk:int)->dict[str,Any]:
 spec=Stage7ShardSpec(s["family"],2024,s["symbol"],s["timeframe"],s["root_month"],int(s["bucket_count"]),int(s["bucket_index"]))
 cls=Stage7RangeChainEngine if s["family"]=="range_chain" else Stage7SchoolCoreEngine
 eng=cls(staging_db=staging_db,output_db=raw,artifacts_root=artifacts_root,year=2024,symbol=s["symbol"],stage5_db=stage5_db,checkpoint_path=cp,shard_spec=spec,hard_guard_bytes=HARD)
 try:ch=eng.run_resumable(chunk_interpretations=chunk)
 except Exception:eng.close(commit=False);raise
 else:eng.close(commit=True)
 if ch.get("completed") is not True:raise RuntimeError("OOS Stage7 shard incomplete")
 m=build_manifest(output_db=raw,artifacts_root=artifacts_root,spec=spec,checkpoint=ch,stage5_sha256=sha256_file(stage5_db),stage6_release_hash="OOS_STAGE6_BOUND_AT_RELEASE",stage6_union_report_hash="OOS_STAGE6_BOUND_AT_RELEASE")
 _atomic(mf,m);return m

def execute(*,plan_path:Path,staging_db:Path,stage5_db:Path,artifacts_root:Path,freeze_path:Path,stage6_release_path:Path,stage6_union_path:Path,output_root:Path,progress_path:Path,release_path:Path,zstd_exe:Path,chunk:int)->dict[str,Any]:
 freeze=verify_freeze(artifacts_root,freeze_path);plan=json.loads(plan_path.read_text());x=dict(plan);ph=x.pop("plan_hash")
 if stable_hash(x)!=ph or plan["freeze_manifest_hash"]!=freeze["manifest_hash"] or plan["stage5_database_sha256"]!=sha256_file(stage5_db):raise RuntimeError("OOS Stage7 plan lineage drift")
 s6r=json.loads(stage6_release_path.read_text());s6u=json.loads(stage6_union_path.read_text())
 if s6r.get("status")!="PASS" or s6u.get("status")!="PASS" or int(s6r.get("year",0))!=2024:raise RuntimeError("OOS Stage6 not PASS")
 output_root.mkdir(parents=True,exist_ok=True);done=[];started=time.monotonic()
 for i,s in enumerate(plan["shards"]):
  stem=f"g8_stage7_{s['family']}_2024_{s['timeframe']}_{s['root_month']}_b{int(s['bucket_index']):04d}of{int(s['bucket_count']):04d}"
  raw=output_root/"raw"/f"{stem}.sqlite";cp=output_root/"checkpoints"/f"{stem}.json";mf=output_root/"manifests"/f"{stem}.json";arc=output_root/"compressed"/f"{stem}.sqlite.zst"
  for p in (raw,cp,mf,arc):p.parent.mkdir(parents=True,exist_ok=True)
  if mf.exists() and arc.exists():
   m=json.loads(mf.read_text());y=dict(m);mh=y.pop("manifest_hash")
   if stable_hash(y)!=mh or sha256_file(arc)!=m["compressed_sha256"]:raise RuntimeError("existing OOS Stage7 shard identity mismatch")
  else:
   m=_run_one(staging_db=staging_db,stage5_db=stage5_db,artifacts_root=artifacts_root,freeze=freeze,s=s,raw=raw,cp=cp,mf=mf,chunk=chunk)
   # bind actual OOS Stage6 lineage before compression; this is metadata only.
   m["stage6_release_hash"]=s6r["release_hash"];m["stage6_union_report_hash"]=s6u["report_hash"];m.pop("manifest_hash",None);m["manifest_hash"]=stable_hash(m);_atomic(mf,m)
   m=compress_verified_shard(database=raw,manifest_path=mf,archive=arc,zstd_exe=zstd_exe,level=6,remove_raw=True)
  done.append({"ordinal":i,"spec":s,"manifest_path":str(mf.relative_to(output_root)),"archive_path":str(arc.relative_to(output_root)),"manifest_hash":m["manifest_hash"],"raw_sha256":m["sha256"],"compressed_sha256":m["compressed_sha256"],"compressed_size_bytes":m["compressed_size_bytes"],"table_row_counts":m["table_row_counts"],"table_logical_sha256":m["table_logical_sha256"]})
  pr={"status":"RUNNING" if len(done)<len(plan["shards"]) else "PASS","completed_shards":len(done),"total_shards":len(plan["shards"]),"elapsed_seconds":time.monotonic()-started,"freeze_manifest_hash":freeze["manifest_hash"]};pr["progress_hash"]=stable_hash(pr);_atomic(progress_path,pr)
 irows=sum(int(x["table_row_counts"]["school_interpretation"]) for x in done);erows=sum(int(x["table_row_counts"]["evidence_chain"]) for x in done)
 if irows!=int(plan["expected_cardinality"]["total_stage7_interpretations"]) or erows!=int(plan["expected_cardinality"]["evidence_chain_rows"]):raise RuntimeError("OOS Stage7 aggregate cardinality mismatch")
 release={"format_version":1,"scope":"GROUP8_V3_STAGE7_2024_OOS_RELEASE","status":"PASS","stage":7,"stage_name":"ict_core","year":2024,"oos":True,"symbol":plan["symbol"],"validated_commit":freeze["validated_commit"],"freeze_manifest_hash":freeze["manifest_hash"],"plan_hash":plan["plan_hash"],"stage5_database_sha256":plan["stage5_database_sha256"],"stage6_release_hash":s6r["release_hash"],"stage6_union_report_hash":s6u["report_hash"],"shard_count":len(done),"range_chain_shard_count":sum(x["spec"]["family"]=="range_chain" for x in done),"school_core_shard_count":sum(x["spec"]["family"]=="school_core" for x in done),"table_row_counts":{"school_interpretation":irows,"evidence_chain":erows},"total_compressed_bytes":sum(int(x["compressed_size_bytes"]) for x in done),"shards":done,"groups_1_7_read_only":True,"stage5_read_only":True,"oos_2024_accessed":True,"frozen_semantics":True}
 release["release_hash"]=stable_hash(release);_atomic(release_path,release);return release

def main()->int:
 p=argparse.ArgumentParser();sp=p.add_subparsers(dest="cmd",required=True)
 a=sp.add_parser("plan");a.add_argument("--staging-db",type=Path,required=True);a.add_argument("--stage5-db",type=Path,required=True);a.add_argument("--artifacts-root",type=Path,required=True);a.add_argument("--freeze",type=Path,required=True);a.add_argument("--work-root",type=Path,required=True);a.add_argument("--symbol",required=True);a.add_argument("--output",type=Path,required=True)
 b=sp.add_parser("execute");b.add_argument("--plan",type=Path,required=True);b.add_argument("--staging-db",type=Path,required=True);b.add_argument("--stage5-db",type=Path,required=True);b.add_argument("--artifacts-root",type=Path,required=True);b.add_argument("--freeze",type=Path,required=True);b.add_argument("--stage6-release",type=Path,required=True);b.add_argument("--stage6-union",type=Path,required=True);b.add_argument("--output-root",type=Path,required=True);b.add_argument("--progress",type=Path,required=True);b.add_argument("--release",type=Path,required=True);b.add_argument("--zstd-exe",type=Path,required=True);b.add_argument("--chunk",type=int,default=5000)
 x=p.parse_args()
 if x.cmd=="plan":r=build_plan(staging_db=x.staging_db.resolve(),stage5_db=x.stage5_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),work_root=x.work_root.resolve(),symbol=x.symbol,output=x.output.resolve())
 else:r=execute(plan_path=x.plan.resolve(),staging_db=x.staging_db.resolve(),stage5_db=x.stage5_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),stage6_release_path=x.stage6_release.resolve(),stage6_union_path=x.stage6_union.resolve(),output_root=x.output_root.resolve(),progress_path=x.progress.resolve(),release_path=x.release.resolve(),zstd_exe=x.zstd_exe.resolve(),chunk=x.chunk)
 print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
