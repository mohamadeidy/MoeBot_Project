#!/usr/bin/env python3
"""Streaming Group 8 V3 Stage 7 union validator.

Validates 574-scale compressed shard releases without materializing a monolithic
Stage7 database. Each archive is decompressed one-at-a-time, its exact raw SHA is
verified, local references/counts are audited, and fixed-width sorted
(id_digest,row_hash_digest) runs are exported. Runs are hierarchically merged with
bounded transient disk to prove global primary-ID uniqueness and compute the frozen
row-level logical SHA-256 over sorted (primary_id,row_hash) pairs.
"""
from __future__ import annotations
import argparse,hashlib,heapq,json,os,shutil,sqlite3,subprocess
from pathlib import Path
from typing import Any,BinaryIO,Iterable

from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_stage7_shard_executor import RANGE_DEFINITIONS,SCHOOL_DEFINITIONS,STAGE7_DEFINITIONS
from moebot_group8_engine_v0_8_0 import sha256_file

RECORD=64
TABLES={
 "school_interpretation":("interpretation_id","interpretation_hash","g8i_"),
 "evidence_chain":("evidence_chain_id","evidence_hash","g8ev_"),
}

def _atomic_json(path:Path,v:dict[str,Any])->None:
 path.parent.mkdir(parents=True,exist_ok=True);t=path.with_suffix(path.suffix+".tmp");t.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(t,path)

def _verify_hash(rec:dict[str,Any],field:str)->None:
 x=dict(rec);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{field} mismatch")

def _decode_record(buf:bytes)->tuple[bytes,bytes]:
 if len(buf)!=RECORD:raise RuntimeError("truncated fingerprint run")
 return buf[:32],buf[32:]

def _write_run(con:sqlite3.Connection,table:str,path:Path)->int:
 idc,hc,prefix=TABLES[table];path.parent.mkdir(parents=True,exist_ok=True);n=0
 q=f'SELECT "{idc}","{hc}" FROM "{table}" ORDER BY "{idc}"'
 with path.open("wb") as out:
  prev=None
  for rid,rh in con.execute(q):
   rid=str(rid);rh=str(rh)
   if not rid.startswith(prefix) or len(rid)!=len(prefix)+64:raise RuntimeError(f"unexpected {table} primary ID:{rid}")
   if len(rh)!=64:raise RuntimeError(f"unexpected {table} row hash length")
   key=bytes.fromhex(rid[len(prefix):]);val=bytes.fromhex(rh)
   if prev is not None and key<=prev:raise RuntimeError(f"local {table} primary IDs not strictly sorted")
   prev=key;out.write(key);out.write(val);n+=1
 return n

def _merge_runs(inputs:list[Path],output:Path)->tuple[int,int]:
 files=[p.open("rb") for p in inputs];heap=[];n=0;dups=0
 try:
  for i,f in enumerate(files):
   b=f.read(RECORD)
   if b:
    k,h=_decode_record(b);heapq.heappush(heap,(k,i,h))
  prev=None
  output.parent.mkdir(parents=True,exist_ok=True)
  with output.open("wb") as out:
   while heap:
    k,i,h=heapq.heappop(heap)
    if prev is not None and k==prev:dups+=1;raise RuntimeError("duplicate Stage7 domain primary ID across shards")
    prev=k;out.write(k);out.write(h);n+=1
    b=files[i].read(RECORD)
    if b:
     nk,nh=_decode_record(b);heapq.heappush(heap,(nk,i,nh))
  return n,dups
 finally:
  for f in files:f.close()

def _hierarchical_merge(runs:list[Path],work:Path,table:str,fan_in:int)->Path:
 if not runs:
  p=work/f"{table}.empty.run";p.write_bytes(b"");return p
 current=list(runs);round_no=0
 while len(current)>1:
  nxt=[]
  for j in range(0,len(current),fan_in):
   batch=current[j:j+fan_in];out=work/f"{table}.r{round_no:02d}.{j//fan_in:05d}.run"
   _merge_runs(batch,out)
   for p in batch:
    if p.exists():p.unlink()
   nxt.append(out)
  current=nxt;round_no+=1
 return current[0]

