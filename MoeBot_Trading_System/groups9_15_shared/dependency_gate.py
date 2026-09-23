#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def stable(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def load_hashed(path:Path, fields=("closure_hash","manifest_hash","report_hash")):
    r=json.loads(path.read_text())
    for field in fields:
        if field in r:
            x=dict(r);saved=str(x.pop(field))
            if stable(x)!=saved: raise RuntimeError(f"{path.name}:{field}_mismatch")
            break
    return r

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--group",type=int,choices=range(9,16),required=True)
    p.add_argument("--predecessor-closure",type=Path,required=True)
    p.add_argument("--checkpoint3",type=Path)
    p.add_argument("--holdout-plan",type=Path)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    pred=load_hashed(a.predecessor_closure)
    failures=[]
    if pred.get("officially_closed") is not True and pred.get("status") not in {"OFFICIALLY_CLOSED","OFFICIALLY_CLOSED_V3"}:
        failures.append("predecessor_not_officially_closed")
    if a.group==9:
        if a.checkpoint3 is None or not a.checkpoint3.is_file():
            failures.append("group8_checkpoint3_missing")
        else:
            cp=load_hashed(a.checkpoint3)
            if cp.get("status")!="PASS" or cp.get("checkpoint") not in (3,"3","CHECKPOINT_3"):
                failures.append("group8_checkpoint3_not_pass")
    if a.group==14:
        if a.holdout_plan is None or not a.holdout_plan.is_file():
            failures.append("final_untouched_holdout_plan_missing")
        else:
            hp=load_hashed(a.holdout_plan)
            if hp.get("status")!="FROZEN" or hp.get("untouched") is not True:
                failures.append("final_holdout_plan_not_frozen_untouched")
    report={"format_version":1,"group":a.group,"status":"PASS" if not failures else "BLOCKED","failures":failures,"real_execution_authorized":not failures}
    report["report_hash"]=stable(report)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if not failures else 2

if __name__=="__main__":raise SystemExit(main())
