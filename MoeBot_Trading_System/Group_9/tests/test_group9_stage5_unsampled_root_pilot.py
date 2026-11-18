#!/usr/bin/env python3
"""Source-identity safety tests; self-contained in-memory Group 9 fixtures."""
from __future__ import annotations
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_stage5_unsampled_root_pilot.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("g9_stage5_pilot", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class UnseenRootSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.support_path = Path(self.tmp.name) / "support.sqlite"
        with closing(sqlite3.connect(self.support_path)) as con:
            con.executescript("""
            CREATE TABLE subject(
                subject_id TEXT PRIMARY KEY, subject_type TEXT, dataset_year INT,
                definition_id TEXT, symbol TEXT, timeframe TEXT, direction TEXT,
                event_time INT, availability_time INT, row_hash TEXT,
                upstream_refs_json TEXT, is_sample_root INT
            );
            CREATE TABLE support_ref(source_group TEXT,source_type TEXT,source_id TEXT);
            CREATE TABLE invalidation(subject_type TEXT,subject_id TEXT);
            CREATE TABLE annual_boundary(dataset_year INT,censor_time INT);
            INSERT INTO annual_boundary VALUES(2023,1690000000);
            """)
        self.inv = sqlite3.connect(":memory:")
        self.inv.row_factory = sqlite3.Row
        self.addCleanup(self.inv.close)
        self.inv.executescript("""
            CREATE TABLE root_candidate(
                root_key TEXT PRIMARY KEY, dataset_year INT,
                setup_family TEXT, source_group INT, source_type TEXT,
                source_id TEXT, definition_id TEXT, symbol TEXT, timeframe TEXT,
                direction TEXT, event_time INT, availability_time INT,
                root_month TEXT, source_row_hash TEXT
            );
        """)
        self.root = ("zzzz", 2023, module.WYCKOFF_FAMILY, 8,
                     "school_interpretation", "raw-stage5-root-01",
                     "wyckoff_spring_candidate", "XAUUSD_", "H1", "bullish",
                     1683000000, 1683000000, "2023-05", "hash-r1")
        dummy = [
            (f"{n:08d}", 2023, module.WYCKOFF_FAMILY, 8,
             "school_interpretation", f"dummy-{n}", "wyckoff_spring_candidate",
             "XAUUSD_", "H1", "bullish", 1683000000, 1683000000,
             "2023-05", "dummy")
            for n in range(12_000)
        ]
        self.inv.executemany("INSERT INTO root_candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", dummy + [self.root])
        self.inv.commit()
        self.src = sqlite3.connect(":memory:")
        self.src.row_factory = sqlite3.Row
        self.addCleanup(self.src.close)
        self.src.executescript("""
            CREATE TABLE school_interpretation(
                interpretation_id TEXT PRIMARY KEY, definition_id TEXT,
                symbol TEXT, timeframe TEXT, direction TEXT, event_time INT,
                availability_time INT, interpretation_hash TEXT,
                upstream_refs_json TEXT
            );
            INSERT INTO school_interpretation VALUES(
                'raw-stage5-root-01','wyckoff_spring_candidate',
                'XAUUSD_','H1','bullish',1683000000,1683000000,'hash-r1','[]'
            );
        """)
        sid = module.setup_id(
            module.WYCKOFF_FAMILY, "XAUUSD_", "H1", "bullish",
            "school_interpretation", "raw-stage5-root-01", "G9-SSI-1.0.0"
        )
        self.shard = {
            "year": 2023, "symbol": "XAUUSD_", "timeframe": "H1",
            "root_month": "2023-05", "bucket_index": module.hash_bucket(sid, 8),
            "bucket_count": 8,
        }

    def get_index(self):
        c = module.make_index_overlay(self.support_path)
        self.addCleanup(c.close)
        return c

    def test_unsampled_root_matches_frozen_source(self):
        idx = self.get_index()
        rows, examined = module.select_unsampled_roots(
            self.inv, self.src, idx, self.shard, offset=12_000, roots_to_run=1
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], "raw-stage5-root-01")
        self.assertEqual(examined, 1)
        got = idx.execute(
            "SELECT * FROM subject WHERE subject_id=?", ("raw-stage5-root-01",)
        ).fetchone()
        self.assertEqual(got["row_hash"], "hash-r1")
        self.assertEqual(got["is_sample_root"], 0)

    def test_drift_in_original_row_hash_is_blocked(self):
        idx = self.get_index()
        self.src.execute(
            "UPDATE school_interpretation SET interpretation_hash='tampered'"
        )
        with self.assertRaisesRegex(RuntimeError, "lineage_mismatch"):
            module.select_unsampled_roots(
                self.inv, self.src, idx, self.shard, offset=12_000, roots_to_run=1
            )

    def test_previously_indexed_root_is_not_marked_unseen(self):
        with closing(sqlite3.connect(self.support_path)) as c:
            c.execute("""INSERT INTO subject VALUES(
                'raw-stage5-root-01','school_interpretation',2023,
                'wyckoff_spring_candidate','XAUUSD_','H1','bullish',
                1683000000,1683000000,'hash-r1','[]',1)""")
            c.commit()
        idx = self.get_index()
        with self.assertRaisesRegex(RuntimeError, "insufficient_unbenchmarked"):
            module.select_unsampled_roots(
                self.inv, self.src, idx, self.shard, offset=12_000, roots_to_run=1
            )

    def test_bounded_and_scope_guards(self):
        idx = self.get_index()
        for off, count in ((0, 1), (12_000, 17)):
            with self.subTest(off=off, count=count), self.assertRaises(ValueError):
                module.select_unsampled_roots(
                    self.inv, self.src, idx, self.shard, offset=off, roots_to_run=count
                )
        wrong = dict(self.shard, year=2024)
        with self.assertRaisesRegex(ValueError, "only_2023_H1"):
            module.select_unsampled_roots(
                self.inv, self.src, idx, wrong, offset=12_000, roots_to_run=1
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
