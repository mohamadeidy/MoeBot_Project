#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_pa7_scoped_shard_executor import run_scoped_shard
from group8_pa7_shard_executor import CHAIN_DEFINITIONS, ShardSpec
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import ART, make_stage


def candidates(db: Path) -> dict[str, str]:
    con=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in CHAIN_DEFINITIONS)
        return {r[0]:r[1] for r in con.execute(f'SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ({q})',CHAIN_DEFINITIONS)}
    finally:con.close()


class PA7BoundaryScopeSplitTest(unittest.TestCase):
    def test_upstream_plus_group8_range_union_equals_monolithic(self)->None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';mono=t/'mono.sqlite';make_stage(stage)
            e=Group8Engine(staging_db=stage,output_db=mono,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:e.load_bars();e.process_bounded_ranges();e.process_breakouts();e.process_failed_breakouts_and_retests()
            finally:e.close()
            expected=candidates(mono);union:dict[str,str]={}
            for tf in ('M15','H1'):
                for scope in ('upstream','group8_range'):
                    for bucket in range(4):
                        out=t/f'{tf}-{scope}-{bucket}.sqlite'
                        run_scoped_shard(staging_db=stage,work_db=t/f'w-{tf}-{scope}-{bucket}.sqlite',output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,bucket),boundary_scope=scope,manifest_path=t/f'm-{tf}-{scope}-{bucket}.json')
                        for cid,h in candidates(out).items():
                            self.assertNotIn(cid,union,f'duplicate candidate across physical scopes: {cid}');union[cid]=h
            self.assertEqual(expected,union)

    def test_upstream_scope_does_not_create_bounded_range_support_rows(self)->None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);work=t/'work.sqlite';out=t/'out.sqlite'
            run_scoped_shard(staging_db=stage,work_db=work,output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',None,1,0),boundary_scope='upstream',manifest_path=t/'m.json')
            con=sqlite3.connect(work)
            try:self.assertEqual(con.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchone()[0],0)
            finally:con.close()

if __name__=='__main__':unittest.main()
