#!/usr/bin/env python3
"""Group 8 V3 Stage 7 annual 2023 orchestrator.

Consumes a frozen PASS annual plan. It executes exactly one raw shard at a time,
resumes deterministic checkpoints, validates the raw SQLite shard, performs
lossless zstd compression with streamed round-trip SHA verification, deletes the
raw shard only after proof, and publishes an atomic release manifest.

It never touches 2024 and never changes frozen trading semantics.
"""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,time
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_stage7_shard_executor import Stage7ShardSpec,compress_verified_shard,run_shard
from moebot_group8_engine_v0_8_0 import sha256_file

HARD_GUARD=2_500_000_000

def _atomic_json(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(tmp,path)

def _verify_hash(rec:dict[str,Any],field:str)->None:
    x=dict(rec);saved=str(x.pop(field))
    if stable_hash(x)!=saved: raise RuntimeError(f"{field} mismatch")

def _git_head(root:Path)->str:
    repo=root.resolve().parent.parent
    return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()

def _safe(v:str)->str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in str(v))

def _stem(s:dict[str,Any])->str:
    return f"g8_stage7_{_safe(s['family'])}_{s['year']}_{_safe(s['timeframe'])}_{_safe(s['root_month'])}_b{int(s['bucket_index']):04d}of{int(s['bucket_count']):04d}"

def _paths(root:Path,s:dict[str,Any])->tuple[Path,Path,Path,Path]:
    stem=_stem(s)
    return (
      root/"raw"/f"{stem}.sqlite",
      root/"checkpoints"/f"{stem}.checkpoint.json",
      root/"manifests"/f"{stem}.manifest.json",
      root/"compressed"/f"{stem}.sqlite.zst",
    )

def _verified_completed(*,manifest_path:Path,archive:Path,spec:dict[str,Any],stage5_sha:str,plan:dict[str,Any])->dict[str,Any]|None:
    if not manifest_path.exists() and not archive.exists(): return None
    if not manifest_path.exists() or not archive.exists():
        raise RuntimeError(f"incomplete completed-shard evidence:{manifest_path}:{archive}")
    m=json.loads(manifest_path.read_text());_verify_hash(m,"manifest_hash")
    checks={
      "status":"PASS","stage":7,"stage_name":"ict_core","family":spec["family"],
      "year":int(spec["year"]),"symbol":spec["symbol"],"timeframe":spec["timeframe"],
      "causal_root_window":spec["root_month"],"bucket_count":int(spec["bucket_count"]),
      "bucket_index":int(spec["bucket_index"]),"stage5_database_sha256":stage5_sha,
      "stage6_release_hash":plan["stage6_release_hash"],
      "stage6_union_report_hash":plan["stage6_union_report_hash"],
      "storage_contract_hash":plan["storage_contract_hash"],"design_freeze_hash":plan["design_freeze_hash"],
    }
    for k,v in checks.items():
        if m.get(k)!=v: raise RuntimeError(f"existing Stage7 manifest mismatch {k}:{m.get(k)!r}!={v!r}")
    if m.get("raw_retained") is not False: raise RuntimeError("completed compressed shard still claims raw_retained")
    if m.get("compression_roundtrip_sha256")!=m.get("sha256"): raise RuntimeError("completed shard lacks exact roundtrip proof")
    if archive.stat().st_size!=int(m.get("compressed_size_bytes",-1)): raise RuntimeError("compressed shard size mismatch")
    if sha256_file(archive)!=m.get("compressed_sha256"): raise RuntimeError("compressed shard SHA mismatch")
    return m

def _progress(*,path:Path,plan:dict[str,Any],completed:list[dict[str,Any]],started:float,status:str)->dict[str,Any]:
    total=int(plan["shard_count"]);done=len(completed);elapsed=max(time.monotonic()-started,1e-9)
    rate=done/elapsed
    total_raw=sum(int(x["manifest"]["file_size_bytes"]) for x in completed)
    total_comp=sum(int(x["manifest"]["compressed_size_bytes"]) for x in completed)
    rec={
      "format_version":1,"scope":"GROUP8_V3_STAGE7_2023_EXECUTION_PROGRESS","status":status,
      "plan_hash":plan["plan_hash"],"validated_commit":plan["validated_commit"],
      "completed_shards":done,"total_shards":total,
      "progress_percent":100.0 if total==0 else round(100.0*done/total,6),
      "elapsed_seconds":round(elapsed,3),"shards_per_second":round(rate,8),
      "eta_seconds":None if rate<=0 else round((total-done)/rate,3),
      "total_raw_bytes_materialized":total_raw,"total_compressed_bytes_retained":total_comp,
      "updated_unix":int(time.time()),
    }
    rec["progress_hash"]=stable_hash(rec);_atomic_json(path,rec);return rec

