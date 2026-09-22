#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

COMPONENTS=("context","location","liquidity","displacement","structure","poi","retracement","confirmation")
def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def load_hash(path:Path):
    r=json.loads(path.read_text())
    for f in ("closure_hash","manifest_hash","report_hash"):
        if f in r:
            x=dict(r);s=str(x.pop(f))
            if stable(x)!=s: raise RuntimeError(f"{path.name}:{f}_mismatch")
            return r
    raise RuntimeError(f"{path.name}:no_self_hash")

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--group8-closure",type=Path,required=True)
    p.add_argument("--checkpoint3",type=Path,required=True)
    p.add_argument("--handoff",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    closure=load_hash(a.group8_closure);cp=load_hash(a.checkpoint3);handoff=load_hash(a.handoff)
    failures=[]
    if closure.get("officially_closed") is not True and closure.get("status") not in {"OFFICIALLY_CLOSED","OFFICIALLY_CLOSED_V3"}:
        failures.append("group8_not_officially_closed")
    if cp.get("status")!="PASS" or cp.get("checkpoint") not in (3,"3","CHECKPOINT_3"):
        failures.append("group8_checkpoint3_not_pass")
    if handoff.get("source_group")!=8 or handoff.get("target_group") not in (9,"9",None):
        failures.append("group8_handoff_wrong_target")
    if handoff.get("consumption_policy",{}).get("read_only") is not True:
        failures.append("group8_handoff_not_read_only")
    report={"format_version":1,"status":"PASS" if not failures else "BLOCKED","group":9,"failures":failures,
            "real_execution_authorized":not failures,"required_components":list(COMPONENTS),
            "semantic_freeze_authorized":False,
            "note":"PASS authorizes Group 9 dependency intake/sizing only; exact Group 9 semantic freeze remains a separate review gate."}
    report["report_hash"]=stable(report)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if not failures else 2
if __name__=="__main__":raise SystemExit(main())
