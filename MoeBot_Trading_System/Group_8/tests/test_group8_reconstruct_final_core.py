#!/usr/bin/env python3
from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_relevant_catalog import init_catalog,append_pass1,append_pass2
from group8_reconstruct_final_core import reconstruct
from test_group8_engine_v0_8_0 import ART,make_stage

class ReconstructionDriverTest(unittest.TestCase):
 def test_two_clean_reconstructions_have_identical_logical_fingerprint(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';base=t/'base.sqlite';cat=t/'cat.sqlite';make_stage(stage)
   e=AnnualCoreEngine(staging_db=stage,output_db=base,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(e.run_core()['status'],'PASS')
   finally:e.close()
   init_catalog(base,cat);shards=[]
   for tf in ('M15','H1'):
    for scope in ('upstream','group8_range'):
     for b in range(4):
      db=t/f's_{tf}_{scope}_{b}.sqlite';run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=t/f'm_{tf}_{scope}_{b}.json');shards.append(db)
   for i,db in enumerate(shards):append_pass1(cat,db,f's{i}')
   for i,db in enumerate(shards):append_pass2(cat,db,f's{i}')
   a=reconstruct(staging_db=stage,base_core_db=base,output_db=t/'a.sqlite',pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_',report_path=t/'a.json')
   b=reconstruct(staging_db=stage,base_core_db=base,output_db=t/'b.sqlite',pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_',report_path=t/'b.json')
   self.assertEqual(a['status'],'PASS');self.assertEqual(b['status'],'PASS');self.assertEqual(a['logical_sha256'],b['logical_sha256']);self.assertEqual(a['unresolved_group8_reference_count'],0);self.assertTrue(a['no_trading_outputs']);self.assertEqual(a['causality'],'PASS')

if __name__=='__main__':unittest.main()
