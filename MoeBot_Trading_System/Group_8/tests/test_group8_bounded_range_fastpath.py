#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from moebot_group8_engine_v0_8_0 import Group8Engine
from group8_bounded_range_fastpath import IndexedBoundedRangeEngine
from test_group8_engine_v0_8_0 import ART,make_stage


def rows(db:Path):
    con=sqlite3.connect(db)
    try:return {(str(r[0]),str(r[1])) for r in con.execute("SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'")}
    finally:con.close()

class BoundedRangeFastPathParity(unittest.TestCase):
    def test_fast_path_matches_frozen_reference_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';refdb=t/'ref.sqlite';fastdb=t/'fast.sqlite';make_stage(stage)
            ref=Group8Engine(staging_db=stage,output_db=refdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:ref.load_bars();ref.process_bounded_ranges()
            finally:ref.close()
            fast=IndexedBoundedRangeEngine(staging_db=stage,output_db=fastdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:fast.load_bars();fast.process_bounded_ranges_fast()
            finally:fast.close()
            self.assertEqual(rows(refdb),rows(fastdb));self.assertGreater(len(rows(refdb)),0)

if __name__=='__main__':unittest.main()
