#!/usr/bin/env python3
from __future__ import annotations
import tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shard_runtime import bucket_for_id,stable_hash,atomic_json,verify_self_hash,HARD_RAW,raw_shard_gate

class RuntimeTests(unittest.TestCase):
    def test_bucket_is_deterministic(self):
        self.assertEqual(bucket_for_id("abc",32),bucket_for_id("abc",32))
    def test_self_hash(self):
        x={"status":"PASS"};x["report_hash"]=stable_hash(x);verify_self_hash(x,"report_hash")
    def test_hard_guard(self):
        with self.assertRaises(RuntimeError):raw_shard_gate(HARD_RAW+1)
    def test_atomic_json(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x.json";atomic_json(p,{"a":1});self.assertTrue(p.exists())
if __name__=="__main__":unittest.main(verbosity=2)
