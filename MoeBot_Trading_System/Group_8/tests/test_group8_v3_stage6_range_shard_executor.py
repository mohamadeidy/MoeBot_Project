#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_v3_stage6_range_shard_executor import (
    RangeShardSpec,
    STAGE6_DEFINITIONS,
    epoch_month,
    run_shard,
)
from moebot_group8_engine_v0_8_0 import sha256_file
from test_group8_engine_v0_8_0 import ART, make_stage

SYMBOL = "XAUUSD_"


def stage6_rows(db: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    con = sqlite3.connect(db)
    try:
        q = ",".join("?" for _ in STAGE6_DEFINITIONS)
        interpretations = {
            (str(r[0]), str(r[1]))
            for r in con.execute(
                f"SELECT interpretation_id,interpretation_hash FROM school_interpretation "
                f"WHERE definition_id IN ({q})",
                STAGE6_DEFINITIONS,
            )
        }
        evidence = {
            (str(r[0]), str(r[1]))
            for r in con.execute(
                f"""SELECT e.evidence_chain_id,e.evidence_hash
                    FROM evidence_chain e
                    JOIN school_interpretation i ON i.interpretation_id=e.subject_id
                    WHERE e.subject_type='school_interpretation'
                      AND i.definition_id IN ({q})""",
                STAGE6_DEFINITIONS,
            )
        }
        return interpretations, evidence
    finally:
        con.close()


def range_specs(stage5: Path, year: int, bucket_count: int) -> list[RangeShardSpec]:
    con = sqlite3.connect(stage5)
    try:
        roots = {
            (str(r[0]), epoch_month(int(r[1])))
            for r in con.execute(
                """SELECT timeframe,event_time
                   FROM price_action_pattern_candidate
                   WHERE definition_id='pa_bounded_range_context'
                   ORDER BY timeframe,event_time"""
            )
        }
    finally:
        con.close()
    specs = []
    for timeframe, month in sorted(roots):
        for bucket in range(bucket_count):
            specs.append(RangeShardSpec(year, SYMBOL, timeframe, month, bucket_count, bucket))
    return specs


class Group8V3Stage6RangeShardTests(unittest.TestCase):
    def _build_stage5(self, td: Path) -> tuple[Path, Path]:
        staging = td / "stage.sqlite"
        stage5 = td / "stage5.sqlite"
        make_stage(staging)
        report = run_segment(
            staging_db=staging,
            output_db=stage5,
            artifacts_root=ART,
            year=2023,
            symbol=SYMBOL,
            start=0,
            end=5,
        )
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["complete"])
        return staging, stage5

    def test_stage6_shard_union_matches_frozen_reference_and_preserves_stage5(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            before = sha256_file(stage5)

            reference = td / "reference.sqlite"
            shutil.copy2(stage5, reference)
            ref = AnnualCoreEngine(
                staging_db=staging,
                output_db=reference,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
            )
            try:
                ref.load_bars()
                ref.process_wyckoff_core()
            finally:
                ref.close()

            actual_i: set[tuple[str, str]] = set()
            actual_e: set[tuple[str, str]] = set()
            for n, spec in enumerate(range_specs(stage5, 2023, bucket_count=2)):
                db = td / f"shard_{n}.sqlite"
                cp = td / f"shard_{n}.checkpoint.json"
                manifest = td / f"shard_{n}.manifest.json"
                result = run_shard(
                    staging_db=staging,
                    stage5_db=stage5,
                    output_db=db,
                    checkpoint_path=cp,
                    manifest_path=manifest,
                    artifacts_root=ART,
                    spec=spec,
                    chunk_pairs=2,
                    hard_guard_bytes=2_500_000_000,
                )
                self.assertEqual(result["status"], "PASS")
                rows_i, rows_e = stage6_rows(db)
                self.assertFalse(actual_i.intersection(rows_i))
                self.assertFalse(actual_e.intersection(rows_e))
                actual_i |= rows_i
                actual_e |= rows_e

            expected_i, expected_e = stage6_rows(reference)
            self.assertEqual(actual_i, expected_i)
            self.assertEqual(actual_e, expected_e)
            self.assertEqual(sha256_file(stage5), before)

    def test_crash_resume_is_logically_identical_and_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            specs = range_specs(stage5, 2023, bucket_count=1)
            if not specs:
                self.skipTest("fixture has no bounded ranges")
            spec = specs[0]

            resumed_db = td / "resumed.sqlite"
            resumed_cp = td / "resumed.checkpoint.json"
            resumed_manifest = td / "resumed.manifest.json"
            partial = run_shard(
                staging_db=staging,
                stage5_db=stage5,
                output_db=resumed_db,
                checkpoint_path=resumed_cp,
                manifest_path=resumed_manifest,
                artifacts_root=ART,
                spec=spec,
                chunk_pairs=1,
                hard_guard_bytes=2_500_000_000,
                max_chunks=1,
            )

            if partial.get("status") == "RUNNING":
                completed = run_shard(
                    staging_db=staging,
                    stage5_db=stage5,
                    output_db=resumed_db,
                    checkpoint_path=resumed_cp,
                    manifest_path=resumed_manifest,
                    artifacts_root=ART,
                    spec=spec,
                    chunk_pairs=1,
                    hard_guard_bytes=2_500_000_000,
                )
                self.assertEqual(completed["status"], "PASS")
            else:
                completed = partial

            clean_db = td / "clean.sqlite"
            clean_cp = td / "clean.checkpoint.json"
            clean_manifest = td / "clean.manifest.json"
            clean = run_shard(
                staging_db=staging,
                stage5_db=stage5,
                output_db=clean_db,
                checkpoint_path=clean_cp,
                manifest_path=clean_manifest,
                artifacts_root=ART,
                spec=spec,
                chunk_pairs=1,
                hard_guard_bytes=2_500_000_000,
            )
            self.assertEqual(clean["status"], "PASS")
            self.assertEqual(stage6_rows(resumed_db), stage6_rows(clean_db))
            self.assertEqual(completed["table_logical_sha256"], clean["table_logical_sha256"])

            rerun = run_shard(
                staging_db=staging,
                stage5_db=stage5,
                output_db=resumed_db,
                checkpoint_path=resumed_cp,
                manifest_path=resumed_manifest,
                artifacts_root=ART,
                spec=spec,
                chunk_pairs=1,
                hard_guard_bytes=2_500_000_000,
            )
            self.assertEqual(rerun["status"], "PASS")
            self.assertEqual(rerun["table_logical_sha256"], completed["table_logical_sha256"])
            self.assertEqual(stage6_rows(resumed_db), stage6_rows(clean_db))


if __name__ == "__main__":
    unittest.main()
