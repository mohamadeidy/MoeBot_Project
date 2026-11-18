#!/usr/bin/env python3
"""Synthetic safety and determinism tests for the Group 9 scope sizing projection."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_scope_sizing.py"
spec = importlib.util.spec_from_file_location("group9_scope_sizing", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def fixture():
    inv = {
        "report_hash": "inventory-x",
        "semantic_registry_hash": "semantic-x",
        "candidate_count": 100,
        "scopes": [
            {"dataset_year": 2023, "symbol": "XAUUSD_", "timeframe": "H1", "root_month": "2023-01", "candidate_count": 60},
            {"dataset_year": 2024, "symbol": "XAUUSD_", "timeframe": "M15", "root_month": "2024-03", "candidate_count": 40},
        ],
        "counts_by_year": {"2023": 60, "2024": 40},
    }
    bench = {
        "report_hash": "benchmark-x",
        "inventory_report_hash": "inventory-x",
        "semantic_registry_hash": "semantic-x",
        "candidate_population": 100,
        "definition_version": "G9-SSI-1.0.0",
        "family_stats": {"fam": {"population": 100}},
        "projected_output_bytes": 10_000,
        "projected_total_seconds": 100.0,
        "largest_stage5_restore_bytes": 100_000,
        "outcome_data_accessed": False,
        "trade_policy_accessed": False,
    }
    return inv, bench


class SizingTests(unittest.TestCase):
    def test_projection_pass_but_never_execution(self):
        inv, bench = fixture()
        result = mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)
        self.assertEqual(result["status"], "PROJECTION_PASS")
        self.assertFalse(result["exact_shard_plan_authorized"])
        self.assertFalse(result["real_annual_execution_authorized"])
        self.assertEqual(sum(s["candidate_count"] for s in result["scopes"]), 100)

    def test_deterministic_plan_and_hash(self):
        inv, bench = fixture()
        a = mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)
        b = mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)
        self.assertEqual(a["report_hash"], b["report_hash"])

    def test_inventory_mismatch_rejected(self):
        inv, bench = fixture()
        inv["candidate_count"] = 101
        with self.assertRaisesRegex(ValueError, "population_mismatch"):
            mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)

    def test_scope_count_mismatch_rejected(self):
        inv, bench = fixture()
        inv["scopes"][0]["candidate_count"] = 59
        with self.assertRaisesRegex(ValueError, "inventory_scope_count_mismatch"):
            mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)

    def test_disk_safety_blocks(self):
        inv, bench = fixture()
        result = mod.make_plan(inv, bench, 119 * mod.GIB, 200 * mod.GIB)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["gates"]["disk_c_floor_120gib"])

    def test_d_scratch_blocks(self):
        inv, bench = fixture()
        result = mod.make_plan(inv, bench, 150 * mod.GIB, 1)
        self.assertEqual(result["status"], "BLOCKED")

    def test_runtime_blocks(self):
        inv, bench = fixture()
        bench["projected_total_seconds"] = 49 * 3600
        result = mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["hard_runtime_48h_met"])

    def test_outcome_data_forbidden(self):
        inv, bench = fixture()
        bench["outcome_data_accessed"] = True
        with self.assertRaisesRegex(ValueError, "outcome_or_policy_contamination"):
            mod.make_plan(inv, bench, 150 * mod.GIB, 200 * mod.GIB)


if __name__ == "__main__":
    unittest.main(verbosity=2)
