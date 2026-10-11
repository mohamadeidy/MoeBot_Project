#!/usr/bin/env python3
from __future__ import annotations
import json,shutil,subprocess,tempfile,unittest
from pathlib import Path
from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_archive_stage5 import archive_stage5
from group8_v3_freeze_oos_2024 import _bucket_policy

class V3Post2023Tests(unittest.TestCase):
 def test_bucket_policy_is_month_of_year_and_frozen(self):
  p={"shards":[
   {"family":"range_chain","timeframe":"M15","root_month":"2023-01","bucket_count":32},
   {"family":"range_chain","timeframe":"M15","root_month":"2023-02","bucket_count":16},
   {"family":"school_core","timeframe":"H1","root_month":"2023-01","bucket_count":2},
  ]}
  x=_bucket_policy(p)
  self.assertEqual(x["range_chain:M15:01"],32);self.assertEqual(x["range_chain:M15:02"],16);self.assertEqual(x["school_core:H1:01"],2)
 def test_bucket_policy_rejects_internal_drift(self):
  p={"shards":[{"family":"x","timeframe":"M15","root_month":"2023-01","bucket_count":2},{"family":"x","timeframe":"M15","root_month":"2023-01","bucket_count":4}]}
  with self.assertRaises(RuntimeError):_bucket_policy(p)
 def test_stage5_archive_roundtrip_if_zstd_available(self):
  z=shutil.which("zstd")
  if not z:self.skipTest("zstd unavailable")
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=td/"stage5.sqlite";db.write_bytes((b"abcdef123456"*100000))
   from moebot_group8_engine_v0_8_0 import sha256_file
   m={"status":"ANNUAL_2023_PASS","stage5":{"sha256":sha256_file(db)}};m["manifest_hash"]=stable_hash(m);mp=td/"annual.json";mp.write_text(json.dumps(m))
   r=archive_stage5(stage5_db=db,annual_manifest=mp,zstd_exe=Path(z),archive=td/"stage5.zst",report=td/"report.json",level=3,remove_raw=True)
   self.assertEqual(r["status"],"PASS");self.assertTrue(r["lossless_roundtrip_verified"]);self.assertTrue(r["raw_deleted"]);self.assertFalse(db.exists())

if __name__=="__main__":unittest.main()
