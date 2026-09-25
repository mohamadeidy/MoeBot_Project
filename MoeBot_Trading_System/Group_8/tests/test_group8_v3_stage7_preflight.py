#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from group8_segmented_annual_core import run_segment
from group8_v3_stage7_preflight import _git_head, run_preflight
from moebot_group8_engine_v0_8_0 import sha256_file, stable_hash
from test_group8_engine_v0_8_0 import ART, make_stage

SYMBOL = "XAUUSD_"


class Group8V3Stage7PreflightTests(unittest.TestCase):
    def test_stage7_preflight_is_read_only_and_never_authorizes_annual_run(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            staging = td / "staging.sqlite"
            stage5 = td / "stage5.sqlite"
            make_stage(staging)
            run_segment(
                staging_db=staging,
                output_db=stage5,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
                start=0,
                end=5,
            )
            before = sha256_file(stage5)

            release = {
                "format_version": 1,
                "status": "PASS",
                "stage": 6,
                "stage5_database_sha256": before,
                "total_output_bytes": 1_000_000,
            }
            release["release_hash"] = stable_hash(release)
            release_path = td / "stage6_release.json"
            release_path.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")

            union = {
                "format_version": 1,
                "status": "PASS",
                "stage": 6,
                "stage6_official_pass_eligible": True,
                "stage6_release_hash": release["release_hash"],
                "stage5_database_sha256": before,
                "table_row_counts": {
                    "school_interpretation": 1000,
                    "evidence_chain": 2000,
                },
            }
            union["report_hash"] = stable_hash(union)
            union_path = td / "stage6_union.json"
            union_path.write_text(json.dumps(union, indent=2, sort_keys=True) + "\n")

            report = run_preflight(
                staging_db=staging,
                stage5_db=stage5,
                stage6_release_path=release_path,
                stage6_union_path=union_path,
                artifacts_root=ART,
                year=2023,
                symbol=SYMBOL,
                validated_commit=_git_head(ART),
                report_path=td / "stage7_preflight.json",
            )
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["stage6_official_pass_prerequisite"])
            self.assertFalse(report["stage7_authorized"])
            self.assertFalse(report["stage7_auto_launch"])
            self.assertFalse(report["full_annual_stage7_permitted_by_preflight"])
            self.assertEqual(report["physical_stage7_contamination_rows"], 0)
            self.assertEqual(report["ict_core_pass_checkpoint_count"], 0)
            self.assertIn("ict_premium_discount_context", report["definition_cardinality_current_engine"])
            self.assertIn("inversion", report["return_to_imbalance_lifecycle_coverage"])
            self.assertFalse(
                report["return_to_imbalance_lifecycle_coverage"]["bpr"]["causal_touch_visit_adapter_available"]
            )
            self.assertEqual(sha256_file(stage5), before)

    def test_2024_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            with self.assertRaises(RuntimeError):
                run_preflight(
                    staging_db=td / "none.sqlite",
                    stage5_db=td / "none2.sqlite",
                    stage6_release_path=td / "release.json",
                    stage6_union_path=td / "union.json",
                    artifacts_root=ART,
                    year=2024,
                    symbol=SYMBOL,
                    validated_commit="x",
                    report_path=td / "report.json",
                )


if __name__ == "__main__":
    unittest.main()
