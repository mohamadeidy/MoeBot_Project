#!/usr/bin/env python3
"""Run one Group 8 engine stage for performance diagnosis without changing frozen code.

This wrapper imports the exact frozen engine, rebuilds only its in-memory bar
state when needed, executes exactly one named stage against a disposable output
SQLite, commits it, and emits timing/count evidence. It is diagnostic tooling,
not an alternative Group 8 implementation or annual validation path.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--group8-root',type=Path,required=True)
    p.add_argument('--staging-db',type=Path,required=True)
    p.add_argument('--output-db',type=Path,required=True)
    p.add_argument('--year',type=int,required=True)
    p.add_argument('--stage',required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    root=a.group8_root.resolve()
    sys.path.insert(0,str(root/'code'))
    from moebot_group8_engine_v0_8_0 import Group8Engine
    from group8_postprocess_v0_8_0 import finalize_postprocessing

    stages={
        'load_bars':'load_bars',
        'base_price_action':'process_base_price_action',
        'dow':'process_dow',
        'bounded_ranges':'process_bounded_ranges',
        'breakouts':'process_breakouts',
        'context_rejections':'process_context_rejections',
        'failed_breakouts_retests':'process_failed_breakouts_and_retests',
        'structural_narratives':'process_structural_narratives',
        'wyckoff':'process_wyckoff',
        'ict':'process_ict',
        'cross_school_mtf':'process_cross_school_and_mtf',
    }
    if a.stage not in stages and a.stage not in {'lifecycle_persistence','audit'}:
        raise SystemExit(f'unknown diagnostic stage:{a.stage}')

    engine=Group8Engine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=root,year=a.year)
    start=time.monotonic();detail={}
    try:
        if a.stage=='load_bars':
            engine.load_bars()
            detail['bar_count']=sum(len(v) for v in engine.bars_by_tf.values())
            detail['series_count']=len(engine.bars_by_tf)
        else:
            # Later stages depend on in-memory bar/ATR indices, but loading them is
            # read-only and deterministic. Its time is excluded from stage_elapsed.
            load_start=time.monotonic();engine.load_bars();detail['load_bars_seconds']=time.monotonic()-load_start
            start=time.monotonic()
            if a.stage=='lifecycle_persistence':
                detail['persistence_report']=finalize_postprocessing(engine)
            elif a.stage=='audit':
                detail['audit']=engine.audit(require_all_definitions_producible=False)
            else:
                getattr(engine,stages[a.stage])()
        elapsed=time.monotonic()-start
        engine.out.commit()
        counts={}
        for table in ('price_action_pattern_candidate','price_action_pattern_state','school_interpretation','narrative_hypothesis','hypothesis_lifecycle_event','invalidation_record','shared_evidence','conflicting_evidence','multi_timeframe_context_relation','evidence_chain'):
            try: counts[table]=int(engine.out.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.Error: counts[table]=None
        report={'format_version':1,'status':'PASS','year':a.year,'stage':a.stage,'stage_elapsed_seconds':elapsed,'output_counts':counts,'detail':detail}
    except Exception as exc:
        report={'format_version':1,'status':'FAIL','year':a.year,'stage':a.stage,'stage_elapsed_seconds':time.monotonic()-start,'error_type':type(exc).__name__,'error':str(exc),'detail':detail}
        raise
    finally:
        try: engine.close()
        finally:
            a.report.parent.mkdir(parents=True,exist_ok=True)
            a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
            print(json.dumps(report,indent=2,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
