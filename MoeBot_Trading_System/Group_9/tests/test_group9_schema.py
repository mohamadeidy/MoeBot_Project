#!/usr/bin/env python3
from __future__ import annotations
import sqlite3, tempfile, unittest
from pathlib import Path

class Group9SchemaTests(unittest.TestCase):
    def test_schema_builds_and_enforces_state_vocab(self):
        root=Path(__file__).resolve().parents[1]
        sql=(root/"02_SCHEMA_DRAFT.sql").read_text()
        con=sqlite3.connect(":memory:");con.executescript(sql)
        con.execute("INSERT INTO setup_instance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("s1","h","XAUUSD_","M15","BUY",1,1,"FORMING",1,1,"draft","p","{}"))
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO setup_instance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("s2","h","XAUUSD_","M15","BUY",1,1,"TRADE_NOW",1,1,"draft","p","{}"))
if __name__=="__main__":unittest.main(verbosity=2)
