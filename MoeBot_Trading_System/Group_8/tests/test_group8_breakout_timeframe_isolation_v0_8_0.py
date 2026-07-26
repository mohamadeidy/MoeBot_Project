#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_group8_engine_v0_8_0 as base
from moebot_group8_engine_v0_8_0 import Group8Engine

ART = base.ART
BASE = 1_700_000_000


class Group8BreakoutTimeframeIsolationTests(unittest.TestCase):
    @staticmethod
    def _insert_group6_boundary(stage: Path, *, variant_id: str, timeframe: str, lower: float, upper: float) -> None:
        con = sqlite3.connect(stage)
        row = base.empty_row("group6", "imbalance_variants")
        row.update(
            variant_id=variant_id,
            timeframe=timeframe,
            variant_type="body_imbalance_candidate",
            direction="bullish",
            start_bar_id=1,
            end_bar_id=2,
            availability_time=BASE + 900,
            lower=lower,
            upper=upper,
            size_atr=1.0,
            classification="market_imbalance_variant",
            separation_reason="separate_from_classic_fvg",
            record_hash=f"{variant_id}-hash",
        )
        base.insert(con, "group6__imbalance_variants", row)
        con.commit()
        con.close()

    def test_group6_breakout_boundaries_are_same_timeframe_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stage = root / "stage.sqlite"
            output = root / "out.sqlite"
            base.make_stage(stage)

            # These levels deliberately guarantee a false cross-timeframe breakout
            # if the Group6 branch omits timeframe filtering:
            # - H1 bars are far below the M15-only boundary.
            # - M15 bars are far above the H1-only boundary.
            self._insert_group6_boundary(
                stage,
                variant_id="tf_m15_only",
                timeframe="M15",
                lower=200.0,
                upper=201.0,
            )
            self._insert_group6_boundary(
                stage,
                variant_id="tf_h1_only",
                timeframe="H1",
                lower=50.0,
                upper=51.0,
            )

            engine = Group8Engine(
                staging_db=stage,
                output_db=output,
                artifacts_root=ART,
                year=2023,
                symbol="XAUUSD_",
            )
            try:
                engine.load_bars()
                m15_bar = engine.bars_by_tf[("XAUUSD_", "M15")][-1]
                h1_bar = engine.bars_by_tf[("XAUUSD_", "H1")][-1]

                m15_group6 = {
                    str(r["id"])
                    for r in engine._boundary_rows_for_bar(m15_bar)
                    if r["group"] == "group6"
                }
                h1_group6 = {
                    str(r["id"])
                    for r in engine._boundary_rows_for_bar(h1_bar)
                    if r["group"] == "group6"
                }

                self.assertIn("tf_m15_only", m15_group6)
                self.assertNotIn("tf_h1_only", m15_group6)
                self.assertIn("tf_h1_only", h1_group6)
                self.assertNotIn("tf_m15_only", h1_group6)

                engine.process_breakouts()
                rows = engine.out.execute(
                    "SELECT timeframe,upstream_refs_json FROM price_action_pattern_candidate "
                    "WHERE definition_id='pa_breakout_exact' ORDER BY candidate_id"
                ).fetchall()

                seen = {"tf_m15_only": 0, "tf_h1_only": 0}
                violations: list[tuple[str, str, str]] = []
                expected_tf = {"tf_m15_only": "M15", "tf_h1_only": "H1"}
                for row in rows:
                    for ref in json.loads(row["upstream_refs_json"]):
                        if ref.get("source_group") != "group6" or ref.get("source_type") != "imbalance_variants":
                            continue
                        source_id = str(ref.get("source_id"))
                        if source_id not in expected_tf:
                            continue
                        seen[source_id] += 1
                        if row["timeframe"] != expected_tf[source_id] or ref.get("timeframe") != expected_tf[source_id]:
                            violations.append((source_id, str(row["timeframe"]), str(ref.get("timeframe"))))

                self.assertGreater(seen["tf_m15_only"], 0)
                self.assertGreater(seen["tf_h1_only"], 0)
                self.assertEqual(violations, [])
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
