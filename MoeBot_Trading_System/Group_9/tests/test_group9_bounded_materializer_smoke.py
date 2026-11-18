#!/usr/bin/env python3
"""Bounded replay selection controls; never accesses real annual data."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_bounded_materializer_smoke.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("g9_bounded_smoke", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class BoundedSmokeTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.execute(
            "CREATE TABLE setup_instance("
            "setup_id TEXT, setup_family TEXT, current_state TEXT, "
            "root_subject_type TEXT, root_subject_id TEXT)"
        )
        rows = []
        for family in module.FAMILIES:
            for state in ("MISSING", "READY"):
                for i in range(5):
                    sid = f"{family}_{state}_{i}"
                    rows.append((sid, family, state, "school_interpretation", sid))
        self.c.executemany("INSERT INTO setup_instance VALUES(?,?,?,?,?)", rows)
        self.addCleanup(self.c.close)

    def test_bounded_selection_keeps_family_state_coverage(self):
        rows = module.select_references(self.c, 2)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r["setup_id"] for r in rows}), 12)
        for fam in module.FAMILIES:
            for state in ("MISSING", "READY"):
                self.assertEqual(sum(r["setup_family"] == fam and
                                     r["current_state"] == state for r in rows), 2)

    def test_rejects_unbounded_selection(self):
        for n in (0, 33, -1):
            with self.subTest(n=n):
                with self.assertRaisesRegex(ValueError, "per_family_outside"):
                    module.select_references(self.c, n)

    def test_missing_reference_family_is_rejected(self):
        self.c.execute("DELETE FROM setup_instance WHERE setup_family=?",
                       (module.FAMILIES[0],))
        with self.assertRaisesRegex(ValueError, "missing_family_in_reference"):
            module.select_references(self.c, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
