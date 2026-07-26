#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from group8_context_rejection_fastpath import IndexedContextRejectionEngine
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import ART,make_stage

def rows(db:Path)->dict[str,str]:
    con=sqlite3.connect(db)
    try:return {r[0]:r[1] for r in con.execute("SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id='pa_context_linked_rejection'")}
    finally:con.close()

class ContextRejectionFastPathTest(unittest.TestCase):
    def test_indexed_fast_path_matches_reference_exactly(self)->None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);ref=t/'ref.sqlite';fast=t/'fast.sqlite'
            a=Group8Engine(staging_db=stage,output_db=ref,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:a.load_bars();a.process_base_price_action();a.process_bounded_ranges();a.process_context_rejections()
            finally:a.close()
            b=IndexedContextRejectionEngine(staging_db=stage,output_db=fast,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:b.load_bars();b.process_base_price_action();b.process_bounded_ranges();b.process_context_rejections_fast()
            finally:b.close()
            self.assertGreater(len(rows(ref)),0);self.assertEqual(rows(ref),rows(fast))

if __name__=='__main__':unittest.main()
