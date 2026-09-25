#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_cross_year_validate import validate

class V3CrossYearTests(unittest.TestCase):
 def test_descriptive_count_drift_is_allowed(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td)
   a23={"status":"ANNUAL_2023_PASS","validated_commit":"c","causality":"PASS","no_lookahead":"PASS","no_trading_outputs":True,"stage6":{"table_row_counts":{"x":1}},"stage7":{"table_row_counts":{"y":2},"definition_coverage":{"d":2}}};a23["manifest_hash"]=stable_hash(a23)
   fr={"status":"FROZEN_FOR_2024_OOS_V3","validated_commit":"c","oos_tooling_commit":"tool","annual_2023_manifest_hash":a23["manifest_hash"]};fr["manifest_hash"]=stable_hash(fr)
   a24={"status":"ANNUAL_2024_OOS_PASS","validated_commit":"c","oos_tooling_commit":"tool","freeze_manifest_hash":fr["manifest_hash"],"causality":"PASS","no_lookahead":"PASS","no_trading_outputs":True,"frozen_identity_drift":False,"oos_conditioned_semantic_changes":False,"stage6":{"table_row_counts":{"x":5}},"stage7":{"table_row_counts":{"y":9},"definition_coverage":{"d":9}}};a24["manifest_hash"]=stable_hash(a24)
   for n,x in (("a23",a23),("fr",fr),("a24",a24)):(td/f"{n}.json").write_text(json.dumps(x))
   r=validate(annual23_path=td/"a23.json",annual24_path=td/"a24.json",freeze_path=td/"fr.json",output=td/"out.json")
   self.assertEqual(r["status"],"PASS");self.assertEqual(r["descriptive_counts"]["2024"]["stage6"]["x"],5);self.assertEqual(r["validated_commit"],"c");self.assertEqual(r["oos_tooling_commit"],"tool")

if __name__=="__main__":unittest.main()
