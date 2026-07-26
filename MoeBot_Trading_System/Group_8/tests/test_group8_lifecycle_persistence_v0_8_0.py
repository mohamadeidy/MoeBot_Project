#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_group8_engine_v0_8_0 as base
from group8_postprocess_v0_8_0 import (
    continuation_structure_valid,
    ensure_initial_hypothesis_lifecycle,
)
from moebot_group8_engine_v0_8_0 import Group8Engine

ART = base.ART


class Group8LifecyclePersistenceTests(unittest.TestCase):
    def _run(self, stage: Path, output: Path):
        engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
        report = engine.run()
        engine.close()
        self.assertEqual(report["status"], "PASS", report["failures"])
        return report

    def test_full_pipeline_persists_pattern_states_lifecycle_audit_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage); self._run(stage, output)
            con = sqlite3.connect(output)
            patterns = con.execute("SELECT COUNT(*) FROM price_action_pattern_candidate").fetchone()[0]
            creation_states = con.execute("SELECT COUNT(*) FROM price_action_pattern_state WHERE state_ordinal=0").fetchone()[0]
            hypotheses = con.execute("SELECT COUNT(*) FROM narrative_hypothesis").fetchone()[0]
            initial = con.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event WHERE lifecycle_ordinal=0").fetchone()[0]
            terminal = con.execute("SELECT COUNT(DISTINCT hypothesis_id) FROM hypothesis_lifecycle_event WHERE lifecycle_state IN ('invalidated','completed_descriptive','right_censored')").fetchone()[0]
            audits = con.execute("SELECT COUNT(*) FROM group8_audit_evidence").fetchone()[0]
            checkpoints = con.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0]
            self.assertEqual(patterns, creation_states)
            self.assertEqual(hypotheses, initial)
            self.assertEqual(hypotheses, terminal)
            self.assertGreater(audits, 0)
            self.assertGreater(checkpoints, 0)
            con.close()

    def test_extended_idempotence_includes_state_lifecycle_invalidation_audit_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage); self._run(stage, output)
            tables = [
                "price_action_pattern_candidate", "price_action_pattern_state", "school_interpretation",
                "narrative_hypothesis", "hypothesis_lifecycle_event", "invalidation_record",
                "group8_audit_evidence", "processing_checkpoint", "evidence_chain",
            ]
            con = sqlite3.connect(output)
            before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            checkpoints_before = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()
            con.close()
            self._run(stage, output)
            con = sqlite3.connect(output)
            after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            checkpoints_after = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()
            con.close()
            self.assertEqual(before, after)
            self.assertEqual(checkpoints_before, checkpoints_after)

    def test_initial_lifecycle_helper_repairs_interruption_without_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            hid = "g8h_interruption_fixture"
            row = {
                "hypothesis_id": hid,
                "definition_id": "pa_structural_pullback",
                "school_id": "school_classical_price_action_v1",
                "symbol": "XAUUSD_", "timeframe": "M15", "direction": "bullish",
                "event_time": 1700000900, "confirmation_time": 1700000900, "availability_time": 1700000900,
                "initial_state": "active_supported", "mandatory_evidence_complete": 1, "ambiguous": 0,
                "supporting_evidence_count": 0, "conflicting_evidence_count": 0,
                "evidence_strength_json": "{}", "upstream_refs_json": "[]", "reasons_json": "[]",
                "hypothesis_hash": "interruption-fixture-hash",
            }
            cols = list(row)
            engine.out.execute(
                f"INSERT INTO narrative_hypothesis ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                [row[c] for c in cols],
            )
            engine.out.commit()
            ensure_initial_hypothesis_lifecycle(engine, hid, "active_supported", event_time=1700000900, availability_time=1700000900)
            ensure_initial_hypothesis_lifecycle(engine, hid, "active_supported", event_time=1700000900, availability_time=1700000900)
            count = engine.out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event WHERE hypothesis_id=? AND lifecycle_ordinal=0", (hid,)).fetchone()[0]
            self.assertEqual(count, 1)
            engine.close()

    def test_bounded_range_invalidation_and_causal_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            con = sqlite3.connect(stage)
            columns = [r[1] for r in con.execute("PRAGMA table_info('group4__zone_transitions')")]
            row = {c: None for c in columns}
            row.update(transition_id="zlow_invalid", zone_id="zlow", bar_id=22, transition_time=1700000000+22*900,
                       from_status="active", to_status="invalidated", role_after="support", reason="fixture_break", transition_hash="zlow-invalid-hash")
            con.execute(f"INSERT INTO group4__zone_transitions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])
            con.commit(); con.close()
            self._run(stage, output)
            con = sqlite3.connect(output)
            inv = con.execute("SELECT event_time,confirmation_time,availability_time FROM invalidation_record WHERE rule_id='pa_bounded_range_context.invalidation_rule' LIMIT 1").fetchone()
            self.assertIsNotNone(inv)
            self.assertLessEqual(inv[0], inv[1]); self.assertLessEqual(inv[1], inv[2])
            state = con.execute("SELECT COUNT(*) FROM price_action_pattern_state WHERE state='invalidated'").fetchone()[0]
            self.assertGreater(state, 0)
            con.close()

    def test_bounded_range_right_censors_without_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage); self._run(stage, output)
            con = sqlite3.connect(output)
            count = con.execute("SELECT COUNT(*) FROM price_action_pattern_state WHERE state='right_censored'").fetchone()[0]
            self.assertGreater(count, 0)
            con.close()

    def test_continuation_requires_structure_valid_until_completion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            con = sqlite3.connect(stage); con.row_factory = sqlite3.Row
            st = dict(con.execute("SELECT * FROM group3__structure_states WHERE state_id='st_bear_ext'").fetchone())
            counter = dict(con.execute("SELECT l.*,v.availability_time validation_availability FROM group6__displacement_legs l JOIN group6__displacement_validation_events v USING(leg_id) WHERE l.leg_id='leg_bull'").fetchone())
            later = dict(con.execute("SELECT l.*,v.availability_time validation_availability FROM group6__displacement_legs l JOIN group6__displacement_validation_events v USING(leg_id) WHERE l.leg_id='leg_bear'").fetchone())
            cols = [r[1] for r in con.execute("PRAGMA table_info('group3__break_events')")]
            row = {c: None for c in cols}
            row.update(event_id="be_block_bear_cont", symbol="XAUUSD_", timeframe="M15", layer="external",
                       candidate_id="be_block_bear_cont_c", event_type="MSS", direction="up", break_kind="reversal",
                       level_price=101, level_swing_id="sw0", candidate_time=1700000000+20*900,
                       resolved_time=1700000000+21*900, candidate_bar_id=20, resolved_bar_id=21,
                       strength_score=1, strong_break=1, outcome="accepted", feature_hash="block-hash")
            con.execute(f"INSERT INTO group3__break_events ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
            con.commit()
            self.assertFalse(continuation_structure_valid(type('E',(object,),{'input':con})(), st, counter, later, "bearish"))
            con.close()
            self._run(stage, output)
            con = sqlite3.connect(output)
            count = con.execute("SELECT COUNT(*) FROM narrative_hypothesis WHERE definition_id='pa_continuation_after_pullback' AND direction='bearish'").fetchone()[0]
            self.assertEqual(count, 0)
            con.close()

    def test_missing_dependency_table_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            con = sqlite3.connect(stage); con.execute("DROP TABLE group3__break_events"); con.commit(); con.close()
            with self.assertRaises(Exception):
                Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")

    def test_partial_dependency_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            con = sqlite3.connect(stage)
            con.execute("ALTER TABLE group3__break_events RENAME TO group3__break_events_full")
            con.execute("CREATE TABLE group3__break_events(event_id TEXT,timeframe TEXT)")
            con.commit(); con.close()
            with self.assertRaises(Exception):
                Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023, symbol="XAUUSD_")

    def test_row_order_stability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); a = root / "a.sqlite"; b = root / "b.sqlite"; oa = root / "oa.sqlite"; ob = root / "ob.sqlite"
            base.make_stage(a); shutil.copy2(a, b)
            con = sqlite3.connect(b)
            con.execute("CREATE TABLE source__bars_reordered AS SELECT * FROM source__bars ORDER BY id DESC")
            con.execute("DROP TABLE source__bars")
            con.execute("ALTER TABLE source__bars_reordered RENAME TO source__bars")
            con.commit(); con.close()
            self._run(a, oa); self._run(b, ob)
            self.assertEqual(base.Group8Tests._ids_by_table(oa), base.Group8Tests._ids_by_table(ob))

    def test_missing_bar_gap_remains_causal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"
            base.make_stage(stage)
            con = sqlite3.connect(stage); con.execute("DELETE FROM source__bars WHERE id=10"); con.commit(); con.close()
            report = self._run(stage, output)
            self.assertFalse(any("causality" in str(x).lower() for x in report["failures"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
