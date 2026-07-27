#!/usr/bin/env python3
"""Annual PA7 shard executor with exact frozen breakout follow-up lifecycle state."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any

from group8_pa7_shard_executor import ShardSpec,export_chain_shard
from group8_pa7_scoped_shard_executor import ScopedPA7ShardEngine,_scope_manifest,SCOPES
from group8_postprocess_v0_8_0 import _finalize_breakout_followups


def run_annual_pa7_shard(*,staging_db:Path,work_db:Path,output_db:Path,artifacts_root:Path,spec:ShardSpec,boundary_scope:str,manifest_path:Path)->dict[str,Any]:
    if boundary_scope not in SCOPES: raise ValueError(boundary_scope)
    if spec.year==2024:
        s=json.loads((artifacts_root/'STATUS.json').read_text())
        if s.get('annual_execution_2024_authorized') is not True: raise RuntimeError('2024 OOS is forbidden')
    work_db.unlink(missing_ok=True)
    engine=ScopedPA7ShardEngine(staging_db=staging_db,output_db=work_db,artifacts_root=artifacts_root,year=spec.year,symbol=spec.symbol,spec=spec,boundary_scope=boundary_scope)
    try:
        engine.load_bars();engine.retain_target_timeframe()
        if boundary_scope in {'group8_range','all'}: engine.process_bounded_ranges()
        engine.process_breakouts();engine.process_failed_breakouts_and_retests_fast()
        _finalize_breakout_followups(engine)
        engine.out.commit()
    finally: engine.close()
    manifest=export_chain_shard(work_db,output_db,artifacts_root,spec)
    manifest=_scope_manifest(manifest,boundary_scope)
    manifest['annual_breakout_followup_finalized']=True
    manifest['manifest_hash']=None
    from group8_pa7_shard_executor import stable_hash
    manifest.pop('manifest_hash',None);manifest['manifest_hash']=stable_hash(manifest)
    manifest_path.parent.mkdir(parents=True,exist_ok=True);manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--work-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--timeframe',required=True);p.add_argument('--root-month');p.add_argument('--bucket-count',type=int,required=True);p.add_argument('--bucket-index',type=int,required=True);p.add_argument('--boundary-scope',choices=sorted(SCOPES),required=True);p.add_argument('--manifest',type=Path,required=True);a=p.parse_args();spec=ShardSpec(a.year,a.symbol,a.timeframe,a.root_month,a.bucket_count,a.bucket_index);r=run_annual_pa7_shard(staging_db=a.staging_db.resolve(),work_db=a.work_db.resolve(),output_db=a.output_db.resolve(),artifacts_root=a.artifacts_root.resolve(),spec=spec,boundary_scope=a.boundary_scope,manifest_path=a.manifest.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
