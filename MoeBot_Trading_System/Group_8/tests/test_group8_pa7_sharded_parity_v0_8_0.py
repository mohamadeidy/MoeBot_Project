#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from moebot_group8_engine_v0_8_0 import Group8Engine
from group8_pa7_shard_executor import CHAIN_DEFINITIONS, ShardSpec, bucket_for_root, run_shard
from test_group8_engine_v0_8_0 import ART, make_stage


def candidate_map(db: Path) -> dict[str, str]:
    con = sqlite3.connect(db)
    try:
        q = ",".join("?" for _ in CHAIN_DEFINITIONS)
        return {r[0]: r[1] for r in con.execute(f"SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ({q})", CHAIN_DEFINITIONS)}
    finally:
        con.close()


def state_map(db: Path, candidate_ids: set[str]) -> dict[str, str]:
    con = sqlite3.connect(db)
    try:
        result: dict[str, str] = {}
        ids = sorted(candidate_ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            if not chunk:
                continue
            q = ",".join("?" for _ in chunk)
            for row in con.execute(f"SELECT state_event_id,state_hash FROM price_action_pattern_state WHERE candidate_id IN ({q})", chunk):
                result[row[0]] = row[1]
        return result
    finally:
        con.close()


class ShardedPA7ParityTest(unittest.TestCase):
    def test_bucket_rule_is_total_and_deterministic(self) -> None:
        roots = [f"group6:fvg_events:fvg{i}" for i in range(100)]
        first = [bucket_for_root(r, 8) for r in roots]
        second = [bucket_for_root(r, 8) for r in roots]
        self.assertEqual(first, second)
        self.assertTrue(all(0 <= x < 8 for x in first))
        with self.assertRaises(ValueError):
            bucket_for_root("x", 3)

    def test_union_of_pa7_shards_matches_monolithic_reference_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            stage = t / "stage.sqlite"
            mono = t / "monolithic.sqlite"
            make_stage(stage)

            engine = Group8Engine(staging_db=stage, output_db=mono, artifacts_root=ART, year=2023, symbol="XAUUSD_")
            try:
                engine.load_bars()
                engine.process_bounded_ranges()
                engine.process_breakouts()
                engine.process_failed_breakouts_and_retests()
            finally:
                engine.close()

            expected_candidates = candidate_map(mono)
            expected_states = state_map(mono, set(expected_candidates))
            self.assertGreater(len(expected_candidates), 0)

            union_candidates: dict[str, str] = {}
            union_states: dict[str, str] = {}
            # The permanent fixture has M15 and H1. Four buckets force actual
            # partitioning while remaining fast enough for the technical gate.
            for timeframe in ("M15", "H1"):
                for bucket in range(4):
                    work = t / f"work_{timeframe}_{bucket}.sqlite"
                    out = t / f"shard_{timeframe}_{bucket}.sqlite"
                    manifest = t / f"manifest_{timeframe}_{bucket}.json"
                    run_shard(
                        staging_db=stage,
                        work_db=work,
                        output_db=out,
                        artifacts_root=ART,
                        spec=ShardSpec(2023, "XAUUSD_", timeframe, None, 4, bucket),
                        manifest_path=manifest,
                    )
                    cmap = candidate_map(out)
                    smap = state_map(out, set(cmap))
                    for cid, h in cmap.items():
                        self.assertNotIn(cid, union_candidates, f"domain candidate duplicated across shards: {cid}")
                        union_candidates[cid] = h
                    for sid, h in smap.items():
                        self.assertNotIn(sid, union_states, f"domain state duplicated across shards: {sid}")
                        union_states[sid] = h

            self.assertEqual(expected_candidates, union_candidates)
            self.assertEqual(expected_states, union_states)


if __name__ == "__main__":
    unittest.main()
