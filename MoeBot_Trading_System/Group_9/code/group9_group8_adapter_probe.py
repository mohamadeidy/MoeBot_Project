#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def cols(con,t):return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--database",type=Path,required=True);p.add_argument("--adapter",type=Path,required=True);p.add_argument("--definition-registry",type=Path,required=True);p.add_argument("--report",type=Path,required=True);a=p.parse_args()
 ad=json.loads(a.adapter.read_text());reg=json.loads(a.definition_registry.read_text());defs=set(reg.get("definitions",{}));fail=[];tables={}
 con=sqlite3.connect(f"file:{a.database.resolve()}?mode=ro",uri=True)
 try:
  for t,required in ad["required_tables"].items():
   have=cols(con,t);missing=sorted(set(required)-have);tables[t]={"column_count":len(have),"missing_columns":missing}
   if missing:fail.append(f"{t}:missing_columns:{','.join(missing)}")
 finally:con.close()
 roles={}
 for role,ids in ad["component_roles"].items():
  missing=sorted(set(ids)-defs);roles[role]={"definition_count":len(ids),"missing_definition_ids":missing}
  if missing:fail.append(f"{role}:missing_definitions:{','.join(missing)}")
 out={"format_version":1,"source_group":8,"target_group":9,"status":"PASS" if not fail else "FAIL","failures":fail,"tables":tables,"roles":roles,
      "adapter_hash":stable(ad),"definition_registry_hash":reg.get("registry_hash") or stable(reg)}
 out["report_hash"]=stable(out);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");print(json.dumps(out,indent=2,sort_keys=True));return 0 if not fail else 2
if __name__=="__main__":raise SystemExit(main())
