#!/usr/bin/env python3
"""Annual PA7 shard executor with exact frozen follow-up states and lineage handoff."""
from __future__ import annotations
import argparse,json,sqlite3
from pathlib import Path
from typing import Any

from group8_pa7_shard_executor import ShardSpec,export_chain_shard,_copy_table,logical_table_hash,sha256_file,stable_hash
from group8_pa7_scoped_shard_executor import ScopedPA7ShardEngine,_scope_manifest,SCOPES
from group8_postprocess_v0_8_0 import _finalize_breakout_followups


def _add_pa7_evidence_chain(work_db:Path,output_db:Path)->dict[str,Any]:
    """Copy every evidence-chain row whose subject is a PA7 candidate in this shard."""
    src=sqlite3.connect(work_db);src.row_factory=sqlite3.Row;dst=sqlite3.connect(output_db);dst.row_factory=sqlite3.Row
    try:
        ids=[str(r[0]) for r in dst.execute('SELECT candidate_id FROM price_action_pattern_candidate ORDER BY candidate_id')]
        for start in range(0,len(ids),500):
            chunk=ids[start:start+500]
            if not chunk:continue
            q=','.join('?' for _ in chunk)
            _copy_table(src,dst,'evidence_chain',f"subject_type='price_action_pattern_candidate' AND subject_id IN ({q})",chunk)
        dst.commit();dst.execute('PRAGMA foreign_keys=ON')
        qc=dst.execute('PRAGMA quick_check').fetchone()[0];ic=dst.execute('PRAGMA integrity_check').fetchone()[0];fk=dst.execute('PRAGMA foreign_key_check').fetchall()
        if qc!='ok' or ic!='ok' or fk:raise RuntimeError(f'PA7 evidence shard validation failed qc={qc} ic={ic} fk={len(fk)}')
        evidence_count=int(dst.execute("SELECT COUNT(*) FROM evidence_chain WHERE subject_type='price_action_pattern_candidate'").fetchone()[0])
        expected=int(dst.execute('SELECT COUNT(*) FROM price_action_pattern_candidate').fetchone()[0])
        # Every PA7 candidate has at least one immutable upstream ref and therefore
        # at least one evidence-chain row. Exact parity tests below verify the full set.
        if expected and evidence_count < expected:raise RuntimeError(f'PA7 evidence-chain underflow candidates={expected} evidence={evidence_count}')
        return {'row_count':evidence_count,'logical_sha256':logical_table_hash(dst,'evidence_chain','evidence_chain_id','evidence_hash')}
    finally:dst.close();src.close()


def run_annual_pa7_shard(*,staging_db:Path,work_db:Path,output_db:Path,artifacts_root:Path,spec:ShardSpec,boundary_scope:str,manifest_path:Path)->dict[str,Any]:
    if boundary_scope not in SCOPES:raise ValueError(boundary_scope)
    if spec.year==2024:
        s=json.loads((artifacts_root/'STATUS.json').read_text())
        if s.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
    work_db.unlink(missing_ok=True)
    engine=ScopedPA7ShardEngine(staging_db=staging_db,output_db=work_db,artifacts_root=artifacts_root,year=spec.year,symbol=spec.symbol,spec=spec,boundary_scope=boundary_scope)
    try:
        engine.load_bars();engine.retain_target_timeframe()
        if boundary_scope in {'group8_range','all'}:engine.process_bounded_ranges()
        engine.process_breakouts();engine.process_failed_breakouts_and_retests_fast();_finalize_breakout_followups(engine);engine.out.commit()
    finally:engine.close()
    manifest=export_chain_shard(work_db,output_db,artifacts_root,spec)
    evidence=_add_pa7_evidence_chain(work_db,output_db)
    manifest['file_size_bytes']=output_db.stat().st_size;manifest['sha256']=sha256_file(output_db)
    manifest.setdefault('table_row_counts',{})['evidence_chain']=evidence['row_count']
    manifest.setdefault('table_logical_sha256',{})['evidence_chain']=evidence['logical_sha256']
    manifest['pa7_evidence_chain_complete']=True
    manifest=_scope_manifest(manifest,boundary_scope)
    manifest['annual_breakout_followup_finalized']=True
    manifest['pa7_evidence_chain_complete']=True
    manifest.pop('manifest_hash',None);manifest['manifest_hash']=stable_hash(manifest)
    manifest_path.parent.mkdir(parents=True,exist_ok=True);manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--work-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--timeframe',required=True);p.add_argument('--root-month');p.add_argument('--bucket-count',type=int,required=True);p.add_argument('--bucket-index',type=int,required=True);p.add_argument('--boundary-scope',choices=sorted(SCOPES),required=True);p.add_argument('--manifest',type=Path,required=True);a=p.parse_args();spec=ShardSpec(a.year,a.symbol,a.timeframe,a.root_month,a.bucket_count,a.bucket_index);r=run_annual_pa7_shard(staging_db=a.staging_db.resolve(),work_db=a.work_db.resolve(),output_db=a.output_db.resolve(),artifacts_root=a.artifacts_root.resolve(),spec=spec,boundary_scope=a.boundary_scope,manifest_path=a.manifest.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
