#!/usr/bin/env python3
"""Create compact cryptographic semantic fingerprints for one Group2-6 annual pipeline output."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from group8_compare_runtime_v2_v3_outputs import G25_RULES, G6_EXCLUDES

def canon(v:Any)->str: return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(v:Any)->str: return hashlib.sha256(canon(v).encode()).hexdigest()
def con(path:Path):
    c=sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True); c.row_factory=sqlite3.Row; return c
def cols(c,table): return [str(r[1]) for r in c.execute(f'PRAGMA table_info("{table}")')]
def semantic(c,table,exclude):
    cs=[x for x in cols(c,table) if x not in set(exclude)]; q=','.join(f'"{x}"' for x in cs); ctr=Counter()
    for row in c.execute(f'SELECT {q} FROM "{table}"'): ctr[canon([row[x] for x in cs])]+=1
    return {'columns':cs,'row_count':sum(ctr.values()),'multiset_digest':digest(sorted(ctr.items()))}
def ids(c,table,idcol):
    if not idcol:return None
    values=[str(r[0]) for r in c.execute(f'SELECT "{idcol}" FROM "{table}" ORDER BY "{idcol}"')]
    return {'id_column':idcol,'count':len(values),'set_digest':digest(values)}
def integrity(c):
    q=c.execute('PRAGMA quick_check').fetchone()[0]; i=c.execute('PRAGMA integrity_check').fetchone()[0]; fk=len(c.execute('PRAGMA foreign_key_check').fetchall()); return {'quick_check':q,'integrity_check':i,'foreign_key_errors':fk,'pass':q=='ok' and i=='ok' and fk==0}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pipeline-report',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    r=json.loads(a.pipeline_report.read_text()); groups={}
    for g,rules in G25_RULES.items():
        c=con(Path(r['artifacts'][g]['path'])); integ=integrity(c); tables={}
        if not integ['pass']: raise SystemExit(f'integrity fail {g}')
        for t,rule in rules.items(): tables[t]={'schema_columns':cols(c,t),'stable_ids':ids(c,t,rule['id']),'semantic':semantic(c,t,list(rule['exclude']))}
        c.close();groups[g]={'sqlite':integ,'tables':tables}
    c=con(Path(r['artifacts']['group6']['path']));integ=integrity(c);tables={}
    if not integ['pass']: raise SystemExit('integrity fail group6')
    for t,ex in G6_EXCLUDES.items(): tables[t]={'schema_columns':cols(c,t),'semantic':semantic(c,t,ex)}
    c.close();groups['group6']={'sqlite':integ,'tables':tables}
    out={'format_version':1,'year':r['year'],'source_sha256':r['source_sha256'],'engines':{g:v['sha256'] for g,v in r['engines'].items()},'groups':groups,'status':'PASS'}
    out['fingerprint_hash']=digest(out);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':'PASS','year':out['year'],'fingerprint_hash':out['fingerprint_hash']},indent=2))
if __name__=='__main__':main()
