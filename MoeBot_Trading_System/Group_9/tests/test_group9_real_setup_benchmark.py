#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CODE=ROOT/"Group_9"/"code"
import sys
sys.path.insert(0,str(CODE))
SCRIPT=CODE/"group9_real_setup_benchmark.py"
spec=importlib.util.spec_from_file_location("g9bench",SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Group9RealSetupBenchmarkTests(unittest.TestCase):
    def test_stratified_sample_keeps_small_family(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            inv=sqlite3.connect(td/"inv.sqlite")
            inv.executescript("""
            CREATE TABLE root_candidate(
              root_key TEXT PRIMARY KEY,dataset_year INTEGER,setup_family TEXT,source_group INTEGER,
              source_type TEXT,source_id TEXT,definition_id TEXT,symbol TEXT,timeframe TEXT,direction TEXT,
              event_time INTEGER,availability_time INTEGER,root_month TEXT,source_row_hash TEXT
            );
            """)
            rows=[]
            for i in range(1000):
                rows.append((f"w{i:04d}",2023,"G9_WYCKOFF_RANGE_RESOLUTION",8,"school_interpretation",f"w{i}","wyckoff_spring_candidate","X","M5","bullish",i,i+1,"2023-01","a"*64))
            for i in range(5):
                rows.append((f"i{i:04d}",2023,"G9_ICT_LIQUIDITY_DELIVERY",8,"school_interpretation",f"i{i}","ict_liquidity_sweep_displacement","X","M5","bullish",i,i+1,"2023-01","b"*64))
            inv.executemany("INSERT INTO root_candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows);inv.commit()
            idx=m.init_index(td/"idx.sqlite")
            r=m.select_sample(inv,idx,120)
            got=dict(idx.execute("SELECT setup_family,COUNT(*) FROM benchmark_sample GROUP BY setup_family"))
            self.assertEqual(got["G9_ICT_LIQUIDITY_DELIVERY"],5)
            self.assertGreater(got["G9_WYCKOFF_RANGE_RESOLUTION"],0)
            self.assertEqual(r["actual"],120)
            idx.close();inv.close()

    def test_wyckoff_direct_chain_materializes_ready(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            idx=m.init_index(td/"idx.sqlite");idx.row_factory=sqlite3.Row
            root_refs=json.dumps([{"source_group":"group8","source_type":"school_interpretation","source_id":"ctx","availability_time":10}])
            ctx_refs="[]"
            sign_refs=json.dumps([{"source_group":"group8","source_type":"school_interpretation","source_id":"ctx","availability_time":10}])
            last_refs=json.dumps([{"source_group":"group8","source_type":"school_interpretation","source_id":"sign","availability_time":30}])
            rows=[
              ("root","school_interpretation",2023,"wyckoff_spring_candidate","X","M5","bullish",20,20,"a"*64,root_refs,1),
              ("ctx","school_interpretation",2023,"wyckoff_range_context","X","M5","neutral",10,10,"b"*64,ctx_refs,0),
              ("sign","school_interpretation",2023,"wyckoff_sign_of_strength","X","M5","bullish",30,30,"c"*64,sign_refs,0),
              ("last","school_interpretation",2023,"wyckoff_last_point_of_support","X","M5","bullish",40,40,"d"*64,last_refs,0),
            ]
            idx.executemany("INSERT INTO subject VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rows)
            m.index_support_refs(idx,"sign","school_interpretation","wyckoff_sign_of_strength",sign_refs)
            m.index_support_refs(idx,"last","school_interpretation","wyckoff_last_point_of_support",last_refs)
            idx.execute("INSERT INTO annual_boundary VALUES(2023,100)")
            idx.execute("""INSERT INTO benchmark_sample VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("rk",2023,"G9_WYCKOFF_RANGE_RESOLUTION","school_interpretation","root","wyckoff_spring_candidate","X","M5","bullish",20,20,"a"*64))
            idx.commit()
            out=m.init_sample_output(td/"out.sqlite",ROOT/"Group_9"/"02_SCHEMA.sql")
            out.execute("PRAGMA foreign_keys=ON")
            sample=idx.execute("SELECT * FROM benchmark_sample").fetchone()
            stats=defaultdict(lambda:{"roots":0,"setup_rows":0,"evidence_rows":0,"transition_rows":0,"logical_bytes":0})
            m.materialize_one(idx,out,sample,"G9-SSI-1.0.0",stats);out.commit()
            state=out.execute("SELECT current_state FROM setup_instance").fetchone()[0]
            trans=[r[0] for r in out.execute("SELECT to_state FROM setup_transition ORDER BY transition_ordinal")]
            self.assertEqual(state,"READY")
            self.assertEqual(trans,["FORMING","READY"])
            self.assertGreaterEqual(out.execute("SELECT COUNT(*) FROM setup_component_evidence").fetchone()[0],6)
            out.close();idx.close()

if __name__=="__main__":
    unittest.main(verbosity=2)
