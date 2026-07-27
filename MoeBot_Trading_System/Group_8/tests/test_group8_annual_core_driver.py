#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine,CORE_PATTERN_DEFINITIONS,CORE_INTERPRETATION_DEFINITIONS,CORE_HYPOTHESIS_DEFINITIONS
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import make_stage,ART


def rows(db:Path,table:str,id_col:str,hash_col:str,defs:set[str]):
    con=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in defs)
        return {(str(r[0]),str(r[1])) for r in con.execute(f'SELECT {id_col},{hash_col} FROM {table} WHERE definition_id IN ({q})',tuple(sorted(defs)))}
    finally:con.close()

class AnnualCoreDriverParity(unittest.TestCase):
    def test_core_owned_domain_rows_equal_full_reference_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);stage=td/'stage.sqlite';refdb=td/'reference.sqlite';coredb=td/'core.sqlite';make_stage(stage)
            ref=Group8Engine(staging_db=stage,output_db=refdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:
                result=ref.run();self.assertEqual(result['status'],'PASS')
            finally:ref.close()
            core=AnnualCoreEngine(staging_db=stage,output_db=coredb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:
                result=core.run_core();self.assertEqual(result['status'],'PASS')
            finally:core.close()
            for table,idc,hashc,defs in [
                ('price_action_pattern_candidate','candidate_id','candidate_hash',CORE_PATTERN_DEFINITIONS),
                ('school_interpretation','interpretation_id','interpretation_hash',CORE_INTERPRETATION_DEFINITIONS),
                ('narrative_hypothesis','hypothesis_id','hypothesis_hash',CORE_HYPOTHESIS_DEFINITIONS),
            ]:
                self.assertEqual(rows(coredb,table,idc,hashc,defs),rows(refdb,table,idc,hashc,defs),table)

    def test_core_contains_no_deferred_definition(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);stage=td/'stage.sqlite';coredb=td/'core.sqlite';make_stage(stage)
            core=AnnualCoreEngine(staging_db=stage,output_db=coredb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:core.run_core()
            finally:core.close()
            con=sqlite3.connect(coredb)
            try:
                expected=set(CORE_PATTERN_DEFINITIONS)|set(CORE_INTERPRETATION_DEFINITIONS)|set(CORE_HYPOTHESIS_DEFINITIONS)
                actual=set()
                for t in ('price_action_pattern_candidate','school_interpretation','narrative_hypothesis'):
                    actual|={str(r[0]) for r in con.execute(f'SELECT DISTINCT definition_id FROM {t}')}
                self.assertLessEqual(actual,expected)
            finally:con.close()

if __name__=='__main__':unittest.main()
