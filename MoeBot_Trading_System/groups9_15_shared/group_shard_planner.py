#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path

def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--group-dir",type=Path,required=True)
    p.add_argument("--inventory",type=Path,required=True,help="JSON list under items with stable root_id and scope fields")
    p.add_argument("--bucket-count",type=int,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();group=int(a.group_dir.name.split("_")[-1])
    inv=json.loads(a.inventory.read_text());items=inv.get("items",[])
    if a.bucket_count<1:raise SystemExit("bucket-count must be >=1")
    counts=[0]*a.bucket_count
    for x in items:
        rid=str(x["root_id"]);b=int.from_bytes(hashlib.sha256(rid.encode()).digest()[:8],"big")%a.bucket_count;counts[b]+=1
    shards=[{"group":group,"bucket_index":i,"bucket_count":a.bucket_count,"candidate_count":n,
             "shard_id":f"g{group}_b{i:04d}of{a.bucket_count:04d}"} for i,n in enumerate(counts) if n]
    out={"format_version":1,"group":group,"status":"PASS","inventory_hash":stable(inv),"bucket_count":a.bucket_count,
         "candidate_count":len(items),"shards":shards}
    out["plan_hash"]=stable(out)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":"PASS","group":group,"shards":len(shards),"candidates":len(items),"plan_hash":out["plan_hash"]},indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main())
