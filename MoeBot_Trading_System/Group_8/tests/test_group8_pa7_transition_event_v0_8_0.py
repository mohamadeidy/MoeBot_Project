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


class Group8PA7TransitionEventTests(unittest.TestCase):
    @staticmethod
    def _insert_boundary(stage: Path, *, variant_id: str, timeframe: str, lower: float, upper: float, available_at: int) -> None:
        con = sqlite3.connect(stage)
        row = base.empty_row("group6", "imbalance_variants")
        row.update(
            variant_id=variant_id,
            timeframe=timeframe,
            variant_type="body_imbalance_candidate",
            direction="bullish",
            start_bar_id=1,
            end_bar_id=2,
            availability_time=available_at,
            lower=lower,
            upper=upper,
            size_atr=1.0,
            classification="market_imbalance_variant",
            separation_reason="transition-regression",
            record_hash=f"{variant_id}-hash",
        )
        base.insert(con, "group6__imbalance_variants", row)
        con.commit(); con.close()

    @staticmethod
    def _rows_for_boundary(engine: Group8Engine, boundary_id: str):
        rows = engine.out.execute(
            "SELECT candidate_id,definition_id,timeframe,direction,source_bar_id,event_time,confirmation_time,availability_time,features_json "
            "FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer') ORDER BY availability_time,candidate_id"
        ).fetchall()
        out = []
        for row in rows:
            feats = json.loads(row["features_json"])
            if feats.get("boundary_identity") == boundary_id:
                out.append((row, feats))
        return out

    def test_transition_only_rearm_variant_isolation_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            # Available before the first M15 bar. Upper=100 makes the alternating
            # early closes (100.2, 99.8, ...) repeatedly cross and re-arm.
            self._insert_boundary(stage, variant_id="pa7_transition_probe", timeframe="M15", lower=90.0, upper=100.0, available_at=BASE)
            engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            try:
                engine.load_bars(); engine.process_breakouts()
                first = self._rows_for_boundary(engine, "pa7_transition_probe")
                self.assertGreater(len(first), 0)

                # Persistent-state enumeration is forbidden: each stored event must
                # either be the first causal eligibility transition or follow a prior
                # eligible bar that was NOT_BEYOND for the same independent variant.
                bars = {b.id: b for b in engine.bars_by_tf[("XAUUSD_", "M15")]}
                by_variant: dict[str, list[tuple[object, dict]]] = {}
                for row, feats in first:
                    by_variant.setdefault(row["definition_id"], []).append((row, feats))
                    self.assertEqual(feats["transition_from"], "NOT_BEYOND_BOUNDARY")
                    self.assertEqual(feats["transition_to"], "BEYOND_BOUNDARY")
                    self.assertEqual(feats["pa7_variant"], row["definition_id"])
                    self.assertEqual(row["timeframe"], "M15")
                    self.assertGreaterEqual(row["availability_time"], row["confirmation_time"])
                    self.assertGreaterEqual(row["confirmation_time"], row["event_time"])
                    self.assertIn("state_key", feats)
                    self.assertIn("group6:imbalance_variants:pa7_transition_probe:", feats["state_boundary_identity"])

                self.assertIn("pa_breakout_exact", by_variant)
                self.assertIn("pa_breakout_point_buffer", by_variant)
                # ATR becomes evaluable only after the warmup and remains a separate state machine.
                self.assertIn("pa_breakout_atr_buffer", by_variant)

                state_keys = {(row["definition_id"], row["direction"], feats["state_key"]) for row, feats in first}
                variants_for_key = {}
                for definition_id, direction, key in state_keys:
                    variants_for_key.setdefault((direction, key), set()).add(definition_id)
                self.assertTrue(all(len(v) == 1 for v in variants_for_key.values()))

                # Exact bullish events after initialization must have a prior M15 bar
                # at/below the exact upper boundary, proving causal re-arm rather than
                # one record on every subsequent BEYOND bar.
                exact_bull = [(r, f) for r, f in by_variant["pa_breakout_exact"] if r["direction"] == "bullish"]
                self.assertGreaterEqual(len(exact_bull), 2)
                for row, feats in exact_bull:
                    if feats["initialization_transition"]:
                        self.assertIsNone(feats["previous_eligible_bar_id"])
                    else:
                        prev = bars[int(feats["previous_eligible_bar_id"])]
                        cur = bars[int(row["source_bar_id"])]
                        self.assertLessEqual(prev.close, 100.0)
                        self.assertGreater(cur.close, 100.0)

                # Run the stage again: deterministic immutable IDs must prevent duplicates.
                count_before = engine.out.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id LIKE 'pa_breakout_%'").fetchone()[0]
                ids_before = {r[0] for r in engine.out.execute("SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id LIKE 'pa_breakout_%'")}
                engine.process_breakouts()
                count_after = engine.out.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id LIKE 'pa_breakout_%'").fetchone()[0]
                ids_after = {r[0] for r in engine.out.execute("SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id LIKE 'pa_breakout_%'")}
                self.assertEqual(count_before, count_after)
                self.assertEqual(ids_before, ids_after)
            finally:
                engine.close()

    def test_same_boundary_id_different_timeframe_has_different_state_key(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); stage=root/"stage.sqlite"; output=root/"out.sqlite"
            base.make_stage(stage)
            self._insert_boundary(stage, variant_id="shared_boundary_id", timeframe="M15", lower=90.0, upper=100.0, available_at=BASE)
            self._insert_boundary(stage, variant_id="shared_boundary_id", timeframe="H1", lower=90.0, upper=100.0, available_at=BASE)
            engine=Group8Engine(staging_db=stage,output_db=output,artifacts_root=ART,year=2023,symbol="XAUUSD_")
            try:
                engine.load_bars(); engine.process_breakouts()
                keys={}
                for row in engine.out.execute("SELECT definition_id,timeframe,direction,features_json FROM price_action_pattern_candidate WHERE definition_id='pa_breakout_exact'"):
                    feats=json.loads(row["features_json"])
                    if feats.get("boundary_identity")!="shared_boundary_id" or row["direction"]!="bullish": continue
                    keys.setdefault(row["timeframe"],set()).add(feats["state_key"])
                self.assertIn("M15",keys); self.assertIn("H1",keys)
                self.assertTrue(keys["M15"].isdisjoint(keys["H1"]))
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
