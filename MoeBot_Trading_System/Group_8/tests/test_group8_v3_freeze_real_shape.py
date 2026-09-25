#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_v3_freeze_oos_2024 import TOOLS,_bucket_policy,_lineage_commits

class FreezeRealShapeTests(unittest.TestCase):
 def test_post_annual_tooling_fix_does_not_rewrite_annual_validated_commit(self):
  annual_commit,tooling_commit=_lineage_commits({"validated_commit":"annual-2023"},"oos-tooling")
  self.assertEqual(annual_commit,"annual-2023")
  self.assertEqual(tooling_commit,"oos-tooling")
  self.assertNotEqual(annual_commit,tooling_commit)

 def test_all_frozen_identity_paths_exist_and_reference_resolution_matches_design_freeze(self):
  root=Path(__file__).resolve().parents[1]
  missing=[rel for rel in TOOLS if not (root/rel).is_file()]
  self.assertEqual(missing,[])
  design=json.loads((root/"DESIGN_FREEZE_MANIFEST.json").read_text())
  resolution=json.loads((root/"DESIGN_REFERENCE_RESOLUTION.json").read_text())
  self.assertEqual(design["reference_resolution_hash"],resolution["resolution_hash"])

 def test_stage6_specs_shape_converts_to_policy(self):
  s6={"specs":[{"timeframe":"M15","root_month":"2023-01","bucket_count":8,"bucket_index":0},{"timeframe":"M15","root_month":"2023-01","bucket_count":8,"bucket_index":1}]}
  p=_bucket_policy({"shards":[{**x,"family":"range_chain"} for x in s6["specs"]]})
  self.assertEqual(p["range_chain:M15:01"],8)

if __name__=="__main__":unittest.main()
