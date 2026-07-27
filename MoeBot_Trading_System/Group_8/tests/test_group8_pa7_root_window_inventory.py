#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from group8_pa7_shard_executor import ShardSpec,epoch_month
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_scoped_shard_executor import ScopedPA7ShardEngine
from test_group8_engine_v0_8_0 import ART,make_stage


def candidates(db:Path):
    c=sqlite3.connect(db)
    try:return {r[0]:r[1] for r in c.execute('SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate')}
    finally:c.close()

class RootWindowCompleteness(unittest.TestCase):
    def test_observed_root_windows_partition_every_scoped_candidate_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage)
            for tf in ('M15','H1'):
                for scope in ('upstream','group8_range'):
                    probe=t/f'probe_{tf}_{scope}.sqlite';spec=ShardSpec(2023,'XAUUSD_',tf,None,1,0)
                    e=ScopedPA7ShardEngine(staging_db=stage,output_db=probe,artifacts_root=ART,year=2023,symbol='XAUUSD_',spec=spec,boundary_scope=scope)
                    try:
                        e.load_bars();e.retain_target_timeframe()
                        if scope=='group8_range':e.process_bounded_ranges()
                        windows=sorted({epoch_month(int(r['event'])) for r in e._pa7_boundary_catalog('XAUUSD_',tf)})
                    finally:e.close()
                    full=t/f'full_{tf}_{scope}.sqlite';fullm=t/f'full_{tf}_{scope}.json'
                    run_annual_pa7_shard(staging_db=stage,work_db=t/f'fw_{tf}_{scope}.sqlite',output_db=full,artifacts_root=ART,spec=spec,boundary_scope=scope,manifest_path=fullm)
                    expected=candidates(full);union={}
                    for month in windows:
                        out=t/f'{tf}_{scope}_{month}.sqlite';man=t/f'{tf}_{scope}_{month}.json'
                        run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{month}.sqlite',output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,month,1,0),boundary_scope=scope,manifest_path=man)
                        for cid,h in candidates(out).items():
                            self.assertNotIn(cid,union);union[cid]=h
                    self.assertEqual(expected,union,(tf,scope,windows))

if __name__=='__main__':unittest.main()
