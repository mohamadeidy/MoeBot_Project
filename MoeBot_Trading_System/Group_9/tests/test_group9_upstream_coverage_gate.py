#!/usr/bin/env python3
"""Small, synthetic tests for the read-only upstream coverage gate."""
from __future__ import annotations
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_upstream_coverage_gate.py"
spec = importlib.util.spec_from_file_location("group9_upstream_coverage_gate", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shard = self.root / "stage6.sqlite"
        with closing(sqlite3.connect(self.shard)) as c:
            c.execute("CREATE TABLE school_interpretation(definition_id TEXT)")
            c.executemany("INSERT INTO school_interpretation VALUES(?)", [
                ("wyckoff_range_context",),
                ("wyckoff_spring_candidate",),
                ("wyckoff_upthrust_candidate",),
            ])
            c.commit()
        self.release = self.root / "stage6.json"
        self.release.write_text(json.dumps({
            "status": "PASS", "stage": 6, "year": 2023,
            "shards": [{"database": str(self.shard),
                        "table_row_counts": {"school_interpretation": 3}}],
        }))
        self.support = self.root / "support.sqlite"
        with closing(sqlite3.connect(self.support)) as c:
            c.execute("CREATE TABLE subject(dataset_year INTEGER,definition_id TEXT)")
            c.execute("CREATE INDEX ix_subject_def ON subject(dataset_year,definition_id)")
            c.commit()
        self.sample = self.root / "sample.sqlite"
        with closing(sqlite3.connect(self.sample)) as c:
            c.execute("CREATE TABLE setup_instance(setup_family TEXT,current_state TEXT)")
            c.execute("INSERT INTO setup_instance VALUES('G9_WYCKOFF_RANGE_RESOLUTION','MISSING')")

            c.commit()

    def test_blocks_missing_mandatory_evidence(self):
        result = mod.audit([self.release], self.support, self.sample)
        self.assertEqual(result["status"], "BLOCKED_MANDATORY_SUPPORT_ABSENT")
        self.assertFalse(result["annual_execution_authorized"])
        self.assertEqual(result["stage6_years"][0]["root_count"], 2)
        self.assertEqual(len(result["missing_required_definitions"]), 4)

    def test_reconciles_verified_shard_counts(self):
        rec = json.loads(self.release.read_text())
        rec["shards"][0]["table_row_counts"]["school_interpretation"] = 4
        self.release.write_text(json.dumps(rec))
        with self.assertRaisesRegex(ValueError, "stage6_count_mismatch"):
            mod.audit([self.release], self.support, self.sample)

    def test_blocks_duplicate_year(self):
        with self.assertRaisesRegex(ValueError, "duplicate_year"):
            mod.audit([self.release, self.release], self.support, self.sample)

    def test_rejects_unapproved_release(self):
        rec = json.loads(self.release.read_text())
        rec["status"] = "FAILED"
        self.release.write_text(json.dumps(rec))
        with self.assertRaisesRegex(ValueError, "unapproved_stage6_release"):
            mod.audit([self.release], self.support, self.sample)


if __name__ == "__main__":
    unittest.main(verbosity=2)
