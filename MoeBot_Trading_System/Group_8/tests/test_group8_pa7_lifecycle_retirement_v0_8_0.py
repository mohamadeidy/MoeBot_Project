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


class PA7LifecycleRetirementTests(unittest.TestCase):
    @staticmethod
    def _insert_terminal_fvg(stage: Path, *, fvg_id: str, terminal_time: int) -> None:
        con = sqlite3.connect(stage)
        fvg = base.empty_row("group6", "fvg_events")
        fvg.update(
            fvg_id=fvg_id,
            timeframe="M15",
            direction="bullish",
            creation_time=BASE,
            confirmation_time=BASE + 900,
            availability_time=BASE + 900,
            lower=99.9,
            upper=100.0,
            ce=99.95,
            size_atr=0.1,
            associated_leg_id="leg_bull",
            associated_group3_event_id=None,
            associated_group5_event_id=None,
            group2_state_id=None,
            group3_state_id=None,
            clean_displacement=1,
            formation_quality=1.0,
            record_hash=f"{fvg_id}-hash",
        )
        base.insert(con, "group6__fvg_events", fvg)
        tr = base.empty_row("group6", "fvg_state_transitions")
        tr.update(
            transition_id=f"{fvg_id}-terminal",
            fvg_id=fvg_id,
            transition_ordinal=1,
            bar_id=8,
            transition_time=terminal_time,
            event_type="traversed",
            fill_state="fully_filled",
            directional_validity="invalidated",
            max_penetration=1.0,
            record_hash=f"{fvg_id}-terminal-hash",
        )
        base.insert(con, "group6__fvg_state_transitions", tr)
        con.commit(); con.close()

    @staticmethod
    def _insert_zone_invalidation(stage: Path, *, zone_id: str, terminal_time: int) -> None:
        con = sqlite3.connect(stage)
        tr = base.empty_row("group4", "zone_transitions")
        tr.update(
            transition_id=f"{zone_id}-invalid",
            zone_id=zone_id,
            bar_id=10,
            transition_time=terminal_time,
            from_status="active",
            to_status="invalidated",
            role_after="broken",
            reason="lifecycle-regression",
            transition_hash=f"{zone_id}-invalid-hash",
        )
        base.insert(con, "group4__zone_transitions", tr)
        con.commit(); con.close()

    @staticmethod
    def _breakout_rows(engine: Group8Engine, boundary_id: str):
        out = []
        for r in engine.out.execute(
            "SELECT candidate_id,definition_id,direction,availability_time,features_json "
            "FROM price_action_pattern_candidate WHERE definition_id IN "
            "('pa_breakout_exact','pa_breakout_atr_buffer','pa_breakout_point_buffer') "
            "ORDER BY availability_time,candidate_id"
        ):
            f = json.loads(r["features_json"])
            if f.get("boundary_identity") == boundary_id:
                out.append((r, f))
        return out

    def test_group6_fvg_retires_at_first_traversed_invalidated_transition(self):
        terminal = BASE + 8 * 900
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            self._insert_terminal_fvg(stage, fvg_id="fvg_terminal_probe", terminal_time=terminal)
            engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            try:
                engine.load_bars()
                catalog = engine._pa7_boundary_catalog("XAUUSD_", "M15")
                bnd = next(x for x in catalog if x["group"] == "group6" and x["type"] == "fvg_events" and x["id"] == "fvg_terminal_probe")
                self.assertEqual(bnd["inactive_at"], terminal)
                self.assertTrue(engine._pa7_boundary_active_at(bnd, terminal - 1))
                self.assertFalse(engine._pa7_boundary_active_at(bnd, terminal))
                self.assertFalse(engine._pa7_boundary_active_at(bnd, terminal + 900))

                engine.process_breakouts()
                rows = self._breakout_rows(engine, "fvg_terminal_probe")
                self.assertGreater(len(rows), 0)
                self.assertTrue(all(int(r["availability_time"]) < terminal for r, _ in rows))

                before = {r["candidate_id"] for r, _ in rows}
                engine.process_breakouts()
                after = {r["candidate_id"] for r, _ in self._breakout_rows(engine, "fvg_terminal_probe")}
                self.assertEqual(before, after)
            finally:
                engine.close()

    def test_group8_bounded_range_retires_at_locked_zone_invalidation(self):
        terminal = BASE + 10 * 900
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            self._insert_zone_invalidation(stage, zone_id="zhigh", terminal_time=terminal)
            engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            try:
                engine.load_bars(); engine.process_bounded_ranges()
                range_rows = engine.out.execute(
                    "SELECT candidate_id,availability_time,features_json FROM price_action_pattern_candidate "
                    "WHERE definition_id='pa_bounded_range_context' ORDER BY availability_time,candidate_id"
                ).fetchall()
                target = None
                for r in range_rows:
                    f = json.loads(r["features_json"])
                    if f.get("lower_zone_id") == "zlow" and f.get("upper_zone_id") == "zhigh" and int(r["availability_time"]) < terminal:
                        target = r; break
                self.assertIsNotNone(target)
                catalog = engine._pa7_boundary_catalog("XAUUSD_", "M15")
                bnd = next(x for x in catalog if x["group"] == "group8" and x["id"] == target["candidate_id"])
                self.assertEqual(bnd["inactive_at"], terminal)
                self.assertTrue(engine._pa7_boundary_active_at(bnd, terminal - 1))
                self.assertFalse(engine._pa7_boundary_active_at(bnd, terminal))

                engine.process_breakouts()
                rows = self._breakout_rows(engine, str(target["candidate_id"]))
                self.assertTrue(all(int(r["availability_time"]) < terminal for r, _ in rows))
            finally:
                engine.close()

    def test_nonterminal_group6_objects_remain_right_censored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            try:
                engine.load_bars()
                catalog = engine._pa7_boundary_catalog("XAUUSD_", "M15")
                for bnd in catalog:
                    if bnd["group"] == "group6" and bnd["type"] in {"imbalance_variants", "liquidity_voids", "bpr_relations"}:
                        self.assertIsNone(bnd.get("inactive_at"))
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
