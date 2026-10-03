#!/usr/bin/env python3
"""Frozen-policy PA7 execution for untouched Group 8 V3 Annual 2024 OOS.

The 2023 sizing decision is immutable. 2024 data is used only to enumerate causal
root windows that must be covered. Bucket counts may never be changed from observed
2024 cardinality, runtime, storage, or outcomes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from group8_pa7_root_window_inventory import inventory
from group8_pa7_onepass_month_partition import run_onepass_bucket
from group8_v3_oos_2024_stage5 import verify_freeze
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

YEAR=2024
HARD_GUARD_BYTES=2_500_000_000
SCOPES=("upstream","group8_range")


def _atomic(path:Path,value:dict[str,Any])->None:
    import os
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
    os.replace(tmp,path)


def _verify(rec:dict[str,Any],field:str,label:str)->None:
    if field not in rec:raise RuntimeError(f"{label}:missing {field}")
    x=dict(rec);saved=str(x.pop(field))
    if stable_hash(x)!=saved:raise RuntimeError(f"{label}:{field} mismatch")


def _policy(freeze:dict[str,Any],timeframe:str,scope:str)->int:
    key=f"{timeframe}:{scope}"
    policy=freeze.get("pa7_bucket_policy_by_timeframe_scope") or {}
    if key not in policy:raise RuntimeError(f"missing frozen PA7 OOS bucket policy:{key}")
    n=int(policy[key])
    if n<=0 or n&(n-1):raise RuntimeError(f"invalid frozen PA7 OOS bucket count:{key}:{n}")
    return n


def build_plan(*,staging_db:Path,artifacts_root:Path,freeze_path:Path,symbol:str,output:Path)->dict[str,Any]:
    freeze=verify_freeze(artifacts_root,freeze_path)
    policy=dict(freeze.get("pa7_bucket_policy_by_timeframe_scope") or {})
    if not policy:raise RuntimeError("freeze has no PA7 bucket policy")
    timeframes=sorted({str(k).split(":",1)[0] for k in policy})
    inv=inventory(
        staging_db=staging_db,artifacts_root=artifacts_root,year=YEAR,symbol=symbol,
        timeframes=timeframes,oos_freeze=freeze_path,
    )
    if inv.get("status")!="PASS" or inv.get("oos_freeze_manifest_hash")!=freeze["manifest_hash"]:
        raise RuntimeError("2024 PA7 root-window inventory not freeze-bound PASS")
    workers=[];expected_shards=0
    for tf in timeframes:
        for scope in SCOPES:
            windows=list(inv["inventory"][tf][scope]["root_windows"])
            if not windows:continue
            count=_policy(freeze,tf,scope)
            expected_shards+=len(windows)*count
            for bucket in range(count):
                workers.append({
                    "worker_id":f"{tf}-{scope}-{bucket:03d}",
                    "timeframe":tf,"scope":scope,"bucket_count":count,"bucket_index":bucket,
                    "root_windows":windows,
                })
    if not workers and inv.get("all_observed_root_windows"):
        raise RuntimeError("2024 PA7 inventory has roots but frozen policy produced no workers")
    plan={
        "format_version":1,"status":"PASS","scope":"GROUP8_V3_PA7_2024_OOS_PLAN",
        "year":YEAR,"symbol":symbol,"freeze_manifest_hash":freeze["manifest_hash"],
        "validated_commit":freeze["validated_commit"],"oos_tooling_commit":freeze["oos_tooling_commit"],
        "pa7_2023_release_report_hash":freeze["pa7_2023_release_report_hash"],
        "pa7_2023_sizing_report_hash":freeze["pa7_2023_sizing_report_hash"],
        "frozen_bucket_policy":policy,"root_window_inventory":inv,
        "worker_count":len(workers),"expected_shard_count":expected_shards,"workers":workers,
        "bucket_counts_fixed_from_2023":True,"oos_conditioned_bucket_changes":False,
        "observed_2024_values_used_for_tuning":False,
        "free_only":True,"paid_runner_allowed":False,"paid_service_allowed":False,
    }
    plan["plan_hash"]=stable_hash(plan);_atomic(output,plan);return plan


def run_worker(
    *,plan_path:Path,worker_id:str,staging_db:Path,artifacts_root:Path,freeze_path:Path,
    worker_root:Path,report_path:Path,
)->dict[str,Any]:
    freeze=verify_freeze(artifacts_root,freeze_path)
    plan=json.loads(plan_path.read_text());_verify(plan,"plan_hash","PA7 OOS plan")
    if plan.get("status")!="PASS" or int(plan.get("year",0))!=YEAR:raise RuntimeError("invalid PA7 OOS plan")
    if plan.get("freeze_manifest_hash")!=freeze["manifest_hash"]:raise RuntimeError("PA7 plan/freeze lineage drift")
    hits=[x for x in plan["workers"] if x["worker_id"]==worker_id]
    if len(hits)!=1:raise RuntimeError(f"PA7 worker not uniquely planned:{worker_id}")
    spec=hits[0]
    if int(spec["bucket_count"])!=_policy(freeze,spec["timeframe"],spec["scope"]):
        raise RuntimeError("PA7 worker bucket policy drift")
    worker_root.mkdir(parents=True,exist_ok=True)
    result=run_onepass_bucket(
        staging_db=staging_db,work_db=worker_root/"work.sqlite",output_dir=worker_root/"payload",
        artifacts_root=artifacts_root,year=YEAR,symbol=plan["symbol"],timeframe=spec["timeframe"],
        root_months=list(spec["root_windows"]),bucket_count=int(spec["bucket_count"]),
        bucket_index=int(spec["bucket_index"]),boundary_scope=spec["scope"],oos_freeze=freeze_path,
    )
    if result.get("status")!="PASS" or result.get("oos_freeze_manifest_hash")!=freeze["manifest_hash"]:
        raise RuntimeError("PA7 OOS worker not freeze-bound PASS")
    if list(result.get("root_months") or [])!=list(spec["root_windows"]):
        raise RuntimeError("PA7 OOS worker root-window coverage drift")
    for shard in result["shards"]:
        mp=Path(shard["manifest"]);db=Path(shard["database"])
        manifest=json.loads(mp.read_text());_verify(manifest,"manifest_hash",f"PA7 shard {mp.name}")
        if int(manifest.get("year",0))!=YEAR or manifest.get("oos_2024_accessed") is not True:
            raise RuntimeError(f"PA7 OOS shard year/OOS drift:{mp}")
        if int(manifest["file_size_bytes"])>HARD_GUARD_BYTES:
            raise RuntimeError(f"PA7 OOS shard exceeds frozen hard guard:{mp}:{manifest['file_size_bytes']}")
        if not db.is_file() or db.stat().st_size!=int(manifest["file_size_bytes"]) or sha256_file(db)!=manifest["sha256"]:
            raise RuntimeError(f"PA7 OOS shard physical identity mismatch:{db}")
    rec={
        "format_version":1,"status":"PASS","scope":"GROUP8_V3_PA7_2024_OOS_WORKER",
        "year":YEAR,"worker_id":worker_id,"plan_hash":plan["plan_hash"],
        "freeze_manifest_hash":freeze["manifest_hash"],"spec":spec,"result":result,
        "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":True,
    }
    rec["report_hash"]=stable_hash(rec);_atomic(report_path,rec);return rec


def finalize_release(
    *,plan_path:Path,freeze_path:Path,artifacts_root:Path,worker_report_paths:list[Path],output:Path,
)->dict[str,Any]:
    freeze=verify_freeze(artifacts_root,freeze_path)
    plan=json.loads(plan_path.read_text());_verify(plan,"plan_hash","PA7 OOS plan")
    if plan.get("freeze_manifest_hash")!=freeze["manifest_hash"]:raise RuntimeError("PA7 release plan/freeze drift")
    expected={str(w["worker_id"]):w for w in plan["workers"]}
    reports=[]
    for p in worker_report_paths:
        r=json.loads(p.read_text());_verify(r,"report_hash",p.name);reports.append(r)
    actual={str(r.get("worker_id")):r for r in reports}
    if len(actual)!=len(reports):raise RuntimeError("duplicate PA7 OOS worker report")
    if set(actual)!=set(expected):raise RuntimeError(f"PA7 OOS worker coverage mismatch:{len(actual)}!={len(expected)}")
    expected_keys=set()
    for w in expected.values():
        for month in w["root_windows"]:
            expected_keys.add((w["timeframe"],w["scope"],month,int(w["bucket_index"]),int(w["bucket_count"])))
    seen={};defs=Counter();raw=candidates=states=0
    for wid,r in sorted(actual.items()):
        if r.get("status")!="PASS" or int(r.get("year",0))!=YEAR or r.get("plan_hash")!=plan["plan_hash"] or r.get("freeze_manifest_hash")!=freeze["manifest_hash"]:
            raise RuntimeError(f"invalid PA7 OOS worker receipt:{wid}")
        if r.get("free_only") is not True or r.get("paid_runner_used") or r.get("paid_service_used") or r.get("oos_2024_accessed") is not True:
            raise RuntimeError(f"PA7 OOS worker policy failure:{wid}")
        w=expected[wid]
        if r.get("spec")!=w:raise RuntimeError(f"PA7 OOS worker spec drift:{wid}")
        for s in r["result"]["shards"]:
            mp=Path(s["manifest"]);db=Path(s["database"])
            m=json.loads(mp.read_text());_verify(m,"manifest_hash",mp.name)
            if int(m.get("year",0))!=YEAR or m.get("oos_2024_accessed") is not True:raise RuntimeError(f"invalid PA7 OOS shard metadata:{mp}")
            if int(m.get("file_size_bytes",-1))>HARD_GUARD_BYTES:raise RuntimeError(f"PA7 OOS shard exceeds frozen hard guard:{mp}")
            if not db.is_file() or db.stat().st_size!=int(m.get("file_size_bytes",-1)) or sha256_file(db)!=m.get("sha256"):raise RuntimeError(f"PA7 OOS shard final identity mismatch:{db}")
            key=(str(m["timeframe"]),str(m["boundary_scope"]),str(m["causal_root_window"]),int(m["bucket_index"]),int(m["bucket_count"]))
            if key in seen:raise RuntimeError(f"duplicate PA7 OOS shard key:{key}")
            if key not in expected_keys:raise RuntimeError(f"unexpected PA7 OOS shard key:{key}")
            seen[key]={
                "timeframe":key[0],"scope":key[1],"root_window":key[2],"bucket_index":key[3],"bucket_count":key[4],
                "shard_id":m["shard_id"],"database":s["database"],"manifest":s["manifest"],
                "file_size_bytes":int(m["file_size_bytes"]),"sha256":m["sha256"],"manifest_hash":m["manifest_hash"],
                "table_row_counts":m["table_row_counts"],"table_logical_sha256":m["table_logical_sha256"],
                "definition_coverage":m["definition_coverage"],
            }
            raw+=int(m["file_size_bytes"]);candidates+=int(m["table_row_counts"].get("price_action_pattern_candidate",0));states+=int(m["table_row_counts"].get("price_action_pattern_state",0));defs.update({k:int(v) for k,v in m["definition_coverage"].items()})
    if set(seen)!=expected_keys:raise RuntimeError(f"PA7 OOS shard coverage mismatch:{len(seen)}!={len(expected_keys)}")
    shards=[seen[k] for k in sorted(seen)]
    rec={
        "format_version":1,"status":"PASS","artifact_kind":"GROUP8_PA7_ANNUAL_2024_OOS_SHARDED_RELEASE",
        "year":YEAR,"symbol":plan["symbol"],"oos":True,"plan_hash":plan["plan_hash"],
        "freeze_manifest_hash":freeze["manifest_hash"],"validated_commit":freeze["validated_commit"],
        "oos_tooling_commit":freeze["oos_tooling_commit"],"worker_count":len(reports),
        "shard_count":len(shards),"expected_shard_count":len(expected_keys),"raw_shard_bytes":raw,
        "candidate_rows":candidates,"state_rows":states,"definition_coverage":dict(sorted(defs.items())),
        "bucket_policy":dict(freeze["pa7_bucket_policy_by_timeframe_scope"]),
        "root_window_inventory_report_hash":plan["root_window_inventory"]["report_hash"],
        "pa7_2023_release_report_hash":freeze["pa7_2023_release_report_hash"],
        "pa7_2023_sizing_report_hash":freeze["pa7_2023_sizing_report_hash"],
        "shards":shards,"complete_once_only_coverage":True,
        "bucket_counts_fixed_from_2023":True,"oos_conditioned_bucket_changes":False,
        "observed_2024_values_used_for_tuning":False,
        "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":True,
    }
    rec["report_hash"]=stable_hash(rec);_atomic(output,rec);return rec


def main()->int:
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("plan");a.add_argument("--staging-db",type=Path,required=True);a.add_argument("--artifacts-root",type=Path,required=True);a.add_argument("--freeze",type=Path,required=True);a.add_argument("--symbol",required=True);a.add_argument("--output",type=Path,required=True)
    b=sub.add_parser("worker");b.add_argument("--plan",type=Path,required=True);b.add_argument("--worker-id",required=True);b.add_argument("--staging-db",type=Path,required=True);b.add_argument("--artifacts-root",type=Path,required=True);b.add_argument("--freeze",type=Path,required=True);b.add_argument("--worker-root",type=Path,required=True);b.add_argument("--report",type=Path,required=True)
    c=sub.add_parser("finalize");c.add_argument("--plan",type=Path,required=True);c.add_argument("--artifacts-root",type=Path,required=True);c.add_argument("--freeze",type=Path,required=True);c.add_argument("--worker-report",type=Path,action="append",required=True);c.add_argument("--output",type=Path,required=True)
    x=p.parse_args()
    if x.cmd=="plan":r=build_plan(staging_db=x.staging_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),symbol=x.symbol,output=x.output.resolve())
    elif x.cmd=="worker":r=run_worker(plan_path=x.plan.resolve(),worker_id=x.worker_id,staging_db=x.staging_db.resolve(),artifacts_root=x.artifacts_root.resolve(),freeze_path=x.freeze.resolve(),worker_root=x.worker_root.resolve(),report_path=x.report.resolve())
    else:r=finalize_release(plan_path=x.plan.resolve(),freeze_path=x.freeze.resolve(),artifacts_root=x.artifacts_root.resolve(),worker_report_paths=[p.resolve() for p in x.worker_report],output=x.output.resolve())
    print(json.dumps(r,indent=2,sort_keys=True));return 0


if __name__=="__main__":
    raise SystemExit(main())
