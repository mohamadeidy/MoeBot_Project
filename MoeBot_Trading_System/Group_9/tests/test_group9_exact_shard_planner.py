#!/usr/bin/env python3
"""Synthetic identity, partition, and safety tests for Group 9 exact shard planner."""
from __future__ import annotations
import importlib.util
import sqlite3
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_exact_shard_planner.py"
spec = importlib.util.spec_from_file_location("g9_exact", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def fixture():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE root_candidate(
        dataset_year INTEGER,symbol TEXT,timeframe TEXT,root_month TEXT,
        setup_family TEXT,source_type TEXT,source_id TEXT,direction TEXT)""")
    c.executemany("INSERT INTO root_candidate VALUES(?,?,?,?,?,?,?,?)", [
        (2023, "XAUUSD_", "H1", "2023-01", "F", "school_interpretation", "id1", "bullish"),
        (2023, "XAUUSD_", "H1", "2023-01", "F", "school_interpretation", "id2", "bearish"),
        (2024, "XAUUSD_", "M15", "2024-03", "F", "school_interpretation", "id3", "bullish"),
    ])
    inv = {"report_hash": "inv", "candidate_count": 3}
    bench = {
        "report_hash": "bench", "candidate_population": 3,
        "sqlite_overhead_factor": 1.0,
        "family_stats": {"F": {"population": 3, "projected_family_logical_bytes": 3000}},
    }
    projection = {
        "status": "PROJECTION_PASS", "report_hash": "projection",
        "inventory_report_hash": "inv", "benchmark_report_hash": "bench",
        "scopes": [
            {"year": 2023, "symbol": "XAUUSD_", "timeframe": "H1", "root_month": "2023-01", "candidate_count": 2, "bucket_count": 2},
            {"year": 2024, "symbol": "XAUUSD_", "timeframe": "M15", "root_month": "2024-03", "candidate_count": 1, "bucket_count": 1},
        ],
    }
    return c, inv, bench, projection


class ExactPlannerTests(unittest.TestCase):
    def test_exact_counts_and_determinism(self):
        c, inv, bench, proj = fixture()
        try:
            a = mod.exact_plan(c, inv, bench, proj)
            b = mod.exact_plan(c, inv, bench, proj)
            self.assertEqual(a["status"], "EXACT_COUNTS_PASS_ESTIMATED_SIZES")
            self.assertEqual(sum(x["candidate_count_exact"] for x in a["shards"]), 3)
            self.assertEqual(a["report_hash"], b["report_hash"])
            self.assertFalse(a["real_annual_execution_authorized"])
            self.assertFalse(a["actual_shard_bytes_verified"])
        finally:
            c.close()

    def test_missing_scope_fails_closed(self):
        c, inv, bench, proj = fixture()
        try:
            proj["scopes"].pop()
            with self.assertRaisesRegex(ValueError, "inventory_scope_absent"):
                mod.exact_plan(c, inv, bench, proj)
        finally:
            c.close()

    def test_family_count_mismatch_fails_closed(self):
        c, inv, bench, proj = fixture()
        try:
            bench["family_stats"]["F"]["population"] = 4
            with self.assertRaisesRegex(ValueError, "family_counts_mismatch"):
                mod.exact_plan(c, inv, bench, proj)
        finally:
            c.close()

    def test_invalid_bucket_count(self):
        with self.assertRaisesRegex(ValueError, "bucket_count_not_power_of_two"):
            mod.hash_bucket("abc", 3)

    def test_frozen_identity_matches_benchmark(self):
        payload = {
            "family": "F", "symbol": "XAUUSD_", "timeframe": "H1",
            "direction": "bullish", "root_subject_type": "school_interpretation",
            "root_subject_id": "id1", "definition_version": "G9-SSI-1.0.0",
        }
        self.assertEqual(mod.setup_id("F", "XAUUSD_", "H1", "bullish",
                                      "school_interpretation", "id1", "G9-SSI-1.0.0"),
                         "g9s_" + mod.stable(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)
