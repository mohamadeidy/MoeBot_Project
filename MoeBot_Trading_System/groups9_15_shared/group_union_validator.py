#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--plan",type=Path,required=True)
    p.add_argument("--manifest-root",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args();plan=json.loads(a.plan.read_text());fail=[];ids=set();rows=0
    manifests=[]
    for s in plan["shards"]:
        m=a.manifest_root/f'{s["shard_id"]}.manifest.json'
        if not m.is_file(): fail.append(f'missing_manifest:{s["shard_id"]}');continue
        x=json.loads(m.read_text());manifests.append(x)
        if x.get("shard_id")!=s["shard_id"]:fail.append(f'shard_id_mismatch:{s["shard_id"]}')
        if x.get("status")!="PASS":fail.append(f'shard_not_pass:{s["shard_id"]}')
        rows+=int(x.get("row_count",0))
        for rid in x.get("sample_or_all_ids",[]):
            if rid in ids:fail.append(f'duplicate_id:{rid}')
            ids.add(rid)
        if x.get("archive_path") and x.get("compressed_sha256"):
            ap=Path(x["archive_path"])
            if ap.is_file() and sha(ap)!=x["compressed_sha256"]:fail.append(f'archive_sha_mismatch:{s["shard_id"]}')
    out={"format_version":1,"group":plan.get("group"),"status":"PASS" if not fail else "FAIL","failures":fail,
         "expected_shards":len(plan["shards"]),"observed_manifests":len(manifests),"declared_rows":rows,
         "note":"Full global ID/reference fingerprints are added by each frozen semantic executor sidecars; this generic validator never reconstructs a monolith."}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps(out,indent=2,sort_keys=True));return 0 if not fail else 2
if __name__=="__main__":raise SystemExit(main())
