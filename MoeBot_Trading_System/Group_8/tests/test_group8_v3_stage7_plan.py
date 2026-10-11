#!/usr/bin/env python3
from __future__ import annotations
import unittest
from group8_v3_stage7_plan import _choose_bucket_plan

class Stage7PlanTests(unittest.TestCase):
    def test_adaptive_bucket_plan_is_lossless_and_power_of_two(self):
        roots=[
            {"root_id":f"r{i}","interpretations":100+i,"evidence_chain_rows":2*(100+i)}
            for i in range(20)
        ]
        n,b=_choose_bucket_plan(
            roots,
            bytes_for_root=lambda r:r["interpretations"]*1000,
            size_safety_factor=1.5,
            soft_target_bytes=200000,
        )
        self.assertEqual(n & (n-1),0)
        self.assertEqual(sum(x["interpretations"] for x in b),sum(x["interpretations"] for x in roots))
        self.assertEqual(sum(x["evidence_chain_rows"] for x in b),sum(x["evidence_chain_rows"] for x in roots))
        self.assertTrue(all(x["guarded_projected_raw_bytes"]<=200000 for x in b))

    def test_single_small_window_stays_one_bucket(self):
        roots=[{"root_id":"x","interpretations":10,"evidence_chain_rows":20}]
        n,b=_choose_bucket_plan(
            roots,bytes_for_root=lambda r:1000,size_safety_factor=1.5,soft_target_bytes=10000
        )
        self.assertEqual(n,1);self.assertEqual(len(b),1);self.assertEqual(b[0]["bucket_index"],0)

if __name__=="__main__":unittest.main()
