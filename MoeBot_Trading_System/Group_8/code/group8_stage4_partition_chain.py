#!/usr/bin/env python3
"""Execute an ordered contiguous stage-4 partition range on one verified DB."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, time
from pathlib import Path
from group8_segmented_annual_core import run_segment
from group8_context_rejection_fastpath import IndexedContextRejectionEngine
from moebot_group8_engine_v0_8_0 import stable_hash

def sha256_file(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(16*1024*1024),b""):h.update(chunk)
 return h.hexdigest()

def integrity(path:Path)->str:
 con=sqlite3.connect(path)
 try:return str(con.execute("PRAGMA integrity_check").fetchone()[0])
 finally:con.close()

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--database",type=Path,required=True)
 p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--start-partition",type=int,required=True);p.add_argument("--end-partition",type=int,required=True)
 p.add_argument("--report-dir",type=Path,required=True);p.add_argument("--manifest",type=Path,required=True);a=p.parse_args()
 if not (0<=a.start_partition<=a.end_partition<24):raise ValueError("invalid partition range")
 if integrity(a.database)!="ok":raise RuntimeError("input SQLite integrity failure")
 plan=IndexedContextRejectionEngine.stage4_partition_plan();timings=[];receipts=[]
 for i in range(a.start_partition,a.end_partition+1):
  started=time.monotonic();report=a.report_dir/f"partition_{i:02d}.json"
  result=run_segment(staging_db=a.staging_db.resolve(),output_db=a.database.resolve(),artifacts_root=a.artifacts_root.resolve(),year=2023,symbol="XAUUSD_",start=4,end=4,stage4_partition=i)
  elapsed=time.monotonic()-started;report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
  timings.append({"partition":i,"seconds":elapsed});receipts.append(result["receipt"])
 if integrity(a.database)!="ok":raise RuntimeError("output SQLite integrity failure")
 payload={"status":"PASS","role":"STAGE4_PARTITION_CHAIN","plan":plan,"start_partition":a.start_partition,"end_partition":a.end_partition,
  "timings":timings,"worst_partition_seconds":max(x["seconds"] for x in timings),"database_filename":a.database.name,
  "database_size_bytes":a.database.stat().st_size,"database_sha256":sha256_file(a.database),"receipts":receipts,
  "checkpoint_3_published":False,"oos_2024_accessed":False,"free_only":True}
 payload["manifest_hash"]=stable_hash(payload);a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
 print(json.dumps(payload,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
