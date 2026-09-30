#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class DraftSchemaTests(unittest.TestCase):
    def test_all_draft_schemas_compile(self):
        for g in range(9,16):
            p=ROOT/f"Group_{g}"/"02_SCHEMA_DRAFT.sql"
            self.assertTrue(p.exists(),str(p))
            con=sqlite3.connect(":memory:")
            con.executescript(p.read_text())
            con.close()
if __name__=="__main__":unittest.main(verbosity=2)
