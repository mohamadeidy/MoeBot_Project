#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from moebot_group8_engine_v0_8_0 import Group8Engine
from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_catalog import build_catalog
from group8_pa7_derived_executor import PA7DerivedEngine,DERIVED_INTERPRETATIONS,DERIVED_HYPOTHESES
from test_group8_engine_v0_8_0 import ART,make_stage

def rows(db,table,idc,hashc,defs):
    c=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in defs);return {(r[0],r[1]) for r in c.execute(f'SELECT {idc},{hashc} FROM {table} WHERE definition_id IN ({q})',tuple(sorted(defs)))}
    finally:c.close()

class PA7DerivedLayerParity(unittest.TestCase):
    def test_catalog_driven_derived_rows_match_full_reference_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';refdb=t/'ref.sqlite';coredb=t/'core.sqlite';cat=t/'pa7cat.sqlite';make_stage(stage)
            ref=Group8Engine(staging_db=stage,output_db=refdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:self.assertEqual(ref.run()['status'],'PASS')
            finally:ref.close()
            core=AnnualCoreEngine(staging_db=stage,output_db=coredb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:self.assertEqual(core.run_core()['status'],'PASS')
            finally:core.close()
            shards=[]
            for tf in ('M15','H1'):
                for scope in ('upstream','group8_range'):
                    for bucket in range(4):
                        work=t/f'w_{tf}_{scope}_{bucket}.sqlite';out=t/f's_{tf}_{scope}_{bucket}.sqlite';man=t/f'm_{tf}_{scope}_{bucket}.json'
                        run_annual_pa7_shard(staging_db=stage,work_db=work,output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,bucket),boundary_scope=scope,manifest_path=man);shards.append(out)
            cr=build_catalog(shards,cat);self.assertEqual(cr['status'],'PASS')
            d=PA7DerivedEngine(staging_db=stage,output_db=coredb,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:self.assertEqual(d.run_derived()['status'],'PASS')
            finally:d.close()
            self.assertEqual(rows(coredb,'school_interpretation','interpretation_id','interpretation_hash',DERIVED_INTERPRETATIONS),rows(refdb,'school_interpretation','interpretation_id','interpretation_hash',DERIVED_INTERPRETATIONS))
            self.assertEqual(rows(coredb,'narrative_hypothesis','hypothesis_id','hypothesis_hash',DERIVED_HYPOTHESES),rows(refdb,'narrative_hypothesis','hypothesis_id','hypothesis_hash',DERIVED_HYPOTHESES))

if __name__=='__main__':unittest.main()
