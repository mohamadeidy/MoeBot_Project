#!/usr/bin/env python3
"""Frozen 2024 OOS Stage0-5 runner for Group8 V3.

Runs only after a valid V3 OOS freeze. It uses the unchanged AnnualCoreEngine
methods for stages 0-5 and never executes Stage6/7. Resume requires the exact
preceding persistent checkpoint.
"""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
from typing import Any

from group8_annual_core_driver import AnnualCoreEngine
from group8_postprocess_v0_8_0 import checkpoint
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

STAGES=(("load_bars","load_bars"),("base_price_action","process_base_price_action"),("dow","process_dow"),("bounded_ranges","process_bounded_ranges"),("context_rejections_fast","process_context_rejections_fast"),("structural_narratives_fast","process_structural_narratives_fast"))

def _verify(rec:dict[str,Any],field:str)->None:
 x=dict(rec);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{field} mismatch")

def _head(root:Path)->str:
 repo=root.resolve().parent.parent
 return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()

def verify_freeze(root:Path,freeze_path:Path)->dict[str,Any]:
 f=json.loads(freeze_path.read_text());_verify(f,"manifest_hash")
 if f.get("status")!="FROZEN_FOR_2024_OOS_V3" or f.get("authorization",{}).get("2024_oos") is not True:raise RuntimeError("2024 OOS not frozen/authorized")
 if f.get("oos_2024_accessed_during_freeze") is not False:raise RuntimeError("freeze was not 2024-data-blind")
 if _head(root)!=f.get("oos_tooling_commit"):raise RuntimeError("Git HEAD drift after OOS freeze")
 for rel,rec in f.get("identities",{}).items():
  p=root/rel
  if not p.is_file() or p.stat().st_size!=int(rec["size_bytes"]) or sha256_file(p)!=rec["sha256"]:raise RuntimeError(f"frozen identity drift:{rel}")
 return f

def _complete(e:AnnualCoreEngine,stage:str)->bool:
 expected={(s,tf) for s,tf in e.bars_by_tf}
 got={(str(r[0]),str(r[1])) for r in e.out.execute("SELECT symbol,timeframe FROM processing_checkpoint WHERE stage=? AND status='PASS'",(stage,))}
 return got==expected

def run(*,staging_db:Path,output_db:Path,artifacts_root:Path,freeze_path:Path,symbol:str,start:int,end:int)->dict[str,Any]:
 if not (0<=start<=end<=5):raise ValueError("OOS Stage5 runner permits only stages 0..5")
 freeze=verify_freeze(artifacts_root,freeze_path)
 e=AnnualCoreEngine(staging_db=staging_db,output_db=output_db,artifacts_root=artifacts_root,year=2024,symbol=symbol)
 try:
  e.load_bars()
  if start>0 and not _complete(e,STAGES[start-1][0]):raise RuntimeError(f"missing preceding checkpoint:{STAGES[start-1][0]}")
  executed=[]
  for idx in range(start,end+1):
   stage,method=STAGES[idx]
   if _complete(e,stage):
    executed.append(stage+":already_pass");continue
   if idx==0:checkpoint(e,stage)
   else:getattr(e,method)();checkpoint(e,stage)
   executed.append(stage)
  for idx in range(0,end+1):
   if not _complete(e,STAGES[idx][0]):raise RuntimeError(f"incomplete checkpoint:{STAGES[idx][0]}")
  return {"format_version":1,"status":"PASS","year":2024,"oos":True,"stage_start":start,"stage_end":end,"stage_names":executed,"stage5_complete":end==5,"freeze_manifest_hash":freeze["manifest_hash"],"validated_commit":freeze["validated_commit"],"oos_tooling_commit":freeze["oos_tooling_commit"],"stage5_database_sha256":sha256_file(output_db),"read_only_upstream":True,"frozen_semantics":True}
 finally:e.close()

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--output-db",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--freeze",type=Path,required=True);p.add_argument("--symbol",required=True);p.add_argument("--start",type=int,required=True);p.add_argument("--end",type=int,required=True);p.add_argument("--report",type=Path,required=True)
 a=p.parse_args();r=run(staging_db=a.staging_db.resolve(),output_db=a.output_db.resolve(),artifacts_root=a.artifacts_root.resolve(),freeze_path=a.freeze.resolve(),symbol=a.symbol,start=a.start,end=a.end);r["report_hash"]=stable_hash(r);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