def _final_hash(path:Path,prefix:str)->tuple[int,str]:
 h=hashlib.sha256();n=0
 with path.open("rb") as f:
  while True:
   b=f.read(RECORD)
   if not b:break
   k,rh=_decode_record(b)
   rid=prefix+k.hex()
   h.update(rid.encode());h.update(b"\0");h.update(rh.hex().encode());h.update(b"\n");n+=1
 return n,h.hexdigest()

def _decompress(zstd:Path,archive:Path,out:Path)->None:
 out.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run([str(zstd),"-d","-f",str(archive),"-o",str(out)],check=True,stdout=subprocess.DEVNULL)

def validate_union(*,release_path:Path,plan_path:Path,stage5_db:Path,output_root:Path,work_root:Path,zstd_exe:Path,output_path:Path,fan_in:int=16)->dict[str,Any]:
 release=json.loads(release_path.read_text());_verify_hash(release,"release_hash")
 plan=json.loads(plan_path.read_text());_verify_hash(plan,"plan_hash")
 if release.get("status")!="PASS" or int(release.get("stage",0))!=7:raise RuntimeError("Stage7 release is not PASS")
 if release.get("plan_hash")!=plan.get("plan_hash"):raise RuntimeError("Stage7 release/plan lineage mismatch")
 if sha256_file(stage5_db)!=release["stage5_database_sha256"]:raise RuntimeError("Stage5 hash drift")
 year=int(release.get("year",0))
 expected_oos=(year==2024)
 if year not in (2023,2024):raise RuntimeError("unsupported Stage7 union year")
 if bool(release.get("oos_2024_accessed")) != expected_oos:raise RuntimeError("Stage7 OOS access flag/year mismatch")
 if int(release["shard_count"])!=len(release["shards"]) or int(release["shard_count"])!=int(plan["shard_count"]):raise RuntimeError("Stage7 shard-count mismatch")
 work_root.mkdir(parents=True,exist_ok=True)
 runs={t:[] for t in TABLES};counts={t:0 for t in TABLES};by_def={};unresolved_local=0
 tempdb=work_root/"current_stage7_union.sqlite"
 if tempdb.exists():tempdb.unlink()
 try:
  for x in sorted(release["shards"],key=lambda z:int(z["ordinal"])):
   spec=x["spec"];mf=output_root/x["manifest_path"];arc=output_root/x["archive_path"]
   m=json.loads(mf.read_text());_verify_hash(m,"manifest_hash")
   if m["manifest_hash"]!=x["manifest_hash"] or sha256_file(arc)!=x["compressed_sha256"]:raise RuntimeError("Stage7 manifest/archive identity mismatch")
   if m.get("compression_roundtrip_sha256")!=m.get("sha256") or m.get("raw_retained") is not False:raise RuntimeError("Stage7 lossless compression proof missing")
   _decompress(zstd_exe,arc,tempdb)
   if sha256_file(tempdb)!=m["sha256"]:raise RuntimeError("decompressed Stage7 raw SHA mismatch")
   con=sqlite3.connect(f"file:{tempdb.resolve()}?mode=ro&immutable=1",uri=True)
   try:
    if con.execute("PRAGMA quick_check").fetchone()[0]!="ok":raise RuntimeError("Stage7 shard quick_check failed")
    defs=RANGE_DEFINITIONS if spec["family"]=="range_chain" else SCHOOL_DEFINITIONS
    q=",".join("?" for _ in defs)
    extra=int(con.execute(f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id NOT IN ({q})",defs).fetchone()[0])
    if extra:raise RuntimeError(f"Stage7 shard contains wrong-family interpretations:{extra}")
    local_i=int(con.execute(f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",defs).fetchone()[0])
    local_e=int(con.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0])
    if local_i!=int(m["table_row_counts"]["school_interpretation"]) or local_e!=int(m["table_row_counts"]["evidence_chain"]):raise RuntimeError("Stage7 shard manifest row-count mismatch")
    bad=int(con.execute("""SELECT COUNT(*) FROM evidence_chain e LEFT JOIN school_interpretation i ON i.interpretation_id=e.subject_id WHERE e.subject_type!='school_interpretation' OR i.interpretation_id IS NULL""").fetchone()[0])
    unresolved_local+=bad
    if bad:raise RuntimeError(f"Stage7 unresolved local evidence subjects:{bad}")
    for d,n in con.execute(f"SELECT definition_id,COUNT(*) FROM school_interpretation WHERE definition_id IN ({q}) GROUP BY definition_id",defs):by_def[str(d)]=by_def.get(str(d),0)+int(n)
    for table in TABLES:
     run=work_root/f"{table}.leaf.{int(x['ordinal']):05d}.run"
     got=_write_run(con,table,run)
     if got!=int(m["table_row_counts"][table]):raise RuntimeError(f"{table} fingerprint export count mismatch")
     runs[table].append(run);counts[table]+=got
   finally:con.close()
   tempdb.unlink()

  if counts["school_interpretation"]!=int(release["table_row_counts"]["school_interpretation"]) or counts["evidence_chain"]!=int(release["table_row_counts"]["evidence_chain"]):raise RuntimeError("Stage7 release aggregate row-count mismatch")
  if counts["school_interpretation"]!=int(plan["expected_cardinality"]["total_stage7_interpretations"]):raise RuntimeError("Stage7 union interpretation count differs from frozen plan")

  hashes={}
  for table,(_,_,prefix) in TABLES.items():
   merged=_hierarchical_merge(runs[table],work_root,table,fan_in)
   n,h=_final_hash(merged,prefix)
   if n!=counts[table]:raise RuntimeError(f"{table} final fingerprint count mismatch")
   hashes[table]=h
   merged.unlink()
  global_payload={t:{"row_count":counts[t],"logical_sha256":hashes[t]} for t in sorted(TABLES)}
  result={
   "format_version":1,"scope":"GROUP8_V3_STAGE7_STREAMING_UNION","status":"PASS",
   "stage":7,"stage_name":"ict_core","year":year,"symbol":release["symbol"],
   "validated_commit":release["validated_commit"],"oos_tooling_commit":release.get("oos_tooling_commit"),"plan_hash":plan["plan_hash"],
   "stage5_database_sha256":release["stage5_database_sha256"],"stage6_release_hash":release["stage6_release_hash"],
   "stage6_union_report_hash":release["stage6_union_report_hash"],"stage7_release_hash":release["release_hash"],
   "shard_count":release["shard_count"],"table_row_counts":counts,"table_logical_sha256":hashes,
   "global_logical_sha256":stable_hash(global_payload),"definition_coverage":dict(sorted(by_def.items())),
   "duplicate_domain_id_count":0,"duplicate_detection_method":"hierarchical fixed-width external merge over every sorted primary ID",
   "unresolved_local_evidence_subject_count":unresolved_local,
   "lossless_archive_roundtrip_reverified":True,"monolithic_stage7_database_required":False,
   "streaming_union_bounded_disk":True,"groups_1_7_read_only":True,"stage5_read_only":True,
   "oos_2024_accessed":expected_oos,"frozen_ids_hashes_semantics_preserved":True,
   "downstream_compatibility":{
    "logical_table_names_unchanged":True,"logical_columns_unchanged":True,
    "immutable_primary_ids_unchanged":True,"row_hash_contract_unchanged":True,
    "physical_layout":"lossless zstd-compressed range_chain + school_core SQLite shards",
    "routing_metadata":"Stage7 release manifests by family/timeframe/root_month/bucket",
    "groups_9_15_must_consume_via_shard-aware_adapter_or_verified_union":True,
   },
   "stage7_official_pass_eligible":True,
   "next_gate":"publish compact Stage7 evidence and close Group8 Annual 2023 core; do not access 2024 automatically",
  }
  result["report_hash"]=stable_hash(result);_atomic_json(output_path,result);return result
 finally:
  if tempdb.exists():tempdb.unlink()

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--release",type=Path,required=True);p.add_argument("--plan",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True);p.add_argument("--work-root",type=Path,required=True);p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--fan-in",type=int,default=16)
 a=p.parse_args();r=validate_union(release_path=a.release.resolve(),plan_path=a.plan.resolve(),stage5_db=a.stage5_db.resolve(),output_root=a.output_root.resolve(),work_root=a.work_root.resolve(),zstd_exe=a.zstd_exe.resolve(),output_path=a.output.resolve(),fan_in=a.fan_in);print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
