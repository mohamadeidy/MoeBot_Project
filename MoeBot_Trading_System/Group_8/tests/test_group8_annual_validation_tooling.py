#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from group8_annual_validation import validate
from group8_sqlite_fingerprint import fingerprint
from moebot_group8_engine_v0_8_0 import Group8Engine
from test_group8_engine_v0_8_0 import ART, make_stage


class AnnualValidationToolingTests(unittest.TestCase):
    def _build(self, root: Path, output: Path):
        stage = root / "stage.sqlite"
        if not stage.exists():
            make_stage(stage)
        engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=ART, year=2023)
        try:
            report = engine.run()
        finally:
            engine.close()
        self.assertEqual(report["status"], "PASS")
        engine_report = root / "engine_audit.json"
        engine_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        material = {
            "format_version": 1,
            "status": "PASS",
            "year": 2023,
            "engine_version": "0.8.0",
            "schema_version": "8.0.0",
            "config_id": "cfg8_0e5a4dc3394efff2d2d54c20b0a93fba66b6ddd3d8e8a28a70292e6bb5755ded",
            "logical_dependency_lineage_id": "moebot-group8-upstream-corrected-v3-g7-v075-v1",
            "database_identities": {},
            "table_counts": {},
            "disk_safe_sequential_materialization": True,
            "read_only_upstream": True,
            "failures": [],
        }
        import hashlib
        material["report_hash"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        material_report = root / "materializer.json"
        material_report.write_text(json.dumps(material, indent=2, sort_keys=True) + "\n")
        return stage, material_report, engine_report

    def test_synthetic_annual_audit_and_rerun_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); output = root / "out.sqlite"
            stage, material, engine_report = self._build(root, output)
            args = argparse.Namespace(group8_root=ART, staging_db=stage, output_db=output, materializer_report=material, engine_audit=engine_report, year=2023, output=root / "annual.json")
            report = validate(args)
            self.assertEqual(report["status"], "PASS", report["failures"])
            first = fingerprint(output)
            self._build(root, output)
            second = fingerprint(output)
            self.assertEqual(first["logical_sha256"], second["logical_sha256"])
            self.assertEqual({k:v["logical_sha256"] for k,v in first["tables"].items()}, {k:v["logical_sha256"] for k,v in second["tables"].items()})

    def test_clean_reconstruction_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); a = root / "a.sqlite"; b = root / "b.sqlite"
            self._build(root, a)
            self._build(root, b)
            fa, fb = fingerprint(a), fingerprint(b)
            self.assertEqual(fa["logical_sha256"], fb["logical_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
