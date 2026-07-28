#!/usr/bin/env python3
"""Exact PA7 one-pass bucket execution with causal-root month partition export.

The frozen PA7 semantics are unchanged. For one (timeframe, boundary_scope, bucket),
the engine processes the union of all causal-root months once, finalizes breakout
followups once, then physically partitions the immutable chain candidates/states back
into the exact monthly shards using each breakout boundary's frozen upstream event
month. Failed-breakout/retest rows inherit their parent breakout's root month.

This removes 12 repeated annual bar scans/catalog builds per bucket while preserving
the original monthly shard IDs, candidate/state IDs, hashes, and logical fingerprints.
"""
from __future__ import annotations

import argparse,hashlib,json,os,sqlite3
from pathlib import Path
from typing import Any,Iterable

from group8_pa7_shard_executor import (
    ShardSpec,CHAIN_DEFINITIONS,_copy_table,logical_table_hash,stable_hash,sha256_file,epoch_month,
)
from group8_pa7_scoped_shard_executor import ScopedPA7ShardEngine,_scope_manifest,SCOPES
from group8_postprocess_v0_8_0 import _finalize_breakout_followups

BREAKOUT_DEFS=('pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer')
CHILD_DEFS=('pa_failed_breakout','pa_retest')
ASSIGN_TABLE='_pa7_root_month_assignment'
SUPERSEDED_GITHUB_RUN_IDS={'30302628989'}


def _chain_assignments(work_db:Path,year:int)->dict[str,int]:
    con=sqlite3.connect(work_db);con.row_factory=sqlite3.Row
    try:
        con.execute(f'DROP TABLE IF EXISTS {ASSIGN_TABLE}')
        con.execute(f'CREATE TABLE {ASSIGN_TABLE}(candidate_id TEXT PRIMARY KEY,root_month TEXT NOT NULL) WITHOUT ROWID')
        q=','.join('?' for _ in BREAKOUT_DEFS)
        breakout_count=0
        for row in con.execute(f'SELECT candidate_id,upstream_refs_json FROM price_action_pattern_candidate WHERE definition_id IN ({q}) ORDER BY candidate_id',BREAKOUT_DEFS):
            refs=json.loads(row['upstream_refs_json']);boundary=[r for r in refs if str(r.get('source_group','')).lower()!='source']
            if len(boundary)!=1 or boundary[0].get('event_time') is None:raise RuntimeError(f'breakout boundary root is not unique/causal:{row["candidate_id"]}')
            month=epoch_month(int(boundary[0]['event_time']))
            if int(month[:4])!=int(year):raise RuntimeError(f'breakout root outside annual year:{row["candidate_id"]}:{month}')
            con.execute(f'INSERT INTO {ASSIGN_TABLE} VALUES(?,?)',(str(row['candidate_id']),month));breakout_count+=1
        qc=','.join('?' for _ in CHILD_DEFS)
        children=con.execute(f'''SELECT c.candidate_id,json_extract(c.features_json,'$.breakout_candidate_id') parent_id
          FROM price_action_pattern_candidate c WHERE c.definition_id IN ({qc}) ORDER BY c.candidate_id''',CHILD_DEFS).fetchall()
        for row in children:
            parent=str(row['parent_id'] or '')
            hit=con.execute(f'SELECT root_month FROM {ASSIGN_TABLE} WHERE candidate_id=?',(parent,)).fetchone()
            if hit is None:raise RuntimeError(f'PA7 child parent root unresolved:{row["candidate_id"]}:{parent}')
            con.execute(f'INSERT INTO {ASSIGN_TABLE} VALUES(?,?)',(str(row['candidate_id']),str(hit[0])))
        chain_q=','.join('?' for _ in CHAIN_DEFINITIONS)
        total=int(con.execute(f'SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id IN ({chain_q})',CHAIN_DEFINITIONS).fetchone()[0])
        assigned=int(con.execute(f'SELECT COUNT(*) FROM {ASSIGN_TABLE}').fetchone()[0])
        if total!=assigned:raise RuntimeError(f'PA7 month assignment coverage mismatch:{assigned}!={total}')
        by_month={str(m):int(n) for m,n in con.execute(f'SELECT root_month,COUNT(*) FROM {ASSIGN_TABLE} GROUP BY root_month ORDER BY root_month')}
        con.commit();return {'breakouts':breakout_count,'children':len(children),'total':total,'months':by_month}
    finally:con.close()


