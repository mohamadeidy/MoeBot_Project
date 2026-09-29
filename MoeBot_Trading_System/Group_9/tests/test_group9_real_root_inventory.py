#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/"Group_9"/"code"/"group9_real_root_inventory.py"
spec=importlib.util.spec_from_file_location("g9inv",SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RealInventoryTests(unittest.TestCase):
    def test_insert_exact_roots_and_duplicate_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"inv.sqlite"
            con=m.init_inventory(db)
            try:
                rows=[
                    (2023,"g8i_a","ict_liquidity_sweep_displacement","XAUUSD_","M5","bullish",1700000000,1700000060,"a"*64),
                    (2024,"g8i_b","wyckoff_spring_candidate","XAUUSD_","M15","bullish",1730000000,1730000060,"b"*64),
                ]
                seen,inserted=m.insert_rows(con,rows,expected_source_type="school_interpretation")
                self.assertEqual((seen,inserted),(2,2))
                con.commit()
                self.assertEqual(con.execute("SELECT COUNT(*) FROM root_candidate").fetchone()[0],2)
                with self.assertRaises(RuntimeError):
                    m.insert_rows(con,[rows[0]],expected_source_type="school_interpretation")
            finally:
                con.close()

    def test_narrative_root_mapping_and_causality_guard(self):
        with tempfile.TemporaryDirectory() as td:
            con=m.init_inventory(Path(td)/"inv.sqlite")
            try:
                row=(2023,"g8h_x","pa_structural_pullback","XAUUSD_","H1","bearish",1700000000,1700000100,"c"*64)
                _,inserted=m.insert_rows(con,[row],expected_source_type="narrative_hypothesis")
                self.assertEqual(inserted,1)
                family=con.execute("SELECT setup_family FROM root_candidate").fetchone()[0]
                self.assertEqual(family,"G9_STRUCTURAL_PULLBACK_CONTINUATION")
                bad=(2023,"bad","pa_structural_pullback","XAUUSD_","H1","bearish",1700000200,1700000100,"d"*64)
                with self.assertRaises(RuntimeError):
                    m.insert_rows(con,[bad],expected_source_type="narrative_hypothesis")
            finally:
                con.close()

    def test_verified_restore_marker_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/"restore.sqlite"
            raw.write_bytes(b"abcd")
            rep={
                "year":2023,
                "raw_size_bytes":4,
                "raw_sha256":"a"*64,
                "archive_sha256":"b"*64,
                "report_hash":"c"*64,
            }
            self.assertFalse(m.load_verified_restore_marker(raw,rep))
            m.write_verified_restore_marker(raw,rep,provenance="unit_test")
            self.assertTrue(m.load_verified_restore_marker(raw,rep))
            raw.write_bytes(b"abcde")
            self.assertFalse(m.load_verified_restore_marker(raw,rep))

    def test_logical_fingerprint_stable(self):
        with tempfile.TemporaryDirectory() as td:
            con=m.init_inventory(Path(td)/"inv.sqlite")
            try:
                rows=[
                    (2024,"z","ict_liquidity_sweep_displacement","XAUUSD_","M5","bearish",1730000000,1730000010,"e"*64),
                    (2023,"a","wyckoff_upthrust_candidate","XAUUSD_","M30","bearish",1700000000,1700000010,"f"*64),
                ]
                m.insert_rows(con,rows,expected_source_type="school_interpretation");con.commit()
                h1=m.logical_fingerprint(con);h2=m.logical_fingerprint(con)
                self.assertEqual(h1,h2)
                self.assertEqual(len(h1),64)
            finally:
                con.close()

if __name__=="__main__":
    unittest.main(verbosity=2)
