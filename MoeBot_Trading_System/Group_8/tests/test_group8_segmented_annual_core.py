#!/usr/bin/env python3
from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_sqlite_fingerprint import fingerprint
from test_group8_engine_v0_8_0 import ART,make_stage

class SegmentedAnnualCoreParity(unittest.TestCase):
 def test_segmented_core_matches_one_shot_logical_fingerprint_exactly(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';ref=t/'ref.sqlite';seg=t/'seg.sqlite';make_stage(stage)
   e=AnnualCoreEngine(staging_db=stage,output_db=ref,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(e.run_core()['status'],'PASS')
   finally:e.close()
   intervals=((0,2),(3,4),(5,6),(7,7));reports=[]
   for a,b in intervals:reports.append(run_segment(staging_db=stage,output_db=seg,artifacts_root=ART,year=2023,symbol='XAUUSD_',start=a,end=b))
   self.assertFalse(reports[0]['complete']);self.assertTrue(reports[-1]['complete'])
   rf=fingerprint(ref);sf=fingerprint(seg);self.assertEqual(sf['logical_sha256'],rf['logical_sha256'])
   self.assertEqual({k:v['logical_sha256'] for k,v in sf['tables'].items()},{k:v['logical_sha256'] for k,v in rf['tables'].items()})
   self.assertEqual({k:v['row_count'] for k,v in sf['tables'].items()},{k:v['row_count'] for k,v in rf['tables'].items()})

 def test_segment_cannot_skip_preceding_checkpoint(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';out=t/'out.sqlite';make_stage(stage)
   with self.assertRaisesRegex(RuntimeError,'missing preceding checkpoint'):
    run_segment(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_',start=3,end=3)

if __name__=='__main__':unittest.main()
