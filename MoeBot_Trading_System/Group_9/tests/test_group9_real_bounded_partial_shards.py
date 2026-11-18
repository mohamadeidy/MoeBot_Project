#!/usr/bin/env python3
"""Fail-closed tests for partial-shard recovery and manifest integrity."""
from __future__ import annotations
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_real_bounded_partial_shards.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("g9_bounded_real", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class RealBoundedShardTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = Path(t.name)
        self.db = self.base / "part.sqlite"
        self.manifest = self.base / "part.manifest.json"
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript("""
                CREATE TABLE setup_instance(setup_id TEXT PRIMARY KEY);
                CREATE TABLE setup_component_evidence(evidence_id TEXT,setup_id TEXT);
                CREATE TABLE setup_transition(transition_id TEXT,setup_id TEXT);
                INSERT INTO setup_instance VALUES('setup-01');
            """)
        body = {
            "plan_report_hash": "plan-a",
            "setup_ids": ["setup-01"],
            "raw_size_bytes": self.db.stat().st_size,
            "raw_sha256": module.sha_file(self.db),
            "row_counts": {
                "setup_instance": 1, "setup_component_evidence": 0,
                "setup_transition": 0,
            },
        }
        body["manifest_hash"] = module.fingerprint(body)
        self.manifest.write_text(json.dumps(body), encoding="utf-8")

    def test_verified_resume_is_exact(self):
        m = module.verify_manifest(self.manifest, self.db, "plan-a", ["setup-01"])
        self.assertEqual(m["row_counts"]["setup_instance"], 1)

    def test_missing_shard_fails_closed(self):
        self.db.unlink()
        with self.assertRaisesRegex(RuntimeError, "manifest_or_database_missing"):
            module.verify_manifest(self.manifest, self.db, "plan-a", ["setup-01"])

    def test_manifest_tampering_fails_closed(self):
        data = json.loads(self.manifest.read_text())
        data["row_counts"]["setup_instance"] = 5
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "manifest_hash_mismatch"):
            module.verify_manifest(self.manifest, self.db, "plan-a", ["setup-01"])

    def test_plan_drift_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "identity_or_membership_mismatch"):
            module.verify_manifest(self.manifest, self.db, "plan-b", ["setup-01"])

    def test_raw_database_sha_fails_closed(self):
        with self.db.open("ab") as f:
            f.write(b"mutation")
        with self.assertRaisesRegex(RuntimeError, "raw_sha_or_size_mismatch"):
            module.verify_manifest(self.manifest, self.db, "plan-a", ["setup-01"])

    def test_bounded_limit_rejected(self):
        with sqlite3.connect(":memory:") as c:
            with self.assertRaisesRegex(ValueError, "invalid_bounded_limit"):
                module.bounded_selection(c, year=2023, tf="H1", month="2023-05",
                                         bucket=0, plan_bucket_count=8, limit=100000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
