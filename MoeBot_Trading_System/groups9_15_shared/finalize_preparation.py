#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

REQ_SHARED=[
 "GROUPS_9_15_PREPARATION_ARCHITECTURE.md","GROUPS_9_15_SHARED_CONTRACT.json",
 "GROUPS_9_15_SHARD_FORMAT_CONTRACT_DRAFT.json","groups9_15_shared/group_sizing.py",
 "groups9_15_shared/group_preflight.py","groups9_15_shared/group_shard_planner.py",
 "groups9_15_shared/group_executor.py","groups9_15_shared/group_union_validator.py",
 "groups9_15_shared/group_handoff.py","groups9_15_shared/shard_runtime.py","groups9_15_shared/manifest_catalog.py"
]
REQ_GROUP=["README.md","STATUS.json","PREPARATION_PLAN.json","01_DEFINITION_REGISTRY_DRAFT.json","02_SCHEMA_DRAFT.sql",
           "UPSTREAM_INPUT_CONTRACT_DRAFT.json","DOWNSTREAM_HANDOFF_CONTRACT_DRAFT.json"]

def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 root=a.root;fail=[];groups={}
 for rel in REQ_SHARED:
  if not (root/rel).is_file():fail.append("missing_shared:"+rel)
 for g in range(9,16):
  gd=root/f"Group_{g}";gf=[]
  for rel in REQ_GROUP:
   if not (gd/rel).is_file():gf.append("missing:"+rel)
  if not gf:
   st=json.loads((gd/"STATUS.json").read_text());plan=json.loads((gd/"PREPARATION_PLAN.json").read_text());defs=json.loads((gd/"01_DEFINITION_REGISTRY_DRAFT.json").read_text())
   if st.get("real_execution_authorized") is not False:gf.append("real_execution_must_remain_blocked")
   if plan.get("status")!="DRAFT_PREPARATION":gf.append("unexpected_plan_status")
   if defs.get("status")!="DRAFT_NOT_FROZEN":gf.append("unexpected_definition_status")
   try:
    con=sqlite3.connect(":memory:");con.executescript((gd/"02_SCHEMA_DRAFT.sql").read_text());con.close()
   except Exception as e:gf.append("schema_compile:"+str(e))
  groups[str(g)]={"status":"PASS_PREPARATION_ONLY" if not gf else "FAIL","failures":gf,
                  "real_execution_authorized":False,"remaining_gate":"predecessor closure + semantic freeze + real sizing/resource PASS"}
  fail.extend(f"group{g}:{x}" for x in gf)
 out={"format_version":1,"scope":"GROUPS_9_15_PREPARATION_FINALIZER","status":"PASS_PREPARATION_ONLY" if not fail else "FAIL",
      "failures":fail,"groups":groups,"real_execution_authorized":False,
      "meaning":"PASS_PREPARATION_ONLY confirms infrastructure/contracts/schemas are prepared; it does not authorize any Group 9-15 real-data execution."}
 out["report_hash"]=stable(out);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");print(json.dumps(out,indent=2,sort_keys=True));return 0 if not fail else 2
if __name__=="__main__":raise SystemExit(main())