def _export_month(*,work_db:Path,output_db:Path,artifacts_root:Path,spec:ShardSpec,boundary_scope:str)->dict[str,Any]:
    if spec.root_month is None:raise ValueError('monthly export requires root_month')
    output_db.unlink(missing_ok=True);output_db.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(work_db);src.row_factory=sqlite3.Row;dst=sqlite3.connect(output_db);dst.row_factory=sqlite3.Row
    try:
        dst.execute('PRAGMA foreign_keys=OFF');dst.executescript((artifacts_root/'02_SCHEMA.sql').read_text())
        for table in ('config_registry','school_registry','pattern_definition_registry','interpretation_definition_registry','dataset_registry','dependency_registry','metadata'):_copy_table(src,dst,table)
        _copy_table(src,dst,'price_action_pattern_candidate',f'candidate_id IN (SELECT candidate_id FROM {ASSIGN_TABLE} WHERE root_month=?)',(spec.root_month,))
        _copy_table(src,dst,'price_action_pattern_state',f'candidate_id IN (SELECT candidate_id FROM {ASSIGN_TABLE} WHERE root_month=?)',(spec.root_month,))
        dst.commit();dst.execute('PRAGMA foreign_keys=ON');qc=dst.execute('PRAGMA quick_check').fetchone()[0];ic=dst.execute('PRAGMA integrity_check').fetchone()[0];fk=dst.execute('PRAGMA foreign_key_check').fetchall()
        if qc!='ok' or ic!='ok' or fk:raise RuntimeError(f'month shard sqlite validation failed qc={qc} ic={ic} fk={len(fk)}')
        counts={t:int(dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in ('price_action_pattern_candidate','price_action_pattern_state')}
        by_def={str(r[0]):int(r[1]) for r in dst.execute('SELECT definition_id,COUNT(*) FROM price_action_pattern_candidate GROUP BY definition_id')}
        times=dst.execute('SELECT MIN(event_time),MAX(event_time),MIN(availability_time),MAX(availability_time) FROM price_action_pattern_candidate').fetchone()
        logical={'price_action_pattern_candidate':logical_table_hash(dst,'price_action_pattern_candidate','candidate_id','candidate_hash'),'price_action_pattern_state':logical_table_hash(dst,'price_action_pattern_state','state_event_id','state_hash')}
    finally:dst.close();src.close()
    freeze=json.loads((artifacts_root/'DESIGN_FREEZE_MANIFEST.json').read_text());contract=json.loads((artifacts_root/'SHARDED_STORAGE_CONTRACT.json').read_text())
    shard_payload={'family':'pa7_chain','year':spec.year,'symbol':spec.symbol,'timeframe':spec.timeframe,'causal_root_window':spec.root_month,'partition_root_rule':contract['partitioning']['partition_root_rules']['pa7_chain'],'bucket_index':spec.bucket_index,'bucket_count':spec.bucket_count}
    base={'format_version':1,'status':'PASS','shard_id':'g8shard_'+stable_hash(shard_payload),**shard_payload,'file_size_bytes':output_db.stat().st_size,'sha256':sha256_file(output_db),'compressed_sha256':None,'table_row_counts':counts,'table_logical_sha256':logical,'definition_coverage':by_def,'min_event_time':times[0],'max_event_time':times[1],'min_availability_time':times[2],'max_availability_time':times[3],'upstream_lineage_id':freeze['logical_dependency_lineage_id'],'engine_sha256':sha256_file(artifacts_root/'code/moebot_group8_engine_v0_8_0.py'),'design_freeze_hash':freeze['design_freeze_hash'],'storage_contract_hash':contract['storage_contract_hash'],'oos_2024_accessed':spec.year==2024}
    base['manifest_hash']=stable_hash(base);manifest=_scope_manifest(base,boundary_scope);manifest['annual_breakout_followup_finalized']=True;manifest.pop('manifest_hash',None);manifest['manifest_hash']=stable_hash(manifest);return manifest


def run_onepass_bucket(*,staging_db:Path,work_db:Path,output_dir:Path,artifacts_root:Path,year:int,symbol:str,timeframe:str,root_months:list[str],bucket_count:int,bucket_index:int,boundary_scope:str)->dict[str,Any]:
    if boundary_scope not in SCOPES:raise ValueError(boundary_scope)
    months=sorted(set(root_months))
    if not months:raise ValueError('root_months empty')
    for month in months:
        y,m=month.split('-')
        if int(y)!=year or not 1<=int(m)<=12:raise ValueError(f'invalid root month:{month}')
    if year==2024:
        status=json.loads((artifacts_root/'STATUS.json').read_text())
        if status.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
    work_db.unlink(missing_ok=True);spec_all=ShardSpec(year,symbol,timeframe,None,bucket_count,bucket_index)
    engine=ScopedPA7ShardEngine(staging_db=staging_db,output_db=work_db,artifacts_root=artifacts_root,year=year,symbol=symbol,spec=spec_all,boundary_scope=boundary_scope)
    try:
        engine.load_bars();engine.retain_target_timeframe()
        if boundary_scope in {'group8_range','all'}:engine.process_bounded_ranges()
        engine.process_breakouts();engine.process_failed_breakouts_and_retests_fast();_finalize_breakout_followups(engine);engine.out.commit()
    finally:engine.close()
    assignment=_chain_assignments(work_db,year);unexpected=sorted(set(assignment['months'])-set(months))
    if unexpected:raise RuntimeError(f'one-pass emitted roots outside requested inventory:{unexpected}')
    output_dir.mkdir(parents=True,exist_ok=True);manifests=[]
    for month in months:
        pad=f'{bucket_index:03d}';cnt=f'{bucket_count:03d}';base=f'g8pa7_{year}_{timeframe}_{boundary_scope}_{month}_b{pad}of{cnt}';db=output_dir/f'{base}.sqlite';mp=output_dir/f'{base}.manifest.json';spec=ShardSpec(year,symbol,timeframe,month,bucket_count,bucket_index);manifest=_export_month(work_db=work_db,output_db=db,artifacts_root=artifacts_root,spec=spec,boundary_scope=boundary_scope);mp.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');manifests.append({'root_month':month,'database':str(db),'manifest':str(mp),'shard_id':manifest['shard_id'],'table_row_counts':manifest['table_row_counts'],'table_logical_sha256':manifest['table_logical_sha256'],'manifest_hash':manifest['manifest_hash'],'sha256':manifest['sha256']})
    rec={'format_version':1,'status':'PASS','year':year,'symbol':symbol,'timeframe':timeframe,'boundary_scope':boundary_scope,'bucket_count':bucket_count,'bucket_index':bucket_index,'root_months':months,'assignment':assignment,'shards':manifests,'one_engine_pass_for_all_root_months':True,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable_hash(rec);return rec


def main()->int:
    if os.environ.get('GITHUB_RUN_ID') in SUPERSEDED_GITHUB_RUN_IDS:
        raise RuntimeError(f'superseded GitHub Actions run blocked:{os.environ.get("GITHUB_RUN_ID")}')
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--work-db',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--timeframe',required=True);p.add_argument('--root-month',action='append',required=True);p.add_argument('--bucket-count',type=int,required=True);p.add_argument('--bucket-index',type=int,required=True);p.add_argument('--boundary-scope',choices=sorted(SCOPES),required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();r=run_onepass_bucket(staging_db=a.staging_db.resolve(),work_db=a.work_db.resolve(),output_dir=a.output_dir.resolve(),artifacts_root=a.artifacts_root.resolve(),year=a.year,symbol=a.symbol,timeframe=a.timeframe,root_months=a.root_month,bucket_count=a.bucket_count,bucket_index=a.bucket_index,boundary_scope=a.boundary_scope);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':r['status'],'shards':len(r['shards']),'report_hash':r['report_hash']},indent=2,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
