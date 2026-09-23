#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def load(path:Path):
    r=json.loads(path.read_text())
    for f in ("report_hash","manifest_hash","closure_hash","contract_hash"):
        if f in r:
            x=dict(r);saved=str(x.pop(f))
            if stable(x)!=saved: raise RuntimeError(f"{path.name}:{f}_mismatch")
            break
    return r
def status_pass(r): return r.get("status") in {"PASS","FROZEN","OFFICIALLY_CLOSED","OFFICIALLY_CLOSED_V3"} or r.get("officially_closed") is True

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--group-dir",type=Path,required=True)
    p.add_argument("--predecessor",type=Path,required=True)
    p.add_argument("--sizing-report",type=Path,required=True)
    p.add_argument("--resource-report",type=Path,required=True)
    p.add_argument("--checkpoint3",type=Path)
    p.add_argument("--holdout-plan",type=Path)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    group=int(a.group_dir.name.split("_")[-1])
    failures=[]
    plan=json.loads((a.group_dir/"PREPARATION_PLAN.json").read_text())
    defs=json.loads((a.group_dir/"01_DEFINITION_REGISTRY_DRAFT.json").read_text())
    pred=load(a.predecessor);size=load(a.sizing_report);resource=load(a.resource_report)
    if not status_pass(pred): failures.append("predecessor_gate_not_pass")
    if defs.get("status")!="FROZEN": failures.append("definitions_not_frozen")
    if plan.get("status")!="FROZEN": failures.append("preparation_plan_not_frozen")
    if size.get("status")!="PASS": failures.append("sizing_not_pass")
    if resource.get("status")!="PASS": failures.append("resource_gate_not_pass")
    if group==9:
        if not a.checkpoint3 or not a.checkpoint3.is_file(): failures.append("group8_checkpoint3_missing")
        else:
            cp=load(a.checkpoint3)
            if cp.get("status")!="PASS" or cp.get("checkpoint") not in (3,"3","CHECKPOINT_3"):
                failures.append("group8_checkpoint3_not_pass")
    if group==14:
        if not a.holdout_plan or not a.holdout_plan.is_file(): failures.append("final_holdout_plan_missing")
        else:
            hp=load(a.holdout_plan)
            if hp.get("status")!="FROZEN" or hp.get("untouched") is not True:
                failures.append("final_holdout_not_frozen_untouched")
    out={"format_version":1,"group":group,"status":"PASS" if not failures else "BLOCKED",
         "failures":failures,"real_execution_authorized":not failures,
         "plan_hash":stable(plan),"definition_hash":stable(defs)}
    out["report_hash"]=stable(out)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps(out,indent=2,sort_keys=True))
    return 0 if not failures else 2
if __name__=="__main__": raise SystemExit(main())
