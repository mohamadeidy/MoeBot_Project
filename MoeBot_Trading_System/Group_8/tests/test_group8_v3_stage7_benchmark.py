#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_segmented_annual_core import run_segment
from group8_v3_stage7_benchmark import run_benchmark
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import ART, make_stage

SYMBOL = "XAUUSD_"


def _rows(db: Path):
    con = sqlite3.connect(db)
    try:
        return {
            (str(r[0]), str(r[1]))
            for r in con.execute(
                "SELECT interpretation_id,interpretation_hash FROM school_interpretation "
                "WHERE definition_id='ict_premium_discount_context'"
            )
        }
    finally:
        con.close()


class Group8V3Stage7BenchmarkTests(unittest.TestCase):
    def test_benchmark_matches_frozen_reference_premium_discount_rows(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging = td / "staging.sqlite"
            stage5 = td / "stage5.sqlite"
            make_stage(staging)
            run_segment(
                staging_db=staging,
                output_db=stage5,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
                start=0,
                end=5,
            )

            con = sqlite3.connect(stage5)
            try:
                range_count = con.execute(
                    "SELECT COUNT(*) FROM price_action_pattern_candidate "
                    "WHERE definition_id='pa_bounded_range_context'"
                ).fetchone()[0]
            finally:
                con.close()
            if range_count == 0:
                self.skipTest("synthetic fixture has no bounded ranges")

            preflight = {
                "status": "PASS",
                "stage7_authorized": False,
                "stage5_database_sha256": __import__("moebot_group8_engine_v0_8_0").sha256_file(stage5),
                "definition_cardinality_current_engine": {
                    "ict_premium_discount_context": 100,
                },
                "projection_diagnostic": {
                    "current_engine_total_logical_rows": 400,
                    "stage6_observed_bytes_per_logical_row": 100.0,
                },
                "premium_discount": {"by_root_window": {"M15:2023-01": 100}},
                "report_hash": "fixture-preflight",
            }
            pf = td / "preflight.json"
            pf.write_text(json.dumps(preflight))

            sample = td / "sample.sqlite"
            report = run_benchmark(
                staging_db=staging,
                stage5_db=stage5,
                preflight_report_path=pf,
                artifacts_root=ART,
                sample_db=sample,
                report_path=td / "benchmark.json",
                symbol=SYMBOL,
                sample_roots_per_window=10000,
                chunk_interpretations=2,
                safety_floor_gb=0.0,
                storage_safety_factor=1.5,
                runtime_safety_factor=1.5,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["stage7_authorized"])
            self.assertFalse(report["full_annual_stage7_permitted"])

            reference = td / "reference.sqlite"
            shutil.copy2(stage5, reference)
            e = Group8Engine(
                staging_db=staging,
                output_db=reference,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
            )
            try:
                e.load_bars()
                e.process_ict()
            finally:
                e.close()

            self.assertEqual(_rows(sample), _rows(reference))

            con = sqlite3.connect(sample)
            try:
                i = con.execute(
                    "SELECT COUNT(*) FROM school_interpretation "
                    "WHERE definition_id='ict_premium_discount_context'"
                ).fetchone()[0]
                ev = con.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0]
            finally:
                con.close()
            self.assertEqual(ev, 2 * i)


if __name__ == "__main__":
    unittest.main()
