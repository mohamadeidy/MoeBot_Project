#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--group-dir",type=Path,required=True);p.add_argument("--union-report",type=Path,required=True);p.add_argument("--release",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 g=int(a.group_dir.name.split("_")[-1]);u=json.loads(a.union_report.read_text());r=json.loads(a.release.read_text())
 fail=[]
 if u.get("status")!="PASS":fail.append("union_not_pass")
 if r.get("status")!="PASS":fail.append("release_not_pass")
 out={"format_version":1,"source_group":g,"target_group":g+1 if g<15 else None,"status":"PASS" if not fail else "BLOCKED",
      "failures":fail,"consumption_policy":{"read_only":True,"selective_shard_access":True,"preserve_source_ids":True},
      "union_report_hash":stable(u),"release_hash":stable(r)}
 out["manifest_hash"]=stable(out);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");print(json.dumps(out,indent=2,sort_keys=True));return 0 if not fail else 2
if __name__=="__main__":raise SystemExit(main())
