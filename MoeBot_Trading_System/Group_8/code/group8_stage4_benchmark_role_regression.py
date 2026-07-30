#!/usr/bin/env python3
"""Regression: BENCHMARK_ONLY partition output equals official ordered partition output.

The benchmark clone is taken from the exact official logical pre-partition state.
Only physical receipt metadata is removed so BENCHMARK_ONLY cannot inherit or fake
official chain progress. Both paths invoke the same engine implementation.
"""
from __future__ import annotations
import argparse,json,shutil,sqlite3
from pathlib import Path
from typing import Any
from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import _enforce_stage4_execution_order
from group8_stage4_partition_regression import _fixture_ids,_filtered_process
from moebot_group8_engine_v0_8_0 import canonical_json,stable_hash

STAGE4_DEF='pa_context_linked_rejection'

def rows(con:sqlite3.Connection,table:str,where:str='',params:tuple=())->list[dict[str,Any]]:
 con.row_factory=sqlite3.Row
 return [dict(r) for r in con.execute(f'SELECT * FROM {table} {where}',params)]

def fingerprint(items:list[dict[str,Any]],id_col:str,hash_col:str)->dict[str,Any]:
 ordered=sorted(items,key=lambda r:str(r[id_col]))
 return {'count':len(ordered),'primary_ids':[r[id_col] for r in ordered],'row_hashes':[r[hash_col] for r in ordered],'logical_fingerprint':stable_hash([canonical_json(r) for r in ordered])}

def stage4_ids(con:sqlite3.Connection)->set[str]:
 return {str(r[0]) for r in con.execute('SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id=?',(STAGE4_DEF,))}

def execute_fixture(engine:AnnualCoreEngine,index:int,ids:set[str],official:bool)->dict[str,Any]:
 existing=_enforce_stage4_execution_order(engine,index) if official else None
 receipt=_filtered_process(engine,index,ids)
 if existing is not None and receipt!=existing:raise AssertionError('non-idempotent official retry')
 return receipt

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--checkpoint2-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--partition',type=int,default=3);p.add_argument('--fixture-per-partition',type=int,default=8);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 if not 0<=a.partition<24:raise ValueError('invalid partition')
 a.work_dir.mkdir(parents=True,exist_ok=True);ids=_fixture_ids(a.checkpoint2_db,a.fixture_per_partition);pre=a.work_dir/'official_pre.sqlite';shutil.copy2(a.checkpoint2_db,pre)
 e=AnnualCoreEngine(staging_db=a.staging_db,output_db=pre,artifacts_root=a.artifacts_root,year=2023,symbol='XAUUSD_')
 try:
  e.load_bars()
  for i in range(a.partition):execute_fixture(e,i,ids,True)
  e.out.commit()
 finally:e.close()
 official=a.work_dir/'official.sqlite';benchmark=a.work_dir/'benchmark.sqlite';shutil.copy2(pre,official);shutil.copy2(pre,benchmark)
 bcon=sqlite3.connect(benchmark);bcon.execute("DELETE FROM metadata WHERE key LIKE 'physical_stage4_partition_receipt:%'");bcon.commit();bcon.close()
 before=sqlite3.connect(pre);before_ids=stage4_ids(before);before.close()
 eo=AnnualCoreEngine(staging_db=a.staging_db,output_db=official,artifacts_root=a.artifacts_root,year=2023,symbol='XAUUSD_')
 eb=AnnualCoreEngine(staging_db=a.staging_db,output_db=benchmark,artifacts_root=a.artifacts_root,year=2023,symbol='XAUUSD_')
 try:
  eo.load_bars();eb.load_bars();official_receipt=execute_fixture(eo,a.partition,ids,True)
  for i in range(24):
   key=eb._receipt_key(eb,i) if hasattr(eb,'_receipt_key') else None
  benchmark_receipt=_filtered_process(eb,a.partition,ids)
  eo.out.commit();eb.out.commit()
 finally:eo.close();eb.close()
 oc=sqlite3.connect(official);bc=sqlite3.connect(benchmark);oc.row_factory=sqlite3.Row;bc.row_factory=sqlite3.Row
 try:
  oall=stage4_ids(oc);ball=stage4_ids(bc);onew=oall-before_ids;bnew=ball-before_ids
  if onew!=bnew:raise AssertionError('output candidate ID mismatch')
  placeholders=','.join('?' for _ in sorted(onew)) or "''";params=tuple(sorted(onew))
  op=rows(oc,'price_action_pattern_candidate',f'WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id',params)
  bp=rows(bc,'price_action_pattern_candidate',f'WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id',params)
  fields=('candidate_id','candidate_hash','feature_hash','features_json','upstream_refs_json','event_time','confirmation_time','availability_time','source_bar_id','definition_id')
  if [{k:r[k] for k in fields} for r in op]!=[{k:r[k] for k in fields} for r in bp]:raise AssertionError('exact candidate row mismatch')
  os=rows(oc,'price_action_pattern_state',f'WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id,state_ordinal',params)
  bs=rows(bc,'price_action_pattern_state',f'WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id,state_ordinal',params)
  if os!=bs:raise AssertionError('lifecycle state output mismatch')
  if official_receipt!=benchmark_receipt:raise AssertionError('receipt preview mismatch before publication')
  payload={'status':'PASS','partition_index':a.partition,'fixture_candidate_count':len(ids),'source_ids_hash':official_receipt['source_ids_hash'],'output_ids_hash':official_receipt['output_ids_hash'],'receipt_content_equal':True,'candidate_rows':fingerprint(op,'candidate_id','candidate_hash'),'state_rows':fingerprint(os,'state_event_id','state_hash'),'features_json_equal':True,'upstream_refs_json_equal':True,'causal_timestamps_equal':True,'benchmark_official_artifact_published':False,'checkpoint_3_published':False,'oos_2024_accessed':False,'free_only':True}
  payload['report_hash']=stable_hash(payload)
 finally:oc.close();bc.close()
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');print(json.dumps(payload,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
