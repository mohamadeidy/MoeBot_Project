#!/usr/bin/env python3
"""Verify that canonical published Group6 upstream IDs resolve in corrected-v3 Groups2-5 outputs.

Group6 itself remains the published frozen annual database. This audit asks the downstream
compatibility question Group8 actually needs: do every explicit Group2/3/4/5 ID carried by
published Group6 still resolve against the corrected canonical upstream databases?
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from pathlib import Path
from typing import Any

ID_TABLES={
 'group2': [('regime_states','state_id')],
 'group3': [('swings','swing_id'),('break_events','event_id'),('structure_states','state_id')],
 'group4': [('zones','zone_id'),('zone_interactions','interaction_id'),('zone_transitions','transition_id')],
 'group5': [('liquidity_pools','pool_id'),('liquidity_events','event_id'),('draw_states','draw_id'),('inducements','inducement_id'),('liquidity_voids','void_id'),('post_event_observations','observation_id'),('void_observations','observation_id')],
}

def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(v:Any)->str:return hashlib.sha256(canon(v).encode()).hexdigest()
def con(path:Path):
    c=sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
def id_union(path:Path,group:str)->set[str]:
    c=con(path);tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};out=set()
    for table,col in ID_TABLES[group]:
        if table not in tables:raise RuntimeError(f'{group} missing {table}')
        out.update(str(r[0]) for r in c.execute(f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'))
    c.close();return out
def main()->int:
    ap=argparse.ArgumentParser();
    ap.add_argument('--published-g6',type=Path,required=True);ap.add_argument('--g2',type=Path,required=True);ap.add_argument('--g3',type=Path,required=True);ap.add_argument('--g4',type=Path,required=True);ap.add_argument('--g5',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    paths={'group2':a.g2,'group3':a.g3,'group4':a.g4,'group5':a.g5};ids={g:id_union(p,g) for g,p in paths.items()};c=con(a.published_g6);fails=[];checks={}
    explicit=[
      ('fvg_events','group2_state_id','group2'),('fvg_events','group3_state_id','group3'),('fvg_events','associated_group3_event_id','group3'),('fvg_events','associated_group5_event_id','group5')]
    for table,col,group in explicit:
        vals=[str(r[0]) for r in c.execute(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL ORDER BY "{col}"')]
        missing=sorted(v for v in vals if v not in ids[group]);checks[f'{table}.{col}']={'target_group':group,'distinct_reference_count':len(vals),'missing_count':len(missing),'missing_sample':missing[:20],'pass':not missing}
        if missing:fails.append(f'{table}.{col}:unresolved:{len(missing)}')
    evidence={g:{'references':0,'missing':[]} for g in ids};unknown={}
    for r in c.execute("SELECT source_group,source_id FROM group6_evidence WHERE source_id IS NOT NULL"):
        raw=str(r['source_group'] or '').strip().lower().replace('_','').replace('-','');sid=str(r['source_id']);target=None
        for g in ids:
            if g in raw:target=g;break
        if target:
            evidence[target]['references']+=1
            if sid not in ids[target] and len(evidence[target]['missing'])<100:evidence[target]['missing'].append(sid)
        else:unknown[str(r['source_group'])]=unknown.get(str(r['source_group']),0)+1
    for g,row in evidence.items():
        row['missing']=sorted(set(row['missing']));row['missing_count']=len(row['missing']);row['pass']=row['missing_count']==0
        if not row['pass']:fails.append(f'group6_evidence:{g}:unresolved_sampled:{row["missing_count"]}')
    c.close()
    report={'format_version':1,'status':'PASS' if not fails else 'FAIL','method':'canonical published Group6 explicit upstream IDs must resolve in corrected-v3 Groups2-5 stable-ID universes','stable_id_universe_counts':{g:len(v) for g,v in ids.items()},'explicit_reference_checks':checks,'group6_evidence_reference_checks':evidence,'non_group2_5_evidence_source_groups':unknown,'failures':fails}
    report['report_hash']=digest(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'failures':fails,'report_hash':report['report_hash']},indent=2));return 0 if not fails else 1
if __name__=='__main__':raise SystemExit(main())
