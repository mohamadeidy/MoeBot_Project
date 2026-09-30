#!/usr/bin/env python3
"""Generic resumable orchestrator for prepared Groups 9-15.

It deliberately contains no trading semantics. A frozen group registers a stage command
template in EXECUTION_COMMAND.json. This orchestrator handles checkpoints, fail-closed
preflight, deterministic shard ordering, and resume.
"""
from __future__ import annotations
import argparse, json, subprocess, time
from pathlib import Path

def atomic(path:Path,v):
    t=path.with_suffix(path.suffix+".tmp");t.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n");t.replace(path)

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--group-dir",type=Path,required=True)
    p.add_argument("--plan",type=Path,required=True)
    p.add_argument("--preflight",type=Path,required=True)
    p.add_argument("--work-root",type=Path,required=True)
    p.add_argument("--python",default="python")
    a=p.parse_args();group=int(a.group_dir.name.split("_")[-1])
    pf=json.loads(a.preflight.read_text())
    if pf.get("status")!="PASS" or pf.get("real_execution_authorized") is not True:
        raise SystemExit("preflight does not authorize real execution")
    plan=json.loads(a.plan.read_text())
    cmd_path=a.group_dir/"EXECUTION_COMMAND.json"
    if not cmd_path.is_file(): raise SystemExit("EXECUTION_COMMAND.json missing; semantics executor not frozen")
    cfg=json.loads(cmd_path.read_text())
    if cfg.get("status")!="FROZEN": raise SystemExit("execution command not frozen")
    a.work_root.mkdir(parents=True,exist_ok=True);cp=a.work_root/"progress.json"
    state={"group":group,"status":"RUNNING","completed":[],"failed":[],"total":len(plan["shards"]),"started_unix":time.time()}
    if cp.is_file():
        old=json.loads(cp.read_text());state["completed"]=old.get("completed",[]);state["started_unix"]=old.get("started_unix",state["started_unix"])
    done=set(state["completed"])
    for shard in plan["shards"]:
        sid=shard["shard_id"]
        if sid in done:continue
        args=[a.python,str(a.group_dir/cfg["entrypoint"])]
        for token in cfg["args_template"]:
            args.append(token.format(shard_id=sid,bucket_index=shard["bucket_index"],bucket_count=shard["bucket_count"],
                                     work_root=str(a.work_root),plan=str(a.plan)))
        r=subprocess.run(args)
        if r.returncode:
            state["status"]="FAILED";state["failed"].append({"shard_id":sid,"returncode":r.returncode});atomic(cp,state);return r.returncode
        state["completed"].append(sid);atomic(cp,state)
    state["status"]="SHARDS_COMPLETE";state["finished_unix"]=time.time();atomic(cp,state)
    print(json.dumps(state,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
