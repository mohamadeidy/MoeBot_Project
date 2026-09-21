#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_oos_2024_stage6 import _policy as p6
from group8_v3_oos_2024_stage7 import _policy as p7

class OOS2024PolicyTests(unittest.TestCase):
 def test_stage6_policy_uses_month_of_year_only(self):
  f={"stage6_bucket_policy_by_timeframe_month":{"range_chain:M15:01":32}}
  self.assertEqual(p6(f,"M15","2024-01"),32)
 def test_stage7_policy_is_family_specific(self):
  f={"stage7_bucket_policy_by_family_timeframe_month":{"range_chain:M15:01":32,"school_core:M15:01":4}}
  self.assertEqual(p7(f,"range_chain","M15","2024-01"),32);self.assertEqual(p7(f,"school_core","M15","2024-01"),4)
 def test_missing_oos_policy_fails_closed(self):
  with self.assertRaises(RuntimeError):p6({"stage6_bucket_policy_by_timeframe_month":{}},"M15","2024-01")
  with self.assertRaises(RuntimeError):p7({"stage7_bucket_policy_by_family_timeframe_month":{}},"range_chain","M15","2024-01")

if __name__=="__main__":unittest.main()
