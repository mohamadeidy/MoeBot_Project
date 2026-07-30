#!/usr/bin/env python3
"""Conservative independent full-data benchmark for one stage-4 partition."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, time
from pathlib import Path
from group8_annual_core_driver import AnnualCoreEngine
from group8_stage4_partition_regression import _filtered_process
from group8_context_rejection_fastpath import STAGE4_PARTITION_COUNT

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for c in iter(lambda:f.read(16*1024*1024),b""):h.update(c)
 return h.hexdigest()

def run(staging:Path,db:Path,root:Path,partition:int,empty:bool)->float:
 e=AnnualCoreEngine(staging_db=staging,output_db=db,artifacts_root=root,year=2023,symbol="XAUUSD_")
 try:
  e.load_bars();started=time.monotonic()
  if empty:_filtered_process(e,None,set())
  else:e.process_context_rejections_fast(partition_index=partition)
  e.out.commit();return time.monotonic()-started
 finally:e.close()

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--checkpoint2-db",type=Path,required=True)
 p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--partition",type=int,required=True);p.add_argument("--work-dir",type=Path,required=True);p.add_argument("--report",type=Path,required=True);a=p.parse_args()
 if not 0<=a.partition<STAGE4_PARTITION_COUNT:raise ValueError("invalid partition")
 a.work_dir.mkdir(parents=True,exist_ok=True);baseline=a.work_dir/"baseline.sqlite";actual=a.work_dir/"actual.sqlite"
 shutil.copy2(a.checkpoint2_db,baseline);shutil.copy2(a.checkpoint2_db,actual)
 rebuild=run(a.staging_db,baseline,a.artifacts_root,a.partition,True);total=run(a.staging_db,actual,a.artifacts_root,a.partition,False)
 commit_started=time.monotonic();con=sqlite3.connect(actual);con.execute("PRAGMA optimize");con.commit();ok=con.execute("PRAGMA integrity_check").fetchone()[0];con.close();commit_seconds=time.monotonic()-commit_started
 hash_started=time.monotonic();digest=sha(actual);hash_seconds=time.monotonic()-hash_started
 report={"status":"PASS","partition":a.partition,"partition_count":STAGE4_PARTITION_COUNT,"context_index_rebuild_seconds":rebuild,
  "total_execution_seconds":total,"candidate_execution_seconds_lower_bound":max(0.0,total-rebuild),"commit_integrity_seconds":commit_seconds,
  "hash_seconds":hash_seconds,"database_size_bytes":actual.stat().st_size,"database_sha256":digest,"sqlite_integrity":ok,
  "safety_limit_seconds":10800,"safety_pass":total<10800,"oos_2024_accessed":False,"free_only":True}
 if ok!="ok" or not report["safety_pass"]:raise RuntimeError(f"benchmark safety failure:{report}")
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");print(json.dumps(report,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