def run_plan(*,plan_path:Path,staging_db:Path,stage5_db:Path,artifacts_root:Path,output_root:Path,progress_path:Path,release_path:Path,zstd_exe:Path,expected_commit:str,safety_floor_gb:float,chunk_interpretations:int,max_shards:int|None=None)->dict[str,Any]:
    plan=json.loads(plan_path.read_text());_verify_hash(plan,"plan_hash")
    if plan.get("status")!="PASS" or plan.get("full_annual_stage7_permitted_by_plan_gate") is False:
        raise RuntimeError("Stage7 annual plan is not PASS")
    if int(plan.get("year",0))!=2023 or plan.get("execution_policy",{}).get("oos_2024_forbidden") is not True:
        raise RuntimeError("Stage7 plan violates 2023-only/OOS lock")
    if plan.get("execution_policy",{}).get("stage7_auto_launch") is not False:
        raise RuntimeError("Stage7 plan unexpectedly permits auto-launch")
    if expected_commit!=plan.get("validated_commit") or _git_head(artifacts_root)!=expected_commit:
        raise RuntimeError("Stage7 orchestrator Git identity mismatch")
    stage5_sha=sha256_file(stage5_db)
    if stage5_sha!=plan["stage5_database_sha256"]: raise RuntimeError("Stage5 SHA drift")
    if not zstd_exe.is_file(): raise RuntimeError("zstd executable missing")
    output_root.mkdir(parents=True,exist_ok=True)

    raw_existing=list((output_root/"raw").glob("*.sqlite")) if (output_root/"raw").exists() else []
    if len(raw_existing)>1: raise RuntimeError(f"more than one raw Stage7 shard exists:{len(raw_existing)}")

    started=time.monotonic();completed:list[dict[str,Any]]=[]
    limit=None if max_shards is None else int(max_shards)
    newly_done=0

    for ordinal,s in enumerate(plan["shards"]):
        raw,cp,mf,arc=_paths(output_root,s)
        existing=_verified_completed(manifest_path=mf,archive=arc,spec=s,stage5_sha=stage5_sha,plan=plan)
        if existing is not None:
            completed.append({"ordinal":ordinal,"spec":s,"manifest_path":str(mf.relative_to(output_root)),"archive_path":str(arc.relative_to(output_root)),"manifest":existing})
            continue
        if limit is not None and newly_done>=limit:
            _progress(path=progress_path,plan=plan,completed=completed,started=started,status="RUNNING")
            return {"status":"RUNNING","completed_shards":len(completed),"total_shards":len(plan["shards"]),"stage7_authorized":False}

        others=[p for p in ((output_root/"raw").glob("*.sqlite") if (output_root/"raw").exists() else []) if p.resolve()!=raw.resolve()]
        if others: raise RuntimeError(f"one-raw-shard invariant violated by:{others[0]}")
        usage=shutil.disk_usage(output_root)
        floor=int(float(safety_floor_gb)*(1024**3))
        usable=max(int(usage.free)-floor,0)
        projected=int(s.get("window_projected_raw_bytes_with_safety",0))/max(int(s["bucket_count"]),1)
        if usable<min(max(int(projected),256*1024*1024),HARD_GUARD):
            raise RuntimeError(f"insufficient safe free space before shard {ordinal}:usable={usable},projected={projected}")

        spec=Stage7ShardSpec(s["family"],int(s["year"]),s["symbol"],s["timeframe"],s["root_month"],int(s["bucket_count"]),int(s["bucket_index"]))
        result=run_shard(
          staging_db=staging_db,stage5_db=stage5_db,output_db=raw,checkpoint_path=cp,
          manifest_path=mf,artifacts_root=artifacts_root,spec=spec,
          chunk_interpretations=chunk_interpretations,hard_guard_bytes=HARD_GUARD,
          stage6_release_hash=plan["stage6_release_hash"],stage6_union_report_hash=plan["stage6_union_report_hash"],
        )
        if result.get("status")!="PASS": raise RuntimeError(f"Stage7 shard did not complete:{ordinal}")
        cm=compress_verified_shard(database=raw,manifest_path=mf,archive=arc,zstd_exe=zstd_exe,level=int(plan["execution_policy"]["zstd_level"]),remove_raw=True)
        completed.append({"ordinal":ordinal,"spec":s,"manifest_path":str(mf.relative_to(output_root)),"archive_path":str(arc.relative_to(output_root)),"manifest":cm})
        newly_done+=1
        _progress(path=progress_path,plan=plan,completed=completed,started=started,status="RUNNING")

    if len(completed)!=int(plan["shard_count"]): raise RuntimeError("completed shard count does not equal frozen plan")
    irows=sum(int(x["manifest"]["table_row_counts"]["school_interpretation"]) for x in completed)
    erows=sum(int(x["manifest"]["table_row_counts"]["evidence_chain"]) for x in completed)
    expected_i=int(plan["expected_cardinality"]["total_stage7_interpretations"])
    if irows!=expected_i: raise RuntimeError(f"Stage7 interpretation cardinality mismatch:{irows}!={expected_i}")
    by_def:dict[str,int]={}
    for x in completed:
        for k,v in x["manifest"]["definition_coverage"].items(): by_def[k]=by_def.get(k,0)+int(v)
    release={
      "format_version":1,"scope":"GROUP8_V3_STAGE7_2023_RELEASE","status":"PASS",
      "stage":7,"stage_name":"ict_core","year":2023,"symbol":plan["symbol"],
      "validated_commit":expected_commit,"plan_hash":plan["plan_hash"],
      "stage5_database_sha256":stage5_sha,"stage6_release_hash":plan["stage6_release_hash"],
      "stage6_union_report_hash":plan["stage6_union_report_hash"],
      "storage_contract_hash":plan["storage_contract_hash"],"design_freeze_hash":plan["design_freeze_hash"],
      "shard_count":len(completed),"range_chain_shard_count":sum(x["spec"]["family"]=="range_chain" for x in completed),
      "school_core_shard_count":sum(x["spec"]["family"]=="school_core" for x in completed),
      "table_row_counts":{"school_interpretation":irows,"evidence_chain":erows},
      "definition_coverage":dict(sorted(by_def.items())),
      "total_raw_bytes":sum(int(x["manifest"]["file_size_bytes"]) for x in completed),
      "total_compressed_bytes":sum(int(x["manifest"]["compressed_size_bytes"]) for x in completed),
      "one_raw_shard_at_a_time_enforced":True,"lossless_compression_roundtrip_required":True,
      "raw_shards_retained":False,"groups_1_7_read_only":True,"stage5_read_only":True,
      "oos_2024_accessed":False,"stage8_exists":False,
      "shards":[{
        "ordinal":x["ordinal"],"spec":x["spec"],"manifest_path":x["manifest_path"],"archive_path":x["archive_path"],
        "manifest_hash":x["manifest"]["manifest_hash"],"raw_sha256":x["manifest"]["sha256"],
        "compressed_sha256":x["manifest"]["compressed_sha256"],"compressed_size_bytes":x["manifest"]["compressed_size_bytes"],
        "table_row_counts":x["manifest"]["table_row_counts"],"table_logical_sha256":x["manifest"]["table_logical_sha256"],
      } for x in completed],
      "stage7_official_pass_eligible":False,
      "next_gate":"streaming Stage7 union validation",
    }
    release["release_hash"]=stable_hash(release);_atomic_json(release_path,release)
    _progress(path=progress_path,plan=plan,completed=completed,started=started,status="PASS")
    return release

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--plan",type=Path,required=True);p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True);p.add_argument("--progress",type=Path,required=True);p.add_argument("--release",type=Path,required=True);p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--expected-commit",required=True);p.add_argument("--safety-floor-gb",type=float,default=120.0);p.add_argument("--chunk-interpretations",type=int,default=5000);p.add_argument("--max-shards",type=int)
    a=p.parse_args();r=run_plan(plan_path=a.plan.resolve(),staging_db=a.staging_db.resolve(),stage5_db=a.stage5_db.resolve(),artifacts_root=a.artifacts_root.resolve(),output_root=a.output_root.resolve(),progress_path=a.progress.resolve(),release_path=a.release.resolve(),zstd_exe=a.zstd_exe.resolve(),expected_commit=a.expected_commit,safety_floor_gb=a.safety_floor_gb,chunk_interpretations=a.chunk_interpretations,max_shards=a.max_shards)
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
