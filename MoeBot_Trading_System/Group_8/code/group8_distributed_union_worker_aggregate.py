#!/usr/bin/env python3
"""Scalable finalizer for worker-aggregate Group 8 distributed-union sidecars.

A production PA7 worker owns several monthly shard databases. Its candidate/state
sidecars are therefore intentionally aggregated across those databases. This finalizer
accepts one sidecar report per worker (and one for the finalized core), cryptographically
flattens every source database SHA from those reports, and requires the resulting
multiset to equal exactly the finalized core plus every PA7 release shard before it
computes the frozen full-union fingerprints.
"""
from __future__ import annotations
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from group8_distributed_union_validator import (
 _load,_verify_report_hash,_stream_combined_table,_tables,_core_domain_hash,_parse_prefix_args,
)
from group8_shard_union_validator import DOMAIN_TABLES,EXPECTED_CONTRACT,EXPECTED_FREEZE,EXPECTED_ENGINE,stable_hash,sha256_file


def finalize_worker_aggregate(*,core_db:Path,pa7_release_report:Path,core_reference_report:Path,shard_audit_paths:list[Path],sidecar_report_paths:list[Path],candidate_prefixes:dict[str,Path],state_prefixes:dict[str,Path],candidate_merge_reports:dict[str,Path],state_merge_reports:dict[str,Path],year:int,symbol:str,output:Path)->dict[str,Any]:
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
 if len(actual)!=len(audits):raise RuntimeError('duplicate shard audit identity')
 if set(expected)!=set(actual):raise RuntimeError(f'shard audit coverage mismatch:{len(actual)}!={len(expected)}')
 for sid,s in expected.items():
  a=actual[sid]
  if a.get('manifest_hash')!=s.get('manifest_hash') or a.get('database_sha256')!=s.get('sha256') or int(a.get('database_size_bytes',-1))!=int(s.get('file_size_bytes',-2)):raise RuntimeError(f'shard audit identity mismatch:{sid}')
 sidecars=[_load(p) for p in sidecar_report_paths]
 actual_sources=Counter()
 for i,r in enumerate(sidecars):
  _verify_report_hash(r,f'sidecar_{i}')
  sources=r.get('source_databases',[])
  if r.get('status')!='PASS' or int(r.get('database_count',-1))<=0 or int(r.get('database_count',-1))!=len(sources) or r.get('free_only') is not True or r.get('paid_runner_used') or r.get('paid_service_used'):raise RuntimeError(f'aggregate sidecar report not PASS:{i}')
  local=Counter(str(x.get('sha256')) for x in sources)
  if None in local or 'None' in local:raise RuntimeError(f'aggregate sidecar source SHA missing:{i}')
  for digest,n in local.items():actual_sources[digest]+=n
 core_sha=sha256_file(core_path);expected_sources=Counter([core_sha]+[str(s['sha256']) for s in expected.values()])
 if actual_sources!=expected_sources:raise RuntimeError(f'sidecar source database coverage mismatch expected={sum(expected_sources.values())} actual={sum(actual_sources.values())}')
 c=sqlite3.connect(f'file:{core_path}?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
 try:
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('core sqlite check failed')
  if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('core foreign-key errors')
  tables=_tables(c);core_counts={t:int(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in ('price_action_pattern_candidate','price_action_pattern_state')};shard_counts={t:sum(int(s.get('table_row_counts',{}).get(t,0)) for s in expected.values()) for t in ('price_action_pattern_candidate','price_action_pattern_state')};table_counts={};table_hashes={}
  cnt,hsh=_stream_combined_table(prefixes=candidate_prefixes,merge_reports=candidate_merge_reports,sidecar_reports=sidecars,core=c,table='price_action_pattern_candidate',idc='candidate_id',hc='candidate_hash',expected_count=core_counts['price_action_pattern_candidate']+shard_counts['price_action_pattern_candidate'],short='candidate');table_counts['price_action_pattern_candidate']=cnt;table_hashes['price_action_pattern_candidate']=hsh
  cnt,hsh=_stream_combined_table(prefixes=state_prefixes,merge_reports=state_merge_reports,sidecar_reports=sidecars,core=c,table='price_action_pattern_state',idc='state_event_id',hc='state_hash',expected_count=core_counts['price_action_pattern_state']+shard_counts['price_action_pattern_state'],short='state');table_counts['price_action_pattern_state']=cnt;table_hashes['price_action_pattern_state']=hsh
  for table,(idc,hc) in DOMAIN_TABLES.items():
   if table in ('price_action_pattern_candidate','price_action_pattern_state') or table not in tables:continue
   count,h=_core_domain_hash(c,table,idc,hc)
   if count:table_counts[table]=count;table_hashes[table]=h
 finally:c.close()
 payload={'tables':{t:{'count':table_counts[t],'logical_sha256':table_hashes[t]} for t in sorted(table_counts)}};global_hash=stable_hash(payload)
 rec={'format_version':3,'status':'PASS','year':year,'symbol':symbol,'full_annual_union':True,'sidecar_group_count':len(sidecars),'source_database_count':sum(actual_sources.values()),'shard_count':len(expected)+1,'pa7_shard_count':len(expected),'total_shard_bytes':core_path.stat().st_size+sum(int(s['file_size_bytes']) for s in expected.values()),'storage_contract_hash':EXPECTED_CONTRACT,'design_freeze_hash':EXPECTED_FREEZE,'engine_sha256':EXPECTED_ENGINE,'table_row_counts':table_counts,'table_logical_sha256':table_hashes,'global_logical_sha256':global_hash,'unresolved_group8_reference_count':0,'unresolved_group8_reference_sample':[],'duplicate_domain_id_count':0,'registry_conflict_count':0,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable_hash(rec);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec


def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--core-db',type=Path,required=True);p.add_argument('--pa7-release-report',type=Path,required=True);p.add_argument('--core-reference-report',type=Path,required=True);p.add_argument('--shard-audit-report',type=Path,action='append',required=True);p.add_argument('--sidecar-report',type=Path,action='append',required=True);p.add_argument('--candidate-prefix',action='append',required=True);p.add_argument('--state-prefix',action='append',required=True);p.add_argument('--candidate-merge-report',action='append',required=True);p.add_argument('--state-merge-report',action='append',required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--output',type=Path,required=True);x=p.parse_args();r=finalize_worker_aggregate(core_db=x.core_db,pa7_release_report=x.pa7_release_report,core_reference_report=x.core_reference_report,shard_audit_paths=x.shard_audit_report,sidecar_report_paths=x.sidecar_report,candidate_prefixes=_parse_prefix_args(x.candidate_prefix),state_prefixes=_parse_prefix_args(x.state_prefix),candidate_merge_reports=_parse_prefix_args(x.candidate_merge_report),state_merge_reports=_parse_prefix_args(x.state_merge_report),year=x.year,symbol=x.symbol,output=x.output);print(json.dumps({'status':r['status'],'global_logical_sha256':r['global_logical_sha256'],'report_hash':r['report_hash']},indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
