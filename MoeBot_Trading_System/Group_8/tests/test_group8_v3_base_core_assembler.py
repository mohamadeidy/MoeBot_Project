#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_segmented_annual_core import run_segment
from group8_v3_base_core_assembler import _copy_stage5_logical
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


if __name__ == "__main__":
    unittest.main()
