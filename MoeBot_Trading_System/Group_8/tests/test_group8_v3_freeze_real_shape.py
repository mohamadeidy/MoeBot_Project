#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_freeze_oos_2024 import _bucket_policy

class FreezeRealShapeTests(unittest.TestCase):
 def test_stage6_specs_shape_converts_to_policy(self):
  s6={"specs":[{"timeframe":"M15","root_month":"2023-01","bucket_count":8,"bucket_index":0},{"timeframe":"M15","root_month":"2023-01","bucket_count":8,"bucket_index":1}]}
  p=_bucket_policy({"shards":[{**x,"family":"range_chain"} for x in s6["specs"]]})
  self.assertEqual(p["range_chain:M15:01"],8)

if __name__=="__main__":unittest.main()
