#!/usr/bin/env python3
"""Compare v2/v3 annual runtime fingerprints and fail on any upstream-ID or semantic drift."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--v2',type=Path,required=True);ap.add_argument('--v3',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    x=json.loads(a.v2.read_text());y=json.loads(a.v3.read_text());fails=[];groups={}
    if x.get('status')!='PASS' or y.get('status')!='PASS':fails.append('fingerprint_input_not_pass')
    if x.get('year')!=y.get('year'):fails.append('year_mismatch')
    if x.get('source_sha256')!=y.get('source_sha256'):fails.append('source_sha_mismatch')
    for g in ('group2','group3','group4','group5'):
        tr={}
        names=sorted(set(x['groups'][g]['tables'])|set(y['groups'][g]['tables']))
        for t in names:
            if t not in x['groups'][g]['tables'] or t not in y['groups'][g]['tables']:
                tr[t]={'pass':False,'reason':'missing_table'};fails.append(f'{g}:{t}:missing');continue
            arow=x['groups'][g]['tables'][t];brow=y['groups'][g]['tables'][t]
            schema=arow['schema_columns']==brow['schema_columns'];sem=arow['semantic']==brow['semantic'];ids=(arow['stable_ids']==brow['stable_ids'])
            ok=schema and sem and ids;tr[t]={'schema_equal':schema,'stable_ids_equal':ids,'semantic_equal':sem,'pass':ok}
            if not ok:fails.append(f'{g}:{t}:drift')
        groups[g]={'tables':tr,'pass':all(v['pass'] for v in tr.values())}
    tr={}
    for t in sorted(set(x['groups']['group6']['tables'])|set(y['groups']['group6']['tables'])):
        if t not in x['groups']['group6']['tables'] or t not in y['groups']['group6']['tables']:
            tr[t]={'pass':False,'reason':'missing_table'};fails.append(f'group6:{t}:missing');continue
        aa=x['groups']['group6']['tables'][t];bb=y['groups']['group6']['tables'][t]
        schema=aa['schema_columns']==bb['schema_columns'];sem=aa['semantic']==bb['semantic'];ok=schema and sem
        tr[t]={'schema_equal':schema,'semantic_equal':sem,'pass':ok}
        if not ok:fails.append(f'group6:{t}:semantic_drift')
    groups['group6']={'tables':tr,'pass':all(v['pass'] for v in tr.values())}
    engines={'v2':x['engines'],'v3':y['engines'],'unchanged_expected':{g:x['engines'][g]==y['engines'][g] for g in ('g2','g3','g6')},'corrected_expected':{g:x['engines'][g]!=y['engines'][g] for g in ('g4','g5')}}
    if not all(engines['unchanged_expected'].values()):fails.append('unexpected_engine_drift_g2_g3_or_g6')
    out={'format_version':1,'year':x.get('year'),'source_sha256':x.get('source_sha256'),'method':'v2-v3 cryptographic fingerprints; Groups2-5 require exact stable-ID set + semantic multiset equality; Group6 requires semantic multiset equality with internal dependency-byte-derived IDs/hashes excluded','groups':groups,'engines':engines,'failures':fails,'status':'PASS' if not fails else 'FAIL'}
    out['report_hash']=hashlib.sha256(canon(out).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':out['status'],'year':out['year'],'failures':fails,'report_hash':out['report_hash']},indent=2));raise SystemExit(0 if not fails else 1)
if __name__=='__main__':main()
