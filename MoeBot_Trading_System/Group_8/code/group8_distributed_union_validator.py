#!/usr/bin/env python3
"""Exact FREE-only full-union validation without a monolithic annual ID ledger.

PA7 shard SQLite files are independently audited against the finalized core. Candidate
and state domain identities are represented by SHA-bound prefix sidecars, merged by
hex prefix with duplicate rejection. Finalization streams the 16 canonical prefixes,
proves exact source-sidecar coverage, proves every finalized-core candidate/state is
present with the same hash, and reconstructs the exact legacy full-union table/global
logical fingerprints. All other Group 8 domain tables live in the finalized core and
are fingerprinted directly with the frozen (primary_id,row_hash) contract.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from collections import Counter
from pathlib import Path
from typing import Any,Iterable

from group8_logical_sidecars import HEX,prefix,sha as sha_file,stable as stable_sidecar
from group8_shard_union_validator import (
    DOMAIN_TABLES,REGISTRY_TABLES,EXPECTED_CONTRACT,EXPECTED_FREEZE,EXPECTED_ENGINE,
    stable_hash,sha256_file,
)


def _load(path:Path)->dict[str,Any]:return json.loads(path.read_text())
def _verify_report_hash(report:dict[str,Any],label:str)->None:
 if 'report_hash' not in report:raise RuntimeError(f'{label}:missing_report_hash')
 q=dict(report);saved=q.pop('report_hash')
 if saved!=stable_hash(q):raise RuntimeError(f'{label}:report_hash_mismatch')

def _tables(c:sqlite3.Connection)->set[str]:return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def _exists(c:sqlite3.Connection,table:str,idc:str,rid:str)->bool:
 return c.execute(f'SELECT 1 FROM "{table}" WHERE "{idc}"=? LIMIT 1',(rid,)).fetchone() is not None

def _definition_typed_exists(shard:sqlite3.Connection,core:sqlite3.Connection,kind:str,rid:str,st:set[str],ct:set[str])->bool:
 """Resolve frozen source_type values that are definition IDs rather than domain tables."""
 if 'price_action_pattern_candidate' in st and shard.execute('SELECT 1 FROM price_action_pattern_candidate WHERE candidate_id=? AND definition_id=? LIMIT 1',(rid,kind)).fetchone() is not None:return True
 if 'price_action_pattern_candidate' in ct and core.execute('SELECT 1 FROM price_action_pattern_candidate WHERE candidate_id=? AND definition_id=? LIMIT 1',(rid,kind)).fetchone() is not None:return True
 if 'school_interpretation' in ct and core.execute('SELECT 1 FROM school_interpretation WHERE interpretation_id=? AND definition_id=? LIMIT 1',(rid,kind)).fetchone() is not None:return True
 return 'narrative_hypothesis' in ct and core.execute('SELECT 1 FROM narrative_hypothesis WHERE hypothesis_id=? AND definition_id=? LIMIT 1',(rid,kind)).fetchone() is not None

def _json_refs(value:str|None)->list[dict[str,Any]]:
 if not value:return []
 v=json.loads(value);return [x for x in v if isinstance(x,dict)] if isinstance(v,list) else []


def audit_pa7_shard(*,database:Path,manifest_path:Path,core_db:Path,year:int,symbol:str,group8_root:Path)->dict[str,Any]:
 if year==2024:
  s=_load(group8_root/'STATUS.json')
  if s.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
 m=_load(manifest_path);payload=dict(m);saved=payload.pop('manifest_hash',None)
 if saved!=stable_hash(payload):raise RuntimeError('manifest self-hash mismatch')
 for key,expected in (('year',year),('symbol',symbol),('storage_contract_hash',EXPECTED_CONTRACT),('design_freeze_hash',EXPECTED_FREEZE),('engine_sha256',EXPECTED_ENGINE)):
  if m.get(key)!=expected:raise RuntimeError(f'manifest identity mismatch:{key}')
 db=database.resolve();core=core_db.resolve()
 if sha256_file(db)!=m.get('sha256') or db.stat().st_size!=int(m.get('file_size_bytes',-1)):raise RuntimeError('shard file identity mismatch')
 s=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True);s.row_factory=sqlite3.Row
 c=sqlite3.connect(f'file:{core}?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
 unresolved=[];registry_conflicts=[];group8_refs=0
 try:
  for label,con in (('shard',s),('core',c)):
   if con.execute('PRAGMA quick_check').fetchone()[0]!='ok' or con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError(f'{label} sqlite check failed')
   if con.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError(f'{label} foreign-key errors')
  st=_tables(s);ct=_tables(c)
  for table,(idc,hc) in REGISTRY_TABLES.items():
   if table not in st:continue
   if table not in ct:raise RuntimeError(f'core registry missing:{table}')
   for rid,rh in s.execute(f'SELECT "{idc}","{hc}" FROM "{table}"'):
    row=c.execute(f'SELECT "{hc}" FROM "{table}" WHERE "{idc}"=?',(str(rid),)).fetchone()
    if row is None or str(row[0])!=str(rh):registry_conflicts.append({'table':table,'row_id':str(rid)})
  if 'price_action_pattern_candidate' in st:
   for row in s.execute('SELECT candidate_id,upstream_refs_json FROM price_action_pattern_candidate'):
    for ref in _json_refs(row['upstream_refs_json']):
     if str(ref.get('source_group','')).lower()!='group8':continue
     group8_refs+=1;kind=str(ref.get('source_type') or '');rid=str(ref.get('source_id') or '')
     rec=DOMAIN_TABLES.get(kind);ok=False
     if rid and rec:
      if kind=='price_action_pattern_candidate':ok=_exists(s,kind,rec[0],rid) or (kind in ct and _exists(c,kind,rec[0],rid))
      else:ok=kind in ct and _exists(c,kind,rec[0],rid)
     elif rid:
      ok=_definition_typed_exists(s,c,kind,rid,st,ct)
     if not ok and len(unresolved)<100:unresolved.append({'candidate_id':str(row['candidate_id']),'target_type':kind,'target_id':rid})
  counts={}
  for table in ('price_action_pattern_candidate','price_action_pattern_state'):
   counts[table]=int(s.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if table in st else 0
 finally:s.close();c.close()
 if registry_conflicts:raise RuntimeError(f'registry conflicts:{registry_conflicts[:5]}')
 if unresolved:raise RuntimeError(f'unresolved PA7 Group8 refs:{unresolved[:5]}')
 rec={'format_version':1,'status':'PASS','year':year,'symbol':symbol,'shard_id':m['shard_id'],'manifest_hash':m['manifest_hash'],'database_sha256':m['sha256'],'database_size_bytes':m['file_size_bytes'],'table_row_counts':counts,'group8_reference_count':group8_refs,'unresolved_group8_reference_count':0,'registry_conflict_count':0,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable_hash(rec);return rec


def _parse_prefix_args(values:Iterable[str])->dict[str,Path]:
 out={}
 for raw in values:
  p,sep,path=raw.partition('=')
  if not sep or p not in HEX or p in out:raise ValueError(f'invalid prefix mapping:{raw}')
  out[p]=Path(path).resolve()
 if set(out)!=set(HEX):raise ValueError('all 16 hex prefixes are required')
 return out


def _core_domain_hash(c:sqlite3.Connection,table:str,idc:str,hc:str)->tuple[int,str]:
 h=hashlib.sha256();count=0
 for rid,rh in c.execute(f'SELECT "{idc}","{hc}" FROM "{table}" ORDER BY "{idc}"'):
  h.update(str(rid).encode());h.update(b'\0');h.update(str(rh).encode());h.update(b'\n');count+=1
 return count,h.hexdigest()


def _stream_combined_table(*,prefixes:dict[str,Path],merge_reports:dict[str,Path],sidecar_reports:list[dict[str,Any]],core:sqlite3.Connection,table:str,idc:str,hc:str,expected_count:int,short:str)->tuple[int,str]:
 expected_inputs={}
 for p in HEX:expected_inputs[p]=Counter(str(r['files'][f'{short}_{p}']['sha256']) for r in sidecar_reports)
 core_cur=iter(core.execute(f'SELECT "{idc}","{hc}" FROM "{table}" ORDER BY "{idc}"'));core_row=next(core_cur,None)
 h=hashlib.sha256();count=0;prev=None
 for p in HEX:
  path=prefixes[p];mr=_load(merge_reports[p]);_verify_report_hash(mr,f'{short}_{p}_merge')
  if mr.get('status')!='PASS' or int(mr.get('input_count',-1))!=len(sidecar_reports):raise RuntimeError(f'{short}_{p}:merge_not_pass')
  if Counter(str(x['sha256']) for x in mr.get('inputs',[]))!=expected_inputs[p]:raise RuntimeError(f'{short}_{p}:sidecar_input_coverage_mismatch')
  if sha_file(path)!=mr.get('file_sha256') or path.stat().st_size!=int(mr.get('file_size_bytes',-1)):raise RuntimeError(f'{short}_{p}:canonical_stream_identity_mismatch')
  local_rows=0
  with path.open('rb') as f:
   for line in f:
    if not line.endswith(b'\n') or b'\0' not in line:raise RuntimeError(f'{short}_{p}:malformed_stream')
    ridb,rhb=line[:-1].split(b'\0',1);rid=ridb.decode();rh=rhb.decode()
    if prefix(rid)!=p:raise RuntimeError(f'{short}_{p}:wrong_prefix:{rid}')
    if prev is not None and rid<=prev:raise RuntimeError(f'{short}:non_strict_global_order_or_duplicate:{rid}')
    while core_row is not None and str(core_row[0])<rid:raise RuntimeError(f'{short}:missing_core_domain_id:{core_row[0]}')
    if core_row is not None and str(core_row[0])==rid:
     if str(core_row[1])!=rh:raise RuntimeError(f'{short}:core_hash_mismatch:{rid}')
     core_row=next(core_cur,None)
    h.update(line);prev=rid;count+=1;local_rows+=1
  if local_rows!=int(mr.get('row_count',-1)):raise RuntimeError(f'{short}_{p}:row_count_mismatch')
 if core_row is not None:raise RuntimeError(f'{short}:missing_trailing_core_domain_id:{core_row[0]}')
 if count!=expected_count:raise RuntimeError(f'{short}:coverage_count_mismatch:{count}!={expected_count}')
 return count,h.hexdigest()


def finalize_distributed_union(*,core_db:Path,pa7_release_report:Path,core_reference_report:Path,shard_audit_paths:list[Path],sidecar_report_paths:list[Path],candidate_prefixes:dict[str,Path],state_prefixes:dict[str,Path],candidate_merge_reports:dict[str,Path],state_merge_reports:dict[str,Path],year:int,symbol:str,output:Path)->dict[str,Any]:
 core_path=core_db.resolve();release=_load(pa7_release_report);_verify_report_hash(release,'pa7_release')
 if int(release.get('year',0))!=year or release.get('status')!='PASS' or release.get('complete_once_only_coverage') is not True:raise RuntimeError('PA7 release coverage not PASS')
 if release.get('free_only') is not True or release.get('paid_runner_used') or release.get('paid_service_used'):raise RuntimeError('PA7 release not FREE-only')
 if bool(release.get('oos_2024_accessed'))!=(year==2024):raise RuntimeError('PA7 release OOS flag mismatch')
 refs=_load(core_reference_report);_verify_report_hash(refs,'core_reference')
 if refs.get('status')!='PASS' or int(refs.get('unresolved_group8_reference_count',-1))!=0:raise RuntimeError('core cross-shard references unresolved')
 audits=[_load(p) for p in shard_audit_paths]
 for i,a in enumerate(audits):
  _verify_report_hash(a,f'shard_audit_{i}')
  if a.get('status')!='PASS' or int(a.get('year',0))!=year or a.get('symbol')!=symbol or int(a.get('unresolved_group8_reference_count',-1))!=0 or int(a.get('registry_conflict_count',-1))!=0:raise RuntimeError(f'shard audit not PASS:{i}')
  if a.get('free_only') is not True or a.get('paid_runner_used') or a.get('paid_service_used'):raise RuntimeError(f'shard audit not FREE:{i}')
 expected={str(s['shard_id']):s for s in release.get('shards',[])};actual={str(a['shard_id']):a for a in audits}
 if set(expected)!=set(actual):raise RuntimeError(f'shard audit coverage mismatch:{len(actual)}!={len(expected)}')
 for sid,s in expected.items():
  a=actual[sid]
  if a.get('manifest_hash')!=s.get('manifest_hash') or a.get('database_sha256')!=s.get('sha256') or int(a.get('database_size_bytes',-1))!=int(s.get('file_size_bytes',-2)):raise RuntimeError(f'shard audit identity mismatch:{sid}')
 sidecars=[_load(p) for p in sidecar_report_paths]
 for i,r in enumerate(sidecars):
  _verify_report_hash(r,f'sidecar_{i}')
  if r.get('status')!='PASS' or int(r.get('database_count',-1))!=1 or r.get('free_only') is not True or r.get('paid_runner_used') or r.get('paid_service_used'):raise RuntimeError(f'sidecar report not PASS:{i}')
 core_sha=sha256_file(core_path);expected_sources=Counter([core_sha]+[str(s['sha256']) for s in expected.values()]);actual_sources=Counter()
 for r in sidecars:
  src=r.get('source_databases',[])
  if len(src)!=1:raise RuntimeError('sidecar source binding must contain exactly one database')
  actual_sources[str(src[0]['sha256'])]+=1
 if actual_sources!=expected_sources:raise RuntimeError('sidecar source database coverage mismatch')
 c=sqlite3.connect(f'file:{core_path}?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
 try:
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('core sqlite check failed')
  if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('core foreign-key errors')
  tables=_tables(c);core_counts={t:int(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in ('price_action_pattern_candidate','price_action_pattern_state')}
  shard_counts={t:sum(int(s.get('table_row_counts',{}).get(t,0)) for s in expected.values()) for t in ('price_action_pattern_candidate','price_action_pattern_state')}
  table_counts={};table_hashes={}
  cnt,hsh=_stream_combined_table(prefixes=candidate_prefixes,merge_reports=candidate_merge_reports,sidecar_reports=sidecars,core=c,table='price_action_pattern_candidate',idc='candidate_id',hc='candidate_hash',expected_count=core_counts['price_action_pattern_candidate']+shard_counts['price_action_pattern_candidate'],short='candidate');table_counts['price_action_pattern_candidate']=cnt;table_hashes['price_action_pattern_candidate']=hsh
  cnt,hsh=_stream_combined_table(prefixes=state_prefixes,merge_reports=state_merge_reports,sidecar_reports=sidecars,core=c,table='price_action_pattern_state',idc='state_event_id',hc='state_hash',expected_count=core_counts['price_action_pattern_state']+shard_counts['price_action_pattern_state'],short='state');table_counts['price_action_pattern_state']=cnt;table_hashes['price_action_pattern_state']=hsh
  for table,(idc,hc) in DOMAIN_TABLES.items():
   if table in ('price_action_pattern_candidate','price_action_pattern_state') or table not in tables:continue
   count,h=_core_domain_hash(c,table,idc,hc)
   if count:table_counts[table]=count;table_hashes[table]=h
 finally:c.close()
 payload={'tables':{t:{'count':table_counts[t],'logical_sha256':table_hashes[t]} for t in sorted(table_counts)}};global_hash=stable_hash(payload)
 rec={'format_version':2,'status':'PASS','year':year,'symbol':symbol,'full_annual_union':True,'shard_count':len(expected)+1,'pa7_shard_count':len(expected),'total_shard_bytes':core_path.stat().st_size+sum(int(s['file_size_bytes']) for s in expected.values()),'storage_contract_hash':EXPECTED_CONTRACT,'design_freeze_hash':EXPECTED_FREEZE,'engine_sha256':EXPECTED_ENGINE,'table_row_counts':table_counts,'table_logical_sha256':table_hashes,'global_logical_sha256':global_hash,'unresolved_group8_reference_count':0,'unresolved_group8_reference_sample':[],'duplicate_domain_id_count':0,'registry_conflict_count':0,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable_hash(rec);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec


def main()->int:
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('audit-shard');a.add_argument('--database',type=Path,required=True);a.add_argument('--manifest',type=Path,required=True);a.add_argument('--core-db',type=Path,required=True);a.add_argument('--year',type=int,required=True);a.add_argument('--symbol',required=True);a.add_argument('--group8-root',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
 f=sub.add_parser('finalize');f.add_argument('--core-db',type=Path,required=True);f.add_argument('--pa7-release-report',type=Path,required=True);f.add_argument('--core-reference-report',type=Path,required=True);f.add_argument('--shard-audit-report',type=Path,action='append',required=True);f.add_argument('--sidecar-report',type=Path,action='append',required=True);f.add_argument('--candidate-prefix',action='append',required=True);f.add_argument('--state-prefix',action='append',required=True);f.add_argument('--candidate-merge-report',action='append',required=True);f.add_argument('--state-merge-report',action='append',required=True);f.add_argument('--year',type=int,required=True);f.add_argument('--symbol',required=True);f.add_argument('--output',type=Path,required=True)
 x=p.parse_args()
 if x.cmd=='audit-shard':
  r=audit_pa7_shard(database=x.database,manifest_path=x.manifest,core_db=x.core_db,year=x.year,symbol=x.symbol,group8_root=x.group8_root);x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
 else:
  r=finalize_distributed_union(core_db=x.core_db,pa7_release_report=x.pa7_release_report,core_reference_report=x.core_reference_report,shard_audit_paths=x.shard_audit_report,sidecar_report_paths=x.sidecar_report,candidate_prefixes=_parse_prefix_args(x.candidate_prefix),state_prefixes=_parse_prefix_args(x.state_prefix),candidate_merge_reports=_parse_prefix_args(x.candidate_merge_report),state_merge_reports=_parse_prefix_args(x.state_merge_report),year=x.year,symbol=x.symbol,output=x.output)
 print(json.dumps({'status':r['status'],'report_hash':r['report_hash'],'global_logical_sha256':r.get('global_logical_sha256')},indent=2,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
