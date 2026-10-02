#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_full_surface_guard import REQUIRED_DOMAIN_TABLES,build_receipt,load_full_surface_receipt
def w(p,r):
 x=dict(r);x["report_hash"]=stable_hash(x);p.write_text(json.dumps(x));return x
class FullSurfaceGuardTests(unittest.TestCase):
 def test_build_and_reload(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);y=2023;s6=w(d/"s6",{"status":"PASS","stage":6,"year":y});s7=w(d/"s7",{"status":"PASS","stage":7,"year":y});pa=w(d/"pa",{"status":"PASS","year":y,"complete_once_only_coverage":True,"free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False});cov={t:{"verified":True} for t in REQUIRED_DOMAIN_TABLES};b=w(d/"b",{"status":"PASS","year":y,"stage6_union_report_hash":s6["report_hash"],"stage7_union_report_hash":s7["report_hash"],"domain_table_coverage":cov,"finalized_core_logical_sha256":"a"*64,"full_union_global_logical_sha256":"b"*64})
   for i in range(3):
    w(d/f"r{i}",{"status":"PASS","year":y,"causality":"PASS","no_trading_outputs":True,"unresolved_group8_reference_count":0,"free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,"logical_sha256":"a"*64});w(d/f"u{i}",{"status":"PASS","year":y,"full_annual_union":True,"unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,"registry_conflict_count":0,"free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,"global_logical_sha256":"b"*64})
   out=d/"o";r=build_receipt(year=y,stage6_union_path=d/"s6",stage7_union_path=d/"s7",pa7_release_path=d/"pa",reconstruction_report_paths=[d/f"r{i}" for i in range(3)],full_union_report_paths=[d/f"u{i}" for i in range(3)],binding_report_path=d/"b",output=out);self.assertTrue(r["complete_logical_annual_dataset"]);self.assertEqual(load_full_surface_receipt(out,year=y,stage6_union_report_hash=s6["report_hash"],stage7_union_report_hash=s7["report_hash"])["logical_fingerprint"],"b"*64)
if __name__=="__main__":unittest.main()
