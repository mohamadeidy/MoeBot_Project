#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_v3_base_core_assembler import _copy_stage5_logical, _release_raw_bytes, _storage_preflight, _storage_projection
from group8_v3_stage6_range_shard_executor import STAGE6_DEFINITIONS
from group8_v3_stage7_shard_executor import STAGE7_DEFINITIONS
from test_group8_engine_v0_8_0 import ART, make_stage

SYMBOL = "XAUUSD_"


class V3BaseCoreAssemblerTests(unittest.TestCase):
    def _stage5(self, td: Path) -> tuple[Path, Path]:
        staging = td / "staging.sqlite"
        stage5 = td / "stage5.sqlite"
        make_stage(staging)
        result = run_segment(
            staging_db=staging,
            output_db=stage5,
            artifacts_root=ART,
            year=2023,
            symbol=SYMBOL,
            start=0,
            end=5,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["complete"])
        return staging, stage5

    def test_logical_stage5_copy_removes_stage6_and_stage7_contamination(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging, stage5 = self._stage5(td)

            engine = AnnualCoreEngine(
                staging_db=staging,
                output_db=stage5,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
            )
            try:
                t = 1672531200
                engine._write_interpretation(
                    "wyckoff_range_context",
                    symbol=SYMBOL,
                    timeframe="M15",
                    direction="neutral",
                    event_time=t,
                    confirmation_time=t,
                    availability_time=t,
                    upstream_refs=[],
                )
                engine._write_interpretation(
                    "ict_draw_on_liquidity_context",
                    symbol=SYMBOL,
                    timeframe="M15",
                    direction="bullish",
                    event_time=t + 60,
                    confirmation_time=t + 60,
                    availability_time=t + 60,
                    upstream_refs=[],
                )
                engine.out.commit()
            finally:
                engine.close()

            cleaned = td / "cleaned.sqlite"
            report = _copy_stage5_logical(
                stage5_db=stage5,
                output_db=cleaned,
                schema_sql=ART / "02_SCHEMA.sql",
            )
            self.assertEqual(report["stage6_contamination_interpretations_removed"], 1)
            self.assertEqual(report["stage7_contamination_interpretations_removed"], 1)

            defs = tuple(STAGE6_DEFINITIONS) + tuple(STAGE7_DEFINITIONS)
            q = ",".join("?" for _ in defs)
            con = sqlite3.connect(cleaned)
            try:
                remaining = int(
                    con.execute(
                        f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",
                        defs,
                    ).fetchone()[0]
                )
                self.assertEqual(remaining, 0)
                self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                con.close()

            source = sqlite3.connect(stage5)
            try:
                source_count = int(
                    source.execute(
                        f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",
                        defs,
                    ).fetchone()[0]
                )
                self.assertEqual(source_count, 2)
            finally:
                source.close()

    def test_logical_stage5_copy_rejects_post_stage5_pass_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            _staging, stage5 = self._stage5(td)

            con = sqlite3.connect(stage5)
            con.row_factory = sqlite3.Row
            try:
                row = con.execute("SELECT * FROM processing_checkpoint LIMIT 1").fetchone()
                self.assertIsNotNone(row)
                cols = [str(x[1]) for x in con.execute("PRAGMA table_info(processing_checkpoint)")]
                values = [row[c] for c in cols]
                values[cols.index("stage")] = "ict_core"
                values[cols.index("status")] = "PASS"
                placeholders = ",".join("?" for _ in cols)
                quoted = ",".join(f'"{c}"' for c in cols)
                con.execute(
                    f"INSERT OR REPLACE INTO processing_checkpoint({quoted}) VALUES({placeholders})",
                    values,
                )
                con.commit()
            finally:
                con.close()

            with self.assertRaisesRegex(RuntimeError, "post-Stage5 PASS checkpoints"):
                _copy_stage5_logical(
                    stage5_db=stage5,
                    output_db=td / "cleaned.sqlite",
                    schema_sql=ART / "02_SCHEMA.sql",
                )

    def test_storage_projection_and_release_accounting(self):
        s6 = {"shards": [{"file_size_bytes": 10}, {"file_size_bytes": 20}]}
        s7 = {"total_raw_bytes": 40}
        self.assertEqual(_release_raw_bytes(s6, stage=6), 30)
        self.assertEqual(_release_raw_bytes(s7, stage=7), 40)
        self.assertEqual(
            _storage_projection(
                stage5_bytes=100,
                stage6_bytes=30,
                stage7_bytes=40,
                size_safety_factor=1.1,
            ),
            188,
        )
        with self.assertRaises(ValueError):
            _storage_projection(
                stage5_bytes=100,
                stage6_bytes=30,
                stage7_bytes=40,
                size_safety_factor=0.99,
            )

    def test_storage_preflight_fails_before_assembly_when_safe_space_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            stage5 = td / "stage5.sqlite"
            stage5.write_bytes(b"x" * 1024)
            output = td / "out" / "base.sqlite"
            work = td / "work"
            s6 = {"total_output_bytes": 2048}
            s7 = {"total_raw_bytes": 4096}
            with patch(
                "group8_v3_base_core_assembler.shutil.disk_usage",
                return_value=SimpleNamespace(free=1_000_000_000),
            ):
                with self.assertRaisesRegex(RuntimeError, "storage preflight failed"):
                    _storage_preflight(
                        stage5_db=stage5,
                        stage6_release=s6,
                        stage7_release=s7,
                        output_db=output,
                        work_root=work,
                        disk_safety_floor_gb=0.0,
                        size_safety_factor=1.0,
                    )
            self.assertFalse(output.exists())

    def test_storage_preflight_passes_with_required_reserve(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            stage5 = td / "stage5.sqlite"
            stage5.write_bytes(b"x" * 1024)
            output = td / "out" / "base.sqlite"
            work = td / "work"
            s6 = {"total_output_bytes": 2048}
            s7 = {"total_raw_bytes": 4096}
            with patch(
                "group8_v3_base_core_assembler.shutil.disk_usage",
                return_value=SimpleNamespace(free=4_000_000_000),
            ):
                rec = _storage_preflight(
                    stage5_db=stage5,
                    stage6_release=s6,
                    stage7_release=s7,
                    output_db=output,
                    work_root=work,
                    disk_safety_floor_gb=0.0,
                    size_safety_factor=1.0,
                )
            self.assertTrue(rec["storage_gate_pass"])
            self.assertGreater(rec["output_required_bytes"], rec["projected_output_upper_bound_bytes"])


if __name__ == "__main__":
    unittest.main()
