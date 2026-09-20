#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_v3_stage6_preflight import _git_head, run_preflight
from group8_v3_stage6_orchestrator import run_plan
from group8_v3_stage6_union_validator import validate_union
from group8_v3_stage6_range_shard_executor import (
    RangeShardSpec,
    STAGE6_DEFINITIONS,
    Stage6RangeShardEngine,
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


def logical_hash(rows: set[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for rid, rh in sorted(rows):
        h.update(rid.encode())
        h.update(b"\0")
        h.update(rh.encode())
        h.update(b"\n")
    return h.hexdigest()


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

    def test_latest_same_layer_dow_only(self):
        rg = {"availability_time": 100, "_layer": "internal"}
        dows = [
            {"availability_time": 10, "_layer": "internal", "interpretation_id": "old"},
            {"availability_time": 20, "_layer": "external", "interpretation_id": "other-layer"},
            {"availability_time": 90, "_layer": "internal", "interpretation_id": "latest"},
            {"availability_time": 110, "_layer": "internal", "interpretation_id": "future"},
        ]
        selected = Stage6RangeShardEngine._eligible_dows(rg, dows)
        self.assertEqual([x["interpretation_id"] for x in selected], ["latest"])

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

    def test_recovered_physical_boundary_with_stage6_rows_is_logically_stage5(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)

            legacy = AnnualCoreEngine(
                staging_db=staging,
                output_db=stage5,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
            )
            try:
                legacy.load_bars()
                legacy.process_wyckoff_core()
            finally:
                legacy.close()

            con = sqlite3.connect(stage5)
            try:
                self.assertEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM processing_checkpoint WHERE stage='wyckoff_core' AND status='PASS'"
                    ).fetchone()[0],
                    0,
                )
                physical_rows = con.execute(
                    "SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN (?,?,?)",
                    STAGE6_DEFINITIONS,
                ).fetchone()[0]
            finally:
                con.close()
            self.assertGreater(physical_rows, 0)

            before = sha256_file(stage5)
            report = run_preflight(
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "out",
                work_root=td / "work",
                year=2023,
                symbol=SYMBOL,
                validated_commit=_git_head(ART),
                safety_floor_gb=0.0,
                max_runtime_hours=1000.0,
                max_sample_windows=2,
                sample_roots_per_window=1,
                storage_safety_factor=1.5,
                runtime_safety_factor=1.5,
                report_path=td / "preflight.json",
                plan_path=td / "plan.json",
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["inventory"]["physical_stage6_contamination_rows"], physical_rows)
            self.assertTrue(report["inventory"]["logical_stage5_boundary_filters_physical_stage6_rows"])
            self.assertEqual(sha256_file(stage5), before)

    def test_union_validator_accepts_recovered_physical_stage6_contamination_read_only(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)

            legacy = AnnualCoreEngine(
                staging_db=staging,
                output_db=stage5,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
            )
            try:
                legacy.load_bars()
                legacy.process_wyckoff_core()
            finally:
                legacy.close()

            before = sha256_file(stage5)
            con = sqlite3.connect(stage5)
            try:
                physical_rows = int(
                    con.execute(
                        "SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN (?,?,?)",
                        STAGE6_DEFINITIONS,
                    ).fetchone()[0]
                )
            finally:
                con.close()
            self.assertGreater(physical_rows, 0)

            commit = _git_head(ART)
            plan_path = td / "plan.json"
            report = run_preflight(
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "annual",
                work_root=td / "work",
                year=2023,
                symbol=SYMBOL,
                validated_commit=commit,
                safety_floor_gb=0.0,
                max_runtime_hours=1000.0,
                max_sample_windows=2,
                sample_roots_per_window=1,
                storage_safety_factor=1.5,
                runtime_safety_factor=1.5,
                report_path=td / "preflight.json",
                plan_path=plan_path,
            )
            self.assertEqual(report["status"], "PASS")
            release_path = td / "stage6_release.json"
            release = run_plan(
                plan_path=plan_path,
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "annual",
                progress_path=td / "annual_progress.json",
                release_path=release_path,
                expected_commit=commit,
            )
            self.assertEqual(release["status"], "PASS")

            union = validate_union(
                release_path=release_path,
                stage5_db=stage5,
                work_root=td / "union_work",
                output_path=td / "union.json",
            )
            self.assertEqual(union["status"], "PASS")
            self.assertEqual(
                union["physical_stage6_contamination_rows_excluded_from_official_union"],
                physical_rows,
            )
            self.assertEqual(union["legacy_stage6_overlap_hash_mismatch_count"], 0)
            self.assertTrue(union["logical_stage5_boundary_filters_physical_stage6_rows"])
            self.assertEqual(sha256_file(stage5), before)

    def test_preflight_passes_on_fixture_and_preserves_stage5(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            before = sha256_file(stage5)
            report_path = td / "preflight.json"
            plan_path = td / "plan.json"
            report = run_preflight(
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "out",
                work_root=td / "work",
                year=2023,
                symbol=SYMBOL,
                validated_commit=_git_head(ART),
                safety_floor_gb=0.0,
                max_runtime_hours=1000.0,
                max_sample_windows=2,
                sample_roots_per_window=1,
                storage_safety_factor=1.5,
                runtime_safety_factor=1.5,
                report_path=report_path,
                plan_path=plan_path,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["gates"]["full_annual_stage6_permitted_by_preflight"])
            self.assertTrue(report_path.is_file())
            self.assertTrue(plan_path.is_file())
            self.assertEqual(sha256_file(stage5), before)

    def test_orchestrator_consumes_pass_plan_and_blocks_stage7(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._build_stage5(td)
            before = sha256_file(stage5)
            commit = _git_head(ART)
            report_path = td / "preflight.json"
            plan_path = td / "plan.json"
            report = run_preflight(
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "annual",
                work_root=td / "work",
                year=2023,
                symbol=SYMBOL,
                validated_commit=commit,
                safety_floor_gb=0.0,
                max_runtime_hours=1000.0,
                max_sample_windows=2,
                sample_roots_per_window=1,
                storage_safety_factor=1.5,
                runtime_safety_factor=1.5,
                report_path=report_path,
                plan_path=plan_path,
            )
            self.assertEqual(report["status"], "PASS")
            release = run_plan(
                plan_path=plan_path,
                staging_db=staging,
                stage5_db=stage5,
                artifacts_root=ART,
                output_root=td / "annual",
                progress_path=td / "annual_progress.json",
                release_path=td / "stage6_release.json",
                expected_commit=commit,
            )
            self.assertEqual(release["status"], "PASS")
            self.assertFalse(release["stage7_auto_launch"])
            self.assertFalse(release["stage7_authorized"])
            self.assertTrue(release["groups_1_7_read_only"])
            self.assertTrue(release["stage5_read_only"])
            union_path = td / "stage6_union.json"
            union = validate_union(
                release_path=td / "stage6_release.json",
                stage5_db=stage5,
                work_root=td / "union_work",
                output_path=union_path,
            )
            self.assertEqual(union["status"], "PASS")
            self.assertTrue(union["stage6_official_pass_eligible"])
            self.assertFalse(union["stage7_authorized"])

            reference = td / "reference_for_union.sqlite"
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
            ref_i, ref_e = stage6_rows(reference)
            self.assertEqual(union["table_logical_sha256"]["school_interpretation"], logical_hash(ref_i))
            self.assertEqual(union["table_logical_sha256"]["evidence_chain"], logical_hash(ref_e))
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
