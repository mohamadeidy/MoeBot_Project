#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_v3_stage6_range_shard_executor import bucket_for_root, epoch_month
from group8_v3_stage7_shard_executor import (
    SCHOOL_DEFINITIONS,
    STAGE7_DEFINITIONS,
    Stage7ShardSpec,
    compress_verified_shard,
    run_shard,
)
from moebot_group8_engine_v0_8_0 import sha256_file
from test_group8_engine_v0_8_0 import ART, make_stage

SYMBOL = "XAUUSD_"
DUMMY_STAGE6_RELEASE = "stage6-release-fixture"
DUMMY_STAGE6_UNION = "stage6-union-fixture"


def stage7_rows(db: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    con = sqlite3.connect(db)
    try:
        q = ",".join("?" for _ in STAGE7_DEFINITIONS)
        interpretations = {
            (str(r[0]), str(r[1]))
            for r in con.execute(
                f"SELECT interpretation_id,interpretation_hash FROM school_interpretation "
                f"WHERE definition_id IN ({q})",
                STAGE7_DEFINITIONS,
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
                STAGE7_DEFINITIONS,
            )
        }
        return interpretations, evidence
    finally:
        con.close()


def _windows_from_bars(staging: Path) -> list[tuple[str, str]]:
    con = sqlite3.connect(staging)
    try:
        rows = con.execute(
            "SELECT timeframe,close_time FROM source__bars WHERE symbol=? ORDER BY timeframe,close_time",
            (SYMBOL,),
        ).fetchall()
    finally:
        con.close()
    return sorted({(str(tf), epoch_month(int(t))) for tf, t in rows})


def _range_windows(stage5: Path) -> list[tuple[str, str]]:
    con = sqlite3.connect(stage5)
    try:
        rows = con.execute(
            "SELECT timeframe,event_time FROM price_action_pattern_candidate "
            "WHERE definition_id='pa_bounded_range_context'"
        ).fetchall()
    finally:
        con.close()
    return sorted({(str(tf), epoch_month(int(t))) for tf, t in rows})


class Group8V3Stage7ShardTests(unittest.TestCase):
    def _build_stage5(self, td: Path) -> tuple[Path, Path]:
        staging = td / "staging.sqlite"
        stage5 = td / "stage5.sqlite"
        make_stage(staging)
        r = run_segment(
            staging_db=staging,
            output_db=stage5,
            artifacts_root=ART,
            year=2023,
            symbol=SYMBOL,
            start=0,
            end=5,
        )
        self.assertEqual(r["status"], "PASS")
        return staging, stage5

    def _run_one(self, td: Path, staging: Path, stage5: Path, spec: Stage7ShardSpec, name: str, **extra):
        return run_shard(
            staging_db=staging,
            stage5_db=stage5,
            output_db=td / f"{name}.sqlite",
            checkpoint_path=td / f"{name}.checkpoint.json",
            manifest_path=td / f"{name}.manifest.json",
            artifacts_root=ART,
            spec=spec,
            chunk_interpretations=2,
            hard_guard_bytes=2_500_000_000,
            stage6_release_hash=DUMMY_STAGE6_RELEASE,
            stage6_union_report_hash=DUMMY_STAGE6_UNION,
            **extra,
        )

    def test_union_of_stage7_shards_matches_frozen_reference(self):
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
                ref.process_ict()
            finally:
                ref.close()
            expected_i, expected_e = stage7_rows(reference)

            actual_i: set[tuple[str, str]] = set()
            actual_e: set[tuple[str, str]] = set()
            n = 0
            for tf, month in _range_windows(stage5):
                for bucket in range(2):
                    spec = Stage7ShardSpec("range_chain", 2023, SYMBOL, tf, month, 2, bucket)
                    self._run_one(td, staging, stage5, spec, f"range_{n}")
                    i, e = stage7_rows(td / f"range_{n}.sqlite")
                    self.assertFalse(actual_i.intersection(i))
                    self.assertFalse(actual_e.intersection(e))
                    actual_i |= i
                    actual_e |= e
                    n += 1

            for tf, month in _windows_from_bars(staging):
                for bucket in range(2):
                    spec = Stage7ShardSpec("school_core", 2023, SYMBOL, tf, month, 2, bucket)
                    self._run_one(td, staging, stage5, spec, f"school_{n}")
                    i, e = stage7_rows(td / f"school_{n}.sqlite")
                    self.assertFalse(actual_i.intersection(i))
                    self.assertFalse(actual_e.intersection(e))
                    actual_i |= i
                    actual_e |= e
                    n += 1

            self.assertEqual(actual_i, expected_i)
            self.assertEqual(actual_e, expected_e)
            self.assertEqual(sha256_file(stage5), before)

    def test_range_resume_and_idempotence(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            windows = _range_windows(stage5)
            if not windows:
                self.skipTest("fixture has no bounded ranges")
            tf, month = windows[0]
            spec = Stage7ShardSpec("range_chain", 2023, SYMBOL, tf, month, 1, 0)
            name = "resume_range"
            partial = self._run_one(
                td, staging, stage5, spec, name, max_chunks=1
            )
            if partial.get("status") == "RUNNING":
                completed = self._run_one(td, staging, stage5, spec, name)
            else:
                completed = partial
            self.assertEqual(completed["status"], "PASS")
            before_rows = stage7_rows(td / f"{name}.sqlite")
            rerun = self._run_one(td, staging, stage5, spec, name)
            self.assertEqual(rerun["status"], "PASS")
            self.assertEqual(stage7_rows(td / f"{name}.sqlite"), before_rows)

    def test_school_core_resume_and_idempotence(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            windows = _windows_from_bars(staging)
            if not windows:
                self.skipTest("fixture has no bars")
            tf, month = windows[0]
            spec = Stage7ShardSpec("school_core", 2023, SYMBOL, tf, month, 1, 0)
            name = "resume_school"
            partial = self._run_one(td, staging, stage5, spec, name, max_chunks=1)
            if partial.get("status") == "RUNNING":
                completed = self._run_one(td, staging, stage5, spec, name)
            else:
                completed = partial
            self.assertEqual(completed["status"], "PASS")
            before_rows = stage7_rows(td / f"{name}.sqlite")
            rerun = self._run_one(td, staging, stage5, spec, name)
            self.assertEqual(rerun["status"], "PASS")
            self.assertEqual(stage7_rows(td / f"{name}.sqlite"), before_rows)

    def test_zstd_compression_roundtrip_is_exact_and_raw_deleted(self):
        zstd = shutil.which("zstd")
        if not zstd:
            self.skipTest("zstd CLI unavailable")
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            windows = _windows_from_bars(staging)
            tf, month = windows[0]
            spec = Stage7ShardSpec("school_core", 2023, SYMBOL, tf, month, 1, 0)
            name = "compress"
            manifest = self._run_one(td, staging, stage5, spec, name)
            db = td / f"{name}.sqlite"
            mf = td / f"{name}.manifest.json"
            archive = td / f"{name}.sqlite.zst"
            raw_sha = manifest["sha256"]
            compressed = compress_verified_shard(
                database=db,
                manifest_path=mf,
                archive=archive,
                zstd_exe=Path(zstd),
                level=6,
                remove_raw=True,
            )
            self.assertFalse(db.exists())
            self.assertTrue(archive.exists())
            self.assertFalse(compressed["raw_retained"])
            self.assertEqual(compressed["compression_roundtrip_sha256"], raw_sha)
            self.assertIsNotNone(compressed["compressed_sha256"])
            self.assertGreater(compressed["compressed_size_bytes"], 0)

    def test_2024_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            spec = Stage7ShardSpec("school_core", 2024, SYMBOL, "M15", "2024-01", 1, 0)
            with self.assertRaises(RuntimeError):
                self._run_one(td, staging, stage5, spec, "oos")


if __name__ == "__main__":
    unittest.main()
