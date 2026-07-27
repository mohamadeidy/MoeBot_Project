#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from group8_structural_narrative_fastpath import IndexedStructuralNarrativeEngine
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import ART,make_stage

PDEFS=('pa_structural_pullback','pa_continuation_after_pullback','pa_exhaustion_failed_breakout')
IDEFS=('dow_protected_pullback',)

def snapshot(db:Path)->dict[str,dict[str,str]]:
    con=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in PDEFS);hyp={r[0]:r[1] for r in con.execute(f'SELECT hypothesis_id,hypothesis_hash FROM narrative_hypothesis WHERE definition_id IN ({q})',PDEFS)}
        q=','.join('?' for _ in IDEFS);inter={r[0]:r[1] for r in con.execute(f'SELECT interpretation_id,interpretation_hash FROM school_interpretation WHERE definition_id IN ({q})',IDEFS)}
        return {'hypothesis':hyp,'interpretation':inter}
    finally:con.close()

def prep(engine:Group8Engine)->None:
    engine.load_bars();engine.process_base_price_action();engine.process_dow();engine.process_bounded_ranges();engine.process_breakouts();engine.process_failed_breakouts_and_retests()

class StructuralNarrativeFastPathTest(unittest.TestCase):
    def test_indexed_structural_narratives_match_reference_exactly(self)->None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);ref=t/'ref.sqlite';fast=t/'fast.sqlite'
            a=Group8Engine(staging_db=stage,output_db=ref,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:prep(a);a.process_structural_narratives()
            finally:a.close()
            b=IndexedStructuralNarrativeEngine(staging_db=stage,output_db=fast,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:prep(b);b.process_structural_narratives_fast()
            finally:b.close()
            self.assertEqual(snapshot(ref),snapshot(fast));self.assertGreater(sum(len(v) for v in snapshot(ref).values()),0)

if __name__=='__main__':unittest.main()
