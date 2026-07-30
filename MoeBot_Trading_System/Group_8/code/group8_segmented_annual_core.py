#!/usr/bin/env python3
"""Exact resumable Annual Core execution for FREE standard-runner time limits.

The frozen AnnualCoreEngine stages are unchanged. This driver only permits the same
stages to be executed in ordered segments against one persistent output SQLite. Each
new process silently reloads source bars to reconstruct in-memory ATR/bar indexes,
requires the immediately preceding persistent checkpoint before advancing, executes
only the requested frozen stages, and writes the same deterministic checkpoints.

Stage 4 has a physical-only deterministic partition mode. Individual partitions never
publish the stage checkpoint. Finalization verifies complete once-only partition
coverage before publishing the unchanged context_rejections_fast checkpoint.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any

from group8_annual_core_driver import AnnualCoreEngine,CORE_PATTERN_DEFINITIONS,CORE_INTERPRETATION_DEFINITIONS,CORE_HYPOTHESIS_DEFINITIONS
from group8_context_rejection_fastpath import STAGE4_PARTITION_COUNT
from group8_postprocess_v0_8_0 import checkpoint

STAGES=(
 ('load_bars','load_bars'),
 ('base_price_action','process_base_price_action'),
 ('dow','process_dow'),
 ('bounded_ranges','process_bounded_ranges'),
 ('context_rejections_fast','process_context_rejections_fast'),
 ('structural_narratives_fast','process_structural_narratives_fast'),
 ('wyckoff_core','process_wyckoff_core'),
 ('ict_core','process_ict'),
)


def _checkpoint_complete(e:AnnualCoreEngine,stage:str)->bool:
 expected={(s,tf) for s,tf in e.bars_by_tf}
 rows={(str(r[0]),str(r[1])) for r in e.out.execute("SELECT symbol,timeframe FROM processing_checkpoint WHERE stage=? AND status='PASS'",(stage,))}
 return rows==expected


def _validate_final_domain(e:AnnualCoreEngine)->dict[str,Any]:
 unexpected=[]
 for table in ('price_action_pattern_candidate','school_interpretation','narrative_hypothesis'):
  allowed=CORE_PATTERN_DEFINITIONS if table=='price_action_pattern_candidate' else CORE_INTERPRETATION_DEFINITIONS if table=='school_interpretation' else CORE_HYPOTHESIS_DEFINITIONS
  for row in e.out.execute(f'SELECT DISTINCT definition_id FROM {table} ORDER BY definition_id'):
   if str(row[0]) not in allowed:unexpected.append(f'{table}:{row[0]}')
 if unexpected:raise RuntimeError(f'annual core definition leakage:{unexpected}')
 return {
  'patterns':{d:int(e.out.execute('SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_PATTERN_DEFINITIONS)},
  'interpretations':{d:int(e.out.execute('SELECT COUNT(*) FROM school_interpretation WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_INTERPRETATION_DEFINITIONS)},
  'hypotheses':{d:int(e.out.execute('SELECT COUNT(*) FROM narrative_hypothesis WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_HYPOTHESIS_DEFINITIONS)},
 }


def run_segment(*,staging_db:Path,output_db:Path,artifacts_root:Path,year:int,symbol:str,start:int,end:int,stage4_partition:int|None=None,stage4_finalize:bool=False)->dict[str,Any]:
 if not (0<=start<=end<len(STAGES)):raise ValueError(f'invalid stage interval:{start}..{end}')
 if stage4_partition is not None and stage4_finalize:raise ValueError('partition execution and finalization are mutually exclusive')
 if (stage4_partition is not None or stage4_finalize) and (start!=4 or end!=4):raise ValueError('stage-4 partition operations require --start 4 --end 4')
 if stage4_partition is not None and not (0<=stage4_partition<STAGE4_PARTITION_COUNT):raise ValueError(f'invalid stage-4 partition:{stage4_partition}')
 if year==2024:
  status=json.loads((artifacts_root/'STATUS.json').read_text())
  if status.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
 e=AnnualCoreEngine(staging_db=staging_db,output_db=output_db,artifacts_root=artifacts_root,year=year,symbol=symbol)
 try:
  e.load_bars()
  if start>0 and not _checkpoint_complete(e,STAGES[start-1][0]):raise RuntimeError(f'missing preceding checkpoint:{STAGES[start-1][0]}')
  if stage4_partition is not None:
   receipt=e.process_context_rejections_fast(partition_index=stage4_partition)
   return {'format_version':1,'status':'PASS','year':year,'physical_role':'ANNUAL_CORE_STAGE4_PARTITION','stage':4,'partition_index':stage4_partition,'partition_count':STAGE4_PARTITION_COUNT,'receipt':receipt,'checkpoint_3_published':False,'free_only':True,'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':year==2024}
  if stage4_finalize:
   aggregate=e.verify_stage4_partition_coverage();checkpoint(e,STAGES[4][0])
   if not _checkpoint_complete(e,STAGES[4][0]):raise RuntimeError('stage-4 final checkpoint coverage incomplete')
   return {'format_version':1,'status':'PASS','year':year,'physical_role':'ANNUAL_CORE_STAGE4_FINALIZATION','stage':4,'partition_count':STAGE4_PARTITION_COUNT,'aggregate':aggregate,'checkpoint_3_published':True,'free_only':True,'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':year==2024}
  executed=[]
  for idx in range(start,end+1):
   stage,method=STAGES[idx]
   if idx==0:
    checkpoint(e,stage);executed.append(stage);continue
   if idx==4:raise RuntimeError('stage 4 must use deterministic partition execution and verified finalization')
   getattr(e,method)();checkpoint(e,stage);executed.append(stage)
  complete=end==len(STAGES)-1
  coverage=_validate_final_domain(e) if complete else None
  if complete:
   for stage,_ in STAGES:
    if not _checkpoint_complete(e,stage):raise RuntimeError(f'incomplete final checkpoint coverage:{stage}')
  return {'format_version':1,'status':'PASS','year':year,'physical_role':'ANNUAL_CORE_NON_PA7_SEGMENT','stage_start':start,'stage_end':end,'stage_names':executed,'complete':complete,'definition_coverage':coverage,'free_only':True,'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':year==2024}
 finally:e.close()


def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--start',type=int,required=True);p.add_argument('--end',type=int,required=True);p.add_argument('--stage4-partition',type=int);p.add_argument('--stage4-finalize',action='store_true');p.add_argument('--report',type=Path,required=True);a=p.parse_args();r=run_segment(staging_db=a.staging_db.resolve(),output_db=a.output_db.resolve(),artifacts_root=a.artifacts_root.resolve(),year=a.year,symbol=a.symbol,start=a.start,end=a.end,stage4_partition=a.stage4_partition,stage4_finalize=a.stage4_finalize);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
