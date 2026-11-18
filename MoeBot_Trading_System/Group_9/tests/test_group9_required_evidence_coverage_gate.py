#!/usr/bin/env python3
"""Synthetic presence-gate regressions. No backtests or remote source writes."""
from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_required_evidence_coverage_gate.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("group9_presence_gate", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def fixtures():
    registry = {
        "status": "FROZEN", "registry_hash": "frozen-g9",
        "setup_families": {
            "WY": {
                "root_definitions": ["spring", "upthrust"],
                "ready_requirements": [
                    {"role": "context", "one_of": ["range"]},
                    {"role": "displacement", "by_root": {"spring": ["strength"], "upthrust": ["weakness"]}},
                    {"role": "last_point", "by_root": {"spring": ["support"], "upthrust": ["supply"]}},
                ],
            },
            "ICT": {
                "root_definitions": ["sweep"],
                "ready_requirements": [
                    {"role": "confirmation", "one_of": ["mss"]},
                    {"role": "poi", "one_of": ["imbalance", "block"]},
                ],
            },
        },
    }
    inventory = {
        "report_hash": "inventory-id",
        "candidate_count": 30,
        "counts_by_definition": {"spring": 15, "upthrust": 10, "sweep": 5},
    }
    benchmark = {
        "inventory_report_hash": "inventory-id",
        "report_hash": "benchmark-id",
        "semantic_registry_hash": "frozen-g9",
        "outcome_data_accessed": False,
        "trade_policy_accessed": False,
        "sample": {"allocations": [
            {"year": 2023, "family": "WY", "population": 25},
            {"year": 2024, "family": "ICT", "population": 5},
        ]},
    }
    counts = {
        (2023, "range"): 50, (2023, "strength"): 12,
        (2023, "weakness"): 10, (2023, "support"): 7,
        (2023, "supply"): 6, (2024, "mss"): 9,
        (2024, "imbalance"): 2, (2024, "block"): 0,
    }
    return inventory, benchmark, registry, counts


class CoverageGateTests(unittest.TestCase):
    def test_all_mandatory_roles_present_is_only_presence_pass(self):
        inv, bench, reg, counts = fixtures()
        r = mod.compute(inv, bench, reg, counts, (2023, 2024))
        self.assertEqual(r["status"], "PRESENCE_ONLY_PASS")
        self.assertEqual(r["all_family_roots"], 30)
        self.assertFalse(r["real_annual_execution_authorized"])
        self.assertFalse(r["full_production_support_coverage_verified"])
        self.assertTrue(r["presence_not_sufficient_for_causal_linkage"])

    def test_missing_wyckoff_sign_fails_closed_for_spring_only(self):
        inv, bench, reg, counts = fixtures()
        counts[(2023, "strength")] = 0
        r = mod.compute(inv, bench, reg, counts, (2023, 2024))
        self.assertEqual(r["status"], "BLOCKED_REQUIRED_DEFINITION_ABSENT")
        self.assertEqual(len(r["failures"]), 1)
        self.assertEqual(r["failures"][0]["root_population"], 15)
        self.assertEqual(r["failures"][0]["missing_mandatory_role"], "displacement")

    def test_disjunction_can_pass_when_one_definition_present(self):
        inv, bench, reg, counts = fixtures()
        counts[(2024, "imbalance")] = 0
        counts[(2024, "block")] = 4
        self.assertEqual(
            mod.compute(inv, bench, reg, counts, (2023, 2024))["status"],
            "PRESENCE_ONLY_PASS",
        )

    def test_missing_both_poi_variants_fails_closed(self):
        inv, bench, reg, counts = fixtures()
        counts[(2024, "imbalance")] = 0
        counts[(2024, "block")] = 0
        r = mod.compute(inv, bench, reg, counts, (2023, 2024))
        self.assertEqual(len(r["failures"]), 1)
        self.assertEqual(r["failures"][0]["root_population"], 5)

    def test_incomplete_root_definition_mapping_fails_closed(self):
        inv, bench, reg, counts = fixtures()
        del reg["setup_families"]["WY"]["ready_requirements"][1]["by_root"]["upthrust"]
        with self.assertRaisesRegex(ValueError, "missing_requirement_for_root"):
            mod.compute(inv, bench, reg, counts, (2023, 2024))

    def test_lineage_and_outcome_contamination_are_rejected(self):
        inv, bench, reg, counts = fixtures()
        bench["semantic_registry_hash"] = "different"
        with self.assertRaisesRegex(ValueError, "definition_registry_benchmark_drift"):
            mod.compute(inv, bench, reg, counts, (2023, 2024))
        bench["semantic_registry_hash"] = "frozen-g9"
        bench["outcome_data_accessed"] = True
        with self.assertRaisesRegex(ValueError, "outcome_or_trade_policy"):
            mod.compute(inv, bench, reg, counts, (2023, 2024))

    def test_multiyear_multi_root_population_requires_disaggregation(self):
        inv, bench, reg, counts = fixtures()
        bench["sample"]["allocations"].append({
            "year": 2024, "family": "WY", "population": 1,
        })
        inv["candidate_count"] = 31
        with self.assertRaisesRegex(ValueError, "per_year_root_definition_counts_required"):
            mod.compute(inv, bench, reg, counts, (2023, 2024))


if __name__ == "__main__":
    unittest.main(verbosity=2)
