#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_relevant_catalog import init_catalog,append_pass1,append_pass2
from group8_pa7_derived_executor import PA7DerivedEngine
from group8_global_finalizer import Group8GlobalFinalizer
from group8_cross_shard_reference_audit import audit
from test_group8_engine_v0_8_0 import ART,make_stage

class CrossShardRefAuditTest(unittest.TestCase):
 def test_final_core_refs_resolve_against_core_plus_relevant_pa7_catalog(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';coredb=t/'core.sqlite';cat=t/'cat.sqlite';make_stage(stage)
   e=AnnualCoreEngine(staging_db=stage,output_db=coredb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(e.run_core()['status'],'PASS')
   finally:e.close()
   init_catalog(coredb,cat);shards=[]
   for tf in ('M15','H1'):
    for scope in ('upstream','group8_range'):
     for b in range(4):
      db=t/f's_{tf}_{scope}_{b}.sqlite';run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=t/f'm_{tf}_{scope}_{b}.json');shards.append(db)
   for i,db in enumerate(shards):append_pass1(cat,db,f's{i}')
   for i,db in enumerate(shards):append_pass2(cat,db,f's{i}')
   d=PA7DerivedEngine(staging_db=stage,output_db=coredb,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(d.run_derived()['status'],'PASS')
   finally:d.close()
   g=Group8GlobalFinalizer(staging_db=stage,output_db=coredb,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(g.run_global_finalizer()['status'],'PASS')
   finally:g.close()
   r=audit(coredb,cat,t/'audit.json');self.assertEqual(r['status'],'PASS');self.assertEqual(r['unresolved_group8_reference_count'],0);self.assertGreater(r['checked_reference_count'],0)
   con=sqlite3.connect(coredb)
   try:
    row=con.execute("SELECT shared_evidence_id FROM shared_evidence WHERE lower(source_group)='group8' LIMIT 1").fetchone()
    if row is not None:
     con.execute("UPDATE shared_evidence SET source_type='price_action_pattern_candidate',source_id='g8_missing_shared_source' WHERE shared_evidence_id=?",(row[0],));con.commit()
   finally:con.close()
   if row is not None:
    with self.assertRaisesRegex(RuntimeError,'unresolved Group8 references'):audit(coredb,cat,t/'audit-bad.json')

if __name__=='__main__':unittest.main()
