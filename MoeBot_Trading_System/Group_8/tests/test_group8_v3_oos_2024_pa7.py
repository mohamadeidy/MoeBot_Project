#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from group8_v3_oos_2024_pa7 import _policy, build_plan, finalize_release
from group8_v3_stage6_range_shard_executor import stable_hash


def write_hashed(path: Path, value: dict, field: str = "report_hash") -> dict:
    rec = dict(value)
    rec[field] = stable_hash(rec)
    path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


class V3OOS2024PA7Tests(unittest.TestCase):
    def freeze(self) -> dict:
        return {
            "status": "FROZEN_FOR_2024_OOS_V3",
            "manifest_hash": "f" * 64,
            "validated_commit": "annual-2023",
            "oos_tooling_commit": "oos-tooling",
            "pa7_2023_release_report_hash": "r" * 64,
            "pa7_2023_sizing_report_hash": "s" * 64,
            "pa7_bucket_policy_by_timeframe_scope": {
                "M1:upstream": 4,
                "M1:group8_range": 2,
            },
        }

    def test_policy_uses_only_frozen_2023_bucket_count(self):
        freeze = self.freeze()
        self.assertEqual(_policy(freeze, "M1", "upstream"), 4)
        self.assertEqual(_policy(freeze, "M1", "group8_range"), 2)
        with self.assertRaises(RuntimeError):
            _policy(freeze, "H1", "upstream")

    @patch("group8_v3_oos_2024_pa7.inventory")
    @patch("group8_v3_oos_2024_pa7.verify_freeze")
    def test_plan_uses_2024_roots_for_coverage_but_not_bucket_tuning(self, vf, inv):
        freeze = self.freeze()
        vf.return_value = freeze
        inv.return_value = write = {
            "format_version": 1,
            "status": "PASS",
            "year": 2024,
            "symbol": "XAUUSD_",
            "timeframes": ["M1"],
            "scopes": ["upstream", "group8_range"],
            "inventory": {
                "M1": {
                    "upstream": {"root_windows": ["2024-01", "2024-02"]},
                    "group8_range": {"root_windows": ["2024-02"]},
                }
            },
            "all_observed_root_windows": ["2024-01", "2024-02"],
            "oos_2024_accessed": True,
            "oos_freeze_manifest_hash": freeze["manifest_hash"],
        }
        inv.return_value["report_hash"] = stable_hash(inv.return_value)
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            plan = build_plan(
                staging_db=td / "staging.sqlite",
                artifacts_root=td,
                freeze_path=td / "freeze.json",
                symbol="XAUUSD_",
                output=td / "plan.json",
            )
        self.assertEqual(plan["worker_count"], 6)
        self.assertEqual(plan["expected_shard_count"], 10)
        self.assertEqual(plan["frozen_bucket_policy"], freeze["pa7_bucket_policy_by_timeframe_scope"])
        self.assertTrue(plan["bucket_counts_fixed_from_2023"])
        self.assertFalse(plan["oos_conditioned_bucket_changes"])
        self.assertFalse(plan["observed_2024_values_used_for_tuning"])

    @patch("group8_v3_oos_2024_pa7.verify_freeze")
    def test_finalize_rejects_missing_worker_coverage(self, vf):
        freeze = self.freeze()
        vf.return_value = freeze
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            worker = {
                "worker_id": "M1-upstream-000",
                "timeframe": "M1",
                "scope": "upstream",
                "bucket_count": 4,
                "bucket_index": 0,
                "root_windows": ["2024-01"],
            }
            inv = {"report_hash": "i" * 64}
            plan = {
                "format_version": 1,
                "status": "PASS",
                "year": 2024,
                "symbol": "XAUUSD_",
                "freeze_manifest_hash": freeze["manifest_hash"],
                "workers": [worker],
                "root_window_inventory": inv,
                "expected_shard_count": 1,
            }
            write_hashed(td / "plan.json", plan, "plan_hash")
            with self.assertRaisesRegex(RuntimeError, "worker coverage mismatch"):
                finalize_release(
                    plan_path=td / "plan.json",
                    freeze_path=td / "freeze.json",
                    artifacts_root=td,
                    worker_report_paths=[],
                    output=td / "release.json",
                )

    @patch("group8_v3_oos_2024_pa7.verify_freeze")
    def test_finalize_rechecks_shard_bytes_and_emits_complete_release(self, vf):
        freeze = self.freeze()
        freeze["pa7_bucket_policy_by_timeframe_scope"] = {"M1:upstream": 1}
        vf.return_value = freeze
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            worker = {
                "worker_id": "M1-upstream-000",
                "timeframe": "M1",
                "scope": "upstream",
                "bucket_count": 1,
                "bucket_index": 0,
                "root_windows": ["2024-01"],
            }
            inv = {"report_hash": "i" * 64}
            plan = {
                "format_version": 1,
                "status": "PASS",
                "year": 2024,
                "symbol": "XAUUSD_",
                "freeze_manifest_hash": freeze["manifest_hash"],
                "workers": [worker],
                "root_window_inventory": inv,
                "expected_shard_count": 1,
            }
            plan = write_hashed(td / "plan.json", plan, "plan_hash")

            db = td / "shard.sqlite"
            db.write_bytes(b"verified-pa7-oos-shard")
            sha = hashlib.sha256(db.read_bytes()).hexdigest()
            manifest = {
                "status": "PASS",
                "year": 2024,
                "oos_2024_accessed": True,
                "annual_breakout_followup_finalized": True,
                "timeframe": "M1",
                "boundary_scope": "upstream",
                "causal_root_window": "2024-01",
                "bucket_index": 0,
                "bucket_count": 1,
                "shard_id": "g8shard_test",
                "file_size_bytes": db.stat().st_size,
                "sha256": sha,
                "table_row_counts": {
                    "price_action_pattern_candidate": 2,
                    "price_action_pattern_state": 2,
                },
                "table_logical_sha256": {
                    "price_action_pattern_candidate": "a" * 64,
                    "price_action_pattern_state": "b" * 64,
                },
                "definition_coverage": {"pa_breakout_exact": 2},
            }
            manifest = write_hashed(td / "shard.manifest.json", manifest, "manifest_hash")
            result = {
                "status": "PASS",
                "root_months": ["2024-01"],
                "oos_freeze_manifest_hash": freeze["manifest_hash"],
                "shards": [{"database": str(db), "manifest": str(td / "shard.manifest.json")}],
            }
            wr = {
                "format_version": 1,
                "status": "PASS",
                "scope": "GROUP8_V3_PA7_2024_OOS_WORKER",
                "year": 2024,
                "worker_id": worker["worker_id"],
                "plan_hash": plan["plan_hash"],
                "freeze_manifest_hash": freeze["manifest_hash"],
                "spec": worker,
                "result": result,
                "free_only": True,
                "paid_runner_used": False,
                "paid_service_used": False,
                "oos_2024_accessed": True,
            }
            write_hashed(td / "worker.json", wr)
            release = finalize_release(
                plan_path=td / "plan.json",
                freeze_path=td / "freeze.json",
                artifacts_root=td,
                worker_report_paths=[td / "worker.json"],
                output=td / "release.json",
            )
            self.assertEqual(release["status"], "PASS")
            self.assertTrue(release["complete_once_only_coverage"])
            self.assertEqual(release["shard_count"], 1)
            self.assertEqual(release["candidate_rows"], 2)
            self.assertEqual(release["state_rows"], 2)

            db.write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "final identity mismatch"):
                finalize_release(
                    plan_path=td / "plan.json",
                    freeze_path=td / "freeze.json",
                    artifacts_root=td,
                    worker_report_paths=[td / "worker.json"],
                    output=td / "release2.json",
                )


if __name__ == "__main__":
    unittest.main()
