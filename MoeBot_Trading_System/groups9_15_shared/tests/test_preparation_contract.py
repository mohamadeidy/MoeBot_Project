#!/usr/bin/env python3
from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class PrepContractTests(unittest.TestCase):
    def test_every_group_is_preparation_only(self):
        for g in range(9,16):
            s=json.loads((ROOT/f"Group_{g}"/"STATUS.json").read_text())
            self.assertEqual(s["status"],"PREPARED_NOT_AUTHORIZED")
            self.assertFalse(s["real_execution_authorized"])
    def test_shared_contract_locks_c_floor_and_free_only(self):
        c=json.loads((ROOT/"GROUPS_9_15_SHARED_CONTRACT.json").read_text())
        self.assertTrue(c["free_only"])
        self.assertEqual(c["storage_policy"]["c_free_safety_floor_gib"],120)
        self.assertTrue(c["execution_policy"]["monolithic_annual_materialization_forbidden"])
        self.assertTrue(c["storage_policy"]["visual_full_population_screenshots_forbidden"])
if __name__=="__main__":unittest.main(verbosity=2)
