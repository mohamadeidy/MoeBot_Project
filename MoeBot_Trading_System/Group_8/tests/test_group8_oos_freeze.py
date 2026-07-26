#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import group8_freeze_oos_2024 as freeze

ART = Path(__file__).resolve().parents[1]


class OOSFreezeTests(unittest.TestCase):
    def test_freeze_binds_2023_and_authorizes_2024_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in ("ENGINE_BUILD_MANIFEST.json", "DESIGN_FREEZE_MANIFEST.json", "FROZEN_CONFIG.json"):
                shutil.copy2(ART / rel, root / rel)
            status = json.loads((ART / "STATUS.json").read_text())
            build = json.loads((ART / "ENGINE_BUILD_MANIFEST.json").read_text())
            annual = {
                "format_version": 1,
                "status": "ANNUAL_2023_PASS",
                "group": 8,
                "year": 2023,
                "engine_version": build["engine_version"],
                "schema_version": build["schema_version"],
                "config_id": build["config_id"],
                "engine_build_manifest_hash": build["manifest_hash"],
                "engine_sha256": build["identities"]["engine"]["sha256"],
                "postprocessor_sha256": build["identities"]["postprocessor"]["sha256"],
                "materializer_sha256": build["identities"]["materializer"]["sha256"],
                "logical_fingerprint": "logical-2023",
                "idempotence": "PASS",
                "clean_reconstruction": "PASS",
                "causality": "PASS",
                "no_lookahead": "PASS",
                "no_backdating": "PASS",
                "duplicate_prevention": "PASS",
                "upstream_reference_integrity": "PASS",
                "no_trading_outputs": True,
                "manifest_hash": "annual-manifest-hash",
            }
            (root / "ANNUAL_2023_VALIDATION_MANIFEST.json").write_text(json.dumps(annual) + "\n")
            status["annual_validation_2023"] = {
                "status": "PASS",
                "manifest_hash": annual["manifest_hash"],
                "engine_build_manifest_hash": build["manifest_hash"],
                "engine_sha256": annual["engine_sha256"],
                "config_id": build["config_id"],
            }
            status["annual_execution_authorized"] = False
            status["annual_execution_2023_authorized"] = False
            status["annual_execution_2024_authorized"] = False
            status["status"] = "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED"
            (root / "STATUS.json").write_text(json.dumps(status) + "\n")

            required = [
                "00_DESIGN_LOCK.md", "01_DEFINITION_REGISTRY.json", "02_SCHEMA.sql",
                "contracts/UPSTREAM_INPUT_CONTRACT.json", "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json",
                "UPSTREAM_ADAPTER_MAP.json", "UPSTREAM_VALUE_BINDINGS.json", "UPSTREAM_REFERENCE_RESOLUTION.json",
                "code/moebot_group8_engine_v0_8_0.py", "code/group8_materialize_inputs.py", "code/group8_postprocess_v0_8_0.py",
                "tests/test_group8_engine_v0_8_0.py", "tests/test_group8_lifecycle_persistence_v0_8_0.py",
                "reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json", "reports/30_ANNUAL_2023_MATERIALIZATION.json",
                "reports/31_ANNUAL_2023_ENGINE_AUDIT.json", "reports/32_ANNUAL_2023_VALIDATION.json",
                "reports/33_ANNUAL_2023_OUTPUT_FINGERPRINT.json", "reports/34_ANNUAL_2023_CLEAN_RECONSTRUCTION.json",
            ]
            for rel in required:
                p = root / rel
                if p.exists():
                    continue
                src = ART / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if src.is_file():
                    shutil.copy2(src, p)
                else:
                    p.write_text(f"fixture:{rel}\n")

            output = root / "OOS_FREEZE_MANIFEST.json"
            argv = sys.argv
            try:
                sys.argv = ["x", "--group8-root", str(root), "--output", str(output)]
                self.assertEqual(freeze.main(), 0)
            finally:
                sys.argv = argv
            manifest = json.loads(output.read_text())
            updated = json.loads((root / "STATUS.json").read_text())
            self.assertEqual(manifest["status"], "FROZEN_FOR_2024_OOS")
            self.assertEqual(manifest["annual_2023_manifest_hash"], annual["manifest_hash"])
            self.assertEqual(manifest["engine_sha256"], annual["engine_sha256"])
            self.assertTrue(manifest["immutability_policy"]["2023_result_conditioned_changes_forbidden"])
            self.assertTrue(updated["annual_execution_authorized"])
            self.assertFalse(updated["annual_execution_2023_authorized"])
            self.assertTrue(updated["annual_execution_2024_authorized"])
            self.assertEqual(updated["status"], "OOS_2024_FROZEN_AND_AUTHORIZED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
