#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_cross_year_validate import validate

class V3CrossYearTests(unittest.TestCase):
 def _a23(self):
  r={"status":"ANNUAL_2023_PASS","validated_commit":"c","causality":"PASS","no_lookahead":"PASS","no_trading_outputs":True,
     "complete_logical_annual_dataset":True,"full_surface":{"receipt_hash":"f23"},
     "stage6":{"table_row_counts":{"x":1}},"stage7":{"table_row_counts":{"y":2},"definition_coverage":{"d":2}}}
  r["manifest_hash"]=stable_hash(r);return r

 def _a24(self,freeze_hash,tool="tool",amended=False):
  r={"status":"ANNUAL_2024_OOS_PASS","validated_commit":"c","oos_tooling_commit":tool,"freeze_manifest_hash":freeze_hash,
     "causality":"PASS","no_lookahead":"PASS","no_trading_outputs":True,"frozen_identity_drift":False,
     "oos_conditioned_semantic_changes":False,"complete_logical_annual_dataset":True,
     "full_surface":{"receipt_hash":"f24"},"stage6":{"table_row_counts":{"x":5}},
     "stage7":{"table_row_counts":{"y":9},"definition_coverage":{"d":9}}}
  if amended:
   r["post_freeze_physical_tooling_amendment"]=True
   r["prior_pre_oos_freeze_manifest_hash"]="prior"
  r["manifest_hash"]=stable_hash(r);return r

 def test_descriptive_count_drift_is_allowed(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);a23=self._a23()
   fr={"status":"FROZEN_FOR_2024_OOS_V3","validated_commit":"c","oos_tooling_commit":"tool","annual_2023_manifest_hash":a23["manifest_hash"]};fr["manifest_hash"]=stable_hash(fr)
   a24=self._a24(fr["manifest_hash"])
   for n,x in (("a23",a23),("fr",fr),("a24",a24)):(td/f"{n}.json").write_text(json.dumps(x))
   r=validate(annual23_path=td/"a23.json",annual24_path=td/"a24.json",freeze_path=td/"fr.json",output=td/"out.json")
   self.assertEqual(r["status"],"PASS")
   self.assertTrue(r["complete_logical_surface_both_years"])
   self.assertEqual(r["full_surface_receipt_hashes"],{"2023":"f23","2024":"f24"})
   self.assertEqual(r["descriptive_counts"]["2024"]["stage6"]["x"],5)
   self.assertEqual(r["validated_commit"],"c");self.assertEqual(r["oos_tooling_commit"],"tool")

 def test_missing_full_surface_fails_closed(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);a23=self._a23();a23.pop("complete_logical_annual_dataset");a23.pop("manifest_hash");a23["manifest_hash"]=stable_hash(a23)
   fr={"status":"FROZEN_FOR_2024_OOS_V3","validated_commit":"c","oos_tooling_commit":"tool","annual_2023_manifest_hash":a23["manifest_hash"]};fr["manifest_hash"]=stable_hash(fr)
   a24=self._a24(fr["manifest_hash"])
   for n,x in (("a23",a23),("fr",fr),("a24",a24)):(td/f"{n}.json").write_text(json.dumps(x))
   with self.assertRaises(RuntimeError):
    validate(annual23_path=td/"a23.json",annual24_path=td/"a24.json",freeze_path=td/"fr.json",output=td/"out.json")

 def test_disclosed_physical_tooling_amendment_preserves_semantic_pass(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);a23=self._a23()
   amendment={"type":"POST_FREEZE_PHYSICAL_TOOLING_REPAIR","prior_freeze_manifest_hash":"prior","oos_2024_accessed_before_amendment":True,
              "semantic_changes":False,"definition_changes":False,"schema_changes":False,"config_changes":False,"threshold_changes":False,
              "upstream_lineage_changes":False,"bucket_policy_changes":False,"observed_2024_values_used_for_tuning":False}
   fr={"status":"FROZEN_FOR_2024_OOS_V3","validated_commit":"c","oos_tooling_commit":"tool2","annual_2023_manifest_hash":a23["manifest_hash"],"post_freeze_physical_tooling_amendment":amendment};fr["manifest_hash"]=stable_hash(fr)
   a24=self._a24(fr["manifest_hash"],tool="tool2",amended=True)
   for n,x in (("a23",a23),("fr",fr),("a24",a24)):(td/f"{n}.json").write_text(json.dumps(x))
   r=validate(annual23_path=td/"a23.json",annual24_path=td/"a24.json",freeze_path=td/"fr.json",output=td/"out.json")
   self.assertTrue(r["post_freeze_physical_tooling_amendment"]);self.assertTrue(r["semantic_policy_unchanged_by_amendment"])

if __name__=="__main__":unittest.main()
