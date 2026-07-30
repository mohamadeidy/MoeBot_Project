#!/usr/bin/env python3
"""Publish/verify an exact resumable per-partition stage-4 release chain."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, subprocess, time
from pathlib import Path
from group8_segmented_annual_core import run_segment
from group8_context_rejection_fastpath import IndexedContextRejectionEngine
from moebot_group8_engine_v0_8_0 import stable_hash

def sh(*args:str,capture:bool=False)->str:
 r=subprocess.run(args,check=True,text=True,capture_output=capture)
 return r.stdout.strip() if capture else ""

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for c in iter(lambda:f.read(16*1024*1024),b""):h.update(c)
 return h.hexdigest()

def self_hash_ok(m:dict)->str:
 key="report_hash" if "report_hash" in m else "manifest_hash";saved=m[key];q=dict(m);q.pop(key)
 if stable_hash(q)!=saved:raise RuntimeError(f"manifest self-hash mismatch:{m.get('partition_index','checkpoint2')}")
 return saved

def integrity(path:Path)->None:
 con=sqlite3.connect(path)
 try:
  if str(con.execute("PRAGMA integrity_check").fetchone()[0])!="ok":raise RuntimeError("SQLite integrity failure")
 finally:con.close()

def assets(repo:str,tag:str)->set[str]:
 raw=sh("gh","release","view",tag,"--repo",repo,"--json","assets",capture=True)
 return {x["name"] for x in json.loads(raw)["assets"]}

def prefix(index:int)->str:return "checkpoint2" if index<0 else f"stage4p{index:02d}"

def download(repo:str,tag:str,index:int,dest:Path)->tuple[Path,dict,str]:
 p=prefix(index);dest.mkdir(parents=True,exist_ok=True)
 sh("gh","release","download",tag,"--repo",repo,"--pattern",f"{p}.*","--dir",str(dest),"--clobber")
 manifest_path=dest/f"{p}.json";m=json.loads(manifest_path.read_text());mh=self_hash_ok(m)
 parts=sorted(dest.glob(f"{p}.sqlite.zst.part-*"));expected=m["parts"]
 if [x.name for x in parts]!=[x["filename"] for x in expected]:raise RuntimeError(f"part filename mismatch:{p}")
 for f,x in zip(parts,expected):
  if f.stat().st_size!=x["size_bytes"] or sha(f)!=x["sha256"]:raise RuntimeError(f"part verification failure:{f.name}")
 z=dest/f"{p}.sqlite.zst"
 with z.open("wb") as out:
  for f in parts:
   with f.open("rb") as src:shutil.copyfileobj(src,out)
 if z.stat().st_size!=m["compressed_size_bytes"] or sha(z)!=m["compressed_sha256"]:raise RuntimeError(f"compressed verification failure:{p}")
 db=dest/f"{p}.sqlite";sh("zstd","-q","-d","-f",str(z),"-o",str(db))
 if db.stat().st_size!=m["raw_size_bytes"] or sha(db)!=m["raw_sha256"]:raise RuntimeError(f"raw verification failure:{p}")
 integrity(db)
 if index>=0:
  plan=IndexedContextRejectionEngine.stage4_partition_plan()
  if m["partition_index"]!=index or m["plan"]["plan_hash"]!=plan["plan_hash"] or m.get("checkpoint_3_published") is not False:raise RuntimeError(f"partition manifest contract failure:{index}")
 return db,m,mh

def publish(repo:str,tag:str,index:int,db:Path,parent_hash:str,result:dict,work:Path,restore_seconds:float)->dict:
 p=prefix(index);z=work/f"{p}.sqlite.zst"
 t=time.monotonic();sh("zstd","-q","-3","-T0","-f",str(db),"-o",str(z));compress_seconds=time.monotonic()-t
 for old in work.glob(f"{p}.sqlite.zst.part-*"):old.unlink()
 sh("split","-b","1750000000","-d","-a","3",str(z),str(work/f"{p}.sqlite.zst.part-"))
 t=time.monotonic();raw_sha=sha(db);compressed_sha=sha(z);parts=[{"filename":f.name,"size_bytes":f.stat().st_size,"sha256":sha(f)} for f in sorted(work.glob(f"{p}.sqlite.zst.part-*"))];hash_seconds=time.monotonic()-t
 payload={"status":"PASS","role":"STAGE4_PARTITION_CHECKPOINT","year":2023,"partition_index":index,"plan":result["plan"],"receipt":result["receipt"],
  "source_manifest_hash":parent_hash,"github_head_sha":sh("git","rev-parse","HEAD",capture=True),"database_filename":f"{p}.sqlite",
  "raw_size_bytes":db.stat().st_size,"raw_sha256":raw_sha,"compressed_size_bytes":z.stat().st_size,"compressed_sha256":compressed_sha,
  "parts":parts,"restore_seconds":restore_seconds,"execution_report":result,"compress_seconds":compress_seconds,"hash_seconds":hash_seconds,
  "checkpoint_3_published":False,"oos_2024_accessed":False,"free_only":True}
 payload["manifest_hash"]=stable_hash(payload);mp=work/f"{p}.json";mp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
 t=time.monotonic();sh("gh","release","upload",tag,*[str(x) for x in sorted(work.glob(f"{p}.sqlite.zst.part-*"))],str(mp),"--repo",repo,"--clobber");upload_seconds=time.monotonic()-t
 payload["upload_seconds"]=upload_seconds
 q=dict(payload);q.pop("manifest_hash");payload["manifest_hash"]=stable_hash(q);mp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
 sh("gh","release","upload",tag,str(mp),"--repo",repo,"--clobber")
 verify=work/f"verify-{p}";download(repo,tag,index,verify)
 return payload

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument("--repo",required=True);ap.add_argument("--tag",required=True);ap.add_argument("--staging-db",type=Path,required=True)
 ap.add_argument("--artifacts-root",type=Path,required=True);ap.add_argument("--start",type=int,required=True);ap.add_argument("--end",type=int,required=True);ap.add_argument("--work-dir",type=Path,required=True);ap.add_argument("--summary",type=Path,required=True);a=ap.parse_args()
 if not 0<=a.start<=a.end<24:raise ValueError("invalid range")
 a.work_dir.mkdir(parents=True,exist_ok=True);names=assets(a.repo,a.tag);highest=a.start-1
 for i in range(a.start,a.end+1):
  if f"{prefix(i)}.json" in names:highest=i
  else:break
 restore_index=highest if highest>=a.start else a.start-1
 t=time.monotonic();db,parent,parent_hash=download(a.repo,a.tag,restore_index,a.work_dir/f"restore-{prefix(restore_index)}");restore_seconds=time.monotonic()-t
 core=a.work_dir/"core.sqlite";shutil.copy2(db,core);published=[]
 for i in range(highest+1,a.end+1):
  started=time.monotonic();result=run_segment(staging_db=a.staging_db.resolve(),output_db=core.resolve(),artifacts_root=a.artifacts_root.resolve(),year=2023,symbol="XAUUSD_",start=4,end=4,stage4_partition=i);execution_seconds=time.monotonic()-started
  result["execution_seconds"]=execution_seconds;manifest=publish(a.repo,a.tag,i,core,parent_hash,result,a.work_dir,restore_seconds if i==highest+1 else 0.0);parent_hash=manifest["manifest_hash"];published.append(manifest)
 summary={"status":"PASS","start":a.start,"end":a.end,"resumed_from":restore_index,"published_partitions":[x["partition_index"] for x in published],
  "final_manifest_hash":parent_hash,"worst_partition_total_seconds":max((x["execution_report"]["execution_seconds"]+x["compress_seconds"]+x["hash_seconds"]+x["upload_seconds"] for x in published),default=0.0),
  "oos_2024_accessed":False,"free_only":True}
 a.summary.parent.mkdir(parents=True,exist_ok=True);a.summary.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n");print(json.dumps(summary,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
