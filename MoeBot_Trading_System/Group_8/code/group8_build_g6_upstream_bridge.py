#!/usr/bin/env python3
"""Fail-closed bridge from published Group6 upstream IDs to corrected-v3 IDs."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from collections import Counter,defaultdict
from pathlib import Path
from typing import Any
GROUPS=('group2','group3','group4','group5')
ID_TABLES={
'group2':(('regime_states','state_id'),),
'group3':(('swings','swing_id'),('break_events','event_id'),('structure_states','state_id')),
'group4':(('zones','zone_id'),('zone_interactions','interaction_id'),('zone_transitions','transition_id')),
'group5':(('liquidity_pools','pool_id'),('liquidity_events','event_id'),('draw_states','draw_id'),('inducements','inducement_id'),('liquidity_voids','void_id'),('post_event_observations','observation_id'),('void_observations','observation_id'))}
CORE={'displacement_legs':'leg_id','displacement_validation_events':'validation_id','fvg_lifecycle_summary':'fvg_id','fvg_state_transitions':'transition_id','fvg_visit_observations':'visit_id','fvg_visit_reactions':'reaction_id','imbalance_variants':'variant_id','inversion_fvg_relations':'inversion_id','inversion_retest_observations':'observation_id','liquidity_voids':'void_id','liquidity_void_members':'member_id','liquidity_void_state_transitions':'transition_id','liquidity_void_lifecycle_summary':'void_id','bpr_state_transitions':'transition_id','bpr_lifecycle_summary':'bpr_id','mtf_imbalance_relations':'relation_id'}
IDENTITY_KEYS={'pool_id','source_event_id','source_pool_id','target_pool_id','protected_high_id','protected_low_id','last_event_id'}
def cj(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha(v:Any)->str:return hashlib.sha256(cj(v).encode()).hexdigest()
def norm(v:Any)->str:
 if isinstance(v,(bytes,bytearray,memoryview)):return bytes(v).hex()
 return str(v)
def con(p:Path):
 c=sqlite3.connect(f'file:{p.resolve()}?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row;return c
def integ(c):
 q=c.execute('PRAGMA quick_check').fetchone()[0];i=c.execute('PRAGMA integrity_check').fetchone()[0];fk=len(c.execute('PRAGMA foreign_key_check').fetchall());return {'quick_check':q,'integrity_check':i,'foreign_key_errors':fk,'pass':q=='ok' and i=='ok' and fk==0}
def universe(p:Path,g:str)->set[str]:
 c=con(p);tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};out=set()
 for t,k in ID_TABLES[g]:
  if t not in tables:raise RuntimeError(f'{g} missing {t}')
  out.update(norm(r[0]) for r in c.execute(f'SELECT "{k}" FROM "{t}" WHERE "{k}" IS NOT NULL'))
 c.close();return out
def group(raw:Any):
 x=str(raw or '').lower().replace('_','').replace('-','')
 return next((g for g in GROUPS if g in x),None)
def strip_ids(v:Any)->Any:
 if isinstance(v,dict):return {k:strip_ids(x) for k,x in sorted(v.items()) if k not in IDENTITY_KEYS and not k.endswith('_id')}
 if isinstance(v,list):return [strip_ids(x) for x in v]
 return v
def remap(v:Any,maps):
 if isinstance(v,str):return next((m[v] for m in maps.values() if v in m),v)
 if isinstance(v,list):return [remap(x,maps) for x in v]
 if isinstance(v,dict):return {k:remap(x,maps) for k,x in v.items()}
 return v
class Bridge:
 def __init__(self,u):self.u=u;self.m={g:{} for g in GROUPS};self.rev={g:{} for g in GROUPS};self.ctx={g:defaultdict(list) for g in GROUPS};self.fail=[]
 def add(self,g,o,n,ctx):
  if o is None and n is None:return
  if o is None or n is None:self.fail.append(f'{ctx}:{g}:null_asymmetry');return
  o,n=norm(o),norm(n)
  if n not in self.u[g]:self.fail.append(f'{ctx}:{g}:new_not_in_universe:{n}');return
  if o in self.m[g] and self.m[g][o]!=n:self.fail.append(f'{ctx}:{g}:one_to_many:{o}');return
  if n in self.rev[g] and self.rev[g][n]!=o:self.fail.append(f'{ctx}:{g}:many_to_one:{n}');return
  self.m[g][o]=n;self.rev[g][n]=o
  if len(self.ctx[g][o])<8:self.ctx[g][o].append(ctx)
 def get(self,g,o):
  if o is None:return None
  o=norm(o)
  if o in self.m[g]:return self.m[g][o]
  if o in self.u[g]:return o
  self.fail.append(f'unresolved:{g}:{o}');return None
def pkrows(c,t,k):return {norm(r[k]):dict(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY "{k}"')}
def compare_core(a,b,fail):
 out={}
 for t,k in CORE.items():
  x,y=pkrows(a,t,k),pkrows(b,t,k);ok=x==y;out[t]={'published_count':len(x),'v3_count':len(y),'exact_rows_equal':ok}
  if not ok:fail.append(f'core_drift:{t}')
 return out
def pair_direct(a,b,br,fail):
 out={}
 for t,k in (('fvg_events','fvg_id'),('bpr_relations','bpr_id')):
  x,y=pkrows(a,t,k),pkrows(b,t,k)
  if set(x)!=set(y):fail.append(f'{t}:subject_set_drift')
  for sid in sorted(set(x)&set(y)):
   l,r=x[sid],y[sid];z=dict(l)
   if t=='fvg_events':
    for col,g in (('group2_state_id','group2'),('group3_state_id','group3'),('associated_group3_event_id','group3'),('associated_group5_event_id','group5')):br.add(g,l.get(col),r.get(col),f'fvg:{sid}:{col}');z[col]=br.get(g,l.get(col))
    oz=json.loads(l.get('parent_zone_ids_json') or '[]');nz=json.loads(r.get('parent_zone_ids_json') or '[]')
    if len(oz)!=len(nz):fail.append(f'fvg:{sid}:zone_count_drift')
    else:
     for i,(o,n) in enumerate(zip(oz,nz)):br.add('group4',o,n,f'fvg:{sid}:zone:{i}')
    z['parent_zone_ids_json']=cj([br.get('group4',v) for v in oz])
   else:
    for col,g in (('group2_state_id','group2'),('group3_state_id','group3')):br.add(g,l.get(col),r.get(col),f'bpr:{sid}:{col}');z[col]=br.get(g,l.get(col))
   z.pop('record_hash',None);rr=dict(r);rr.pop('record_hash',None)
   if z!=rr:fail.append(f'{t}:normalized_drift:{sid}')
  out[t]={'published_count':len(x),'v3_count':len(y),'compared':len(set(x)&set(y))}
 return out
def evgroups(c):
 d=defaultdict(list)
 for r in c.execute('SELECT * FROM group6_evidence ORDER BY subject_type,subject_id,source_group,relation_type,source_timeframe,availability_time,evidence_id'):
  x=dict(r);d[(x['subject_type'],x['subject_id'],x['source_group'],x['relation_type'],x['source_timeframe'],x['availability_time'])].append(x)
 return d
def pair_evidence(a,b,br,fail):
 A,B=evgroups(a),evgroups(b);paired=amb=0
 if set(A)!=set(B):fail.append('evidence:signature_set_drift')
 for key in sorted(set(A)&set(B),key=cj):
  L,R=A[key],B[key];g=group(key[2])
  if len(L)!=len(R):fail.append(f'evidence:count_drift:{cj(key)}');continue
  if not g:
   if sorted((r['source_id'],r['details_json']) for r in L)!=sorted((r['source_id'],r['details_json']) for r in R):fail.append(f'evidence:internal_drift:{cj(key)}')
   paired+=len(L);continue
  def sk(r):
   try:v=json.loads(r.get('details_json') or '{}')
   except json.JSONDecodeError:v=r.get('details_json')
   return cj(strip_ids(v))
  lb,rb=defaultdict(list),defaultdict(list)
  for r in L:lb[sk(r)].append(r)
  for r in R:rb[sk(r)].append(r)
  if set(lb)!=set(rb):fail.append(f'evidence:semantic_key_drift:{cj(key)}');continue
  for s in sorted(lb):
   if len(lb[s])!=len(rb[s]):fail.append(f'evidence:semantic_count_drift:{cj(key)}');continue
   if len(lb[s])!=1:amb+=len(lb[s]);fail.append(f'evidence:ambiguous:{cj(key)}:{len(lb[s])}');continue
   br.add(g,lb[s][0]['source_id'],rb[s][0]['source_id'],f'evidence:{cj(key)}');paired+=1
 def normalized(c,published):
  out=Counter()
  for r in c.execute('SELECT subject_type,subject_id,source_group,source_id,relation_type,source_timeframe,availability_time,details_json FROM group6_evidence'):
   x=dict(r);g=group(x['source_group'])
   if published and g:
    x['source_id']=br.get(g,x['source_id'])
    try:x['details_json']=cj(remap(json.loads(x['details_json'] or '{}'),br.m))
    except json.JSONDecodeError:pass
   out[cj(x)]+=1
  return out
 if normalized(a,True)!=normalized(b,False):fail.append('evidence:normalized_multiset_drift')
 return {'published_signatures':len(A),'v3_signatures':len(B),'paired_rows':paired,'ambiguous_rows':amb}
def coverage(c,br):
 n=Counter()
 for r in c.execute('SELECT group2_state_id,group3_state_id,associated_group3_event_id,associated_group5_event_id,parent_zone_ids_json FROM fvg_events'):
  for v,g in ((r[0],'group2'),(r[1],'group3'),(r[2],'group3'),(r[3],'group5')):
   if v is not None:n[g]+=1;br.get(g,v)
  for v in json.loads(r[4] or '[]'):n['group4']+=1;br.get('group4',v)
 for r in c.execute('SELECT group2_state_id,group3_state_id FROM bpr_relations'):
  if r[0] is not None:n['group2']+=1;br.get('group2',r[0])
  if r[1] is not None:n['group3']+=1;br.get('group3',r[1])
 for r in c.execute('SELECT source_group,source_id FROM group6_evidence WHERE source_id IS NOT NULL'):
  g=group(r[0])
  if g:n[g]+=1;br.get(g,r[1])
 return {g:n[g] for g in GROUPS}
def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=(2023,2024),required=True);p.add_argument('--published-g6',type=Path,required=True);p.add_argument('--v3-g6',type=Path,required=True)
 for g in GROUPS:p.add_argument(f'--{g}',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);a=p.parse_args();paths={g:getattr(a,g) for g in GROUPS};u={g:universe(paths[g],g) for g in GROUPS};br=Bridge(u);fail=[];A,B=con(a.published_g6),con(a.v3_g6);ia,ib=integ(A),integ(B)
 if not ia['pass']:fail.append('published_integrity')
 if not ib['pass']:fail.append('v3_integrity')
 core=compare_core(A,B,fail);direct=pair_direct(A,B,br,fail);ev=pair_evidence(A,B,br,fail);cov=coverage(A,br);fail=sorted(set(fail+br.fail));maps={}
 for g in GROUPS:
  explicit=[{'published_id':o,'corrected_v3_id':n,'contexts':br.ctx[g].get(o,[])} for o,n in sorted(br.m[g].items()) if o!=n];identity=sorted(o for o,n in br.m[g].items() if o==n)
  maps[g]={'referenced_count':cov[g],'resolved_unique_count':len(br.m[g]),'identity_mapping_count':len(identity),'identity_mapping_set_sha256':sha(identity),'explicit_non_identity_mapping_count':len(explicit),'explicit_non_identity_mappings':explicit,'corrected_v3_universe_count':len(u[g])}
 report={'format_version':1,'status':'PASS' if not fail else 'FAIL','year':a.year,'method':'Align identical immutable Group6 subjects and unique evidence semantics; require bijective referenced-ID bridge and normalized Group6 equality.','published_g6_sqlite':ia,'corrected_v3_g6_sqlite':ib,'core_table_comparison':core,'direct_reference_comparison':direct,'evidence_comparison':ev,'mappings':maps,'failures':fail};report['bridge_hash']=sha(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'year':a.year,'failure_count':len(fail),'bridge_hash':report['bridge_hash'],'non_identity':{g:maps[g]['explicit_non_identity_mapping_count'] for g in GROUPS}},indent=2));A.close();B.close();raise SystemExit(0 if not fail else 1)
if __name__=='__main__':main()
