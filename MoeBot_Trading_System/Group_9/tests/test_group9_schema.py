#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path

class Group9SchemaTests(unittest.TestCase):
 def test_frozen_schema_builds_and_enforces_state_vocab(self):
  root=Path(__file__).resolve().parents[1]
  sql=(root/"02_SCHEMA.sql").read_text()
  con=sqlite3.connect(":memory:");con.executescript(sql)
  row=("s1","h","G9_ICT_LIQUIDITY_DELIVERY","school_interpretation","r1","ict_liquidity_sweep_displacement","XAUUSD_","M15","bullish",1,1,"FORMING",1,1,"G9-SSI-1.0.0","p","{}")
  con.execute("INSERT INTO setup_instance VALUES("+",".join("?" for _ in row)+")",row)
  bad=list(row);bad[11]="TRADE_NOW";bad[0]="s2";bad[2]="G9_WYCKOFF_RANGE_RESOLUTION";bad[4]="r2"
  with self.assertRaises(sqlite3.IntegrityError):
   con.execute("INSERT INTO setup_instance VALUES("+",".join("?" for _ in bad)+")",bad)
  con.close()

if __name__=="__main__":unittest.main(verbosity=2)
