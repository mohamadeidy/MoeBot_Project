#!/usr/bin/env python3
from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

class SemanticContractTests(unittest.TestCase):
    def _plan(self,g):
        return json.loads((ROOT/f"Group_{g}"/"PREPARATION_PLAN.json").read_text())
    def _defs(self,g):
        return json.loads((ROOT/f"Group_{g}"/"01_DEFINITION_REGISTRY_DRAFT.json").read_text())

    def test_group9_causality_and_no_policy(self):
        p=self._plan(9)
        joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("availability",joined)
        self.assertIn("future outcome",joined)
        self.assertIn("trade policy",joined)

    def test_group10_outcomes_cannot_rewrite_setup(self):
        p=self._plan(10); joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("setup availability",joined)
        self.assertIn("immutable",joined)
        self.assertIn("post-outcome",joined)

    def test_group11_no_bitmap_population(self):
        p=self._plan(11); joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("recipe",joined)
        self.assertIn("full population",joined)

    def test_group12_discovery_confirmation_separated(self):
        p=self._plan(12); joined=" ".join(p["semantic_rules"]).lower()
        self.assertIn("discovery and confirmation partitions distinct",joined)
        self.assertIn("cannot modify",joined)

    def test_group13_final_holdout_inaccessible(self):
        p=self._plan(13); joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("final holdout inaccessible",joined)
        self.assertIn("wait/buy/sell/hold/exit",joined)

    def test_group14_holdout_is_final_and_immutable(self):
        p=self._plan(14); joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("policy immutable",joined)
        self.assertIn("failed holdout remains evidence",joined)

    def test_group15_demo_precedes_live(self):
        p=self._plan(15); joined=" ".join(p["semantic_rules"]+p["forbidden"]).lower()
        self.assertIn("demo before gradual live",joined)
        self.assertIn("risk reservation precedes order",joined)
        self.assertIn("cannot self-modify",joined)

    def test_definitions_stay_unfrozen_during_preparation(self):
        for g in range(9,16):
            d=self._defs(g)
            self.assertEqual(d["status"],"DRAFT_NOT_FROZEN")
            self.assertFalse(d.get("thresholds_frozen",False))

if __name__=="__main__": unittest.main(verbosity=2)
