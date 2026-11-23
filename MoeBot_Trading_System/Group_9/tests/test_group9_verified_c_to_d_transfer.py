#!/usr/bin/env python3
"""Safety regressions for Group9 C: -> D: transfer; synthetic tiny files only."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

CODE = Path(__file__).resolve().parents[1] / "code" / "group9_verified_c_to_d_transfer.py"
sys.path.insert(0, str(CODE.parent))
spec = importlib.util.spec_from_file_location("g9_archive_transfer", CODE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class VerifiedTransferTests(unittest.TestCase):
    def setUp(self):
        self.a = tempfile.TemporaryDirectory(prefix="g9_transfer_active_", dir=r"C:\MoeBotWork")
        self.addCleanup(self.a.cleanup)
        self.v = tempfile.TemporaryDirectory(prefix="g9_transfer_vault_", dir=r"D:\MoeBotVault")
        self.addCleanup(self.v.cleanup)
        self.active = Path(self.a.name)
        self.vault = Path(self.v.name)
        self.raw = self.active / "synthetic.sqlite"
        self.archive = self.active / "synthetic.sqlite.zst"
        self.report = self.active / "synthetic.report.json"
        self.raw.write_bytes(b"FAKE_SQLITE_BYTES_ONLY_FOR_TRANSFER_TEST")
        self.archive.write_bytes(b"FAKE_ZSTD_BYTES_ONLY_FOR_TRANSFER_TEST")
        doc = {
            "status": "PASS_ONE_EXACT_COMPLETE_SHARD",
            "shard_key": "synthetic_only_not_annual",
            "source_roots_complete": True, "candidate_count": 1,
            "archive_compression_roundtrip_verified": True,
            "archive_path": str(self.archive),
            "archive_bytes": self.archive.stat().st_size,
            "archive_sha256": mod.sha_file(self.archive),
            "output_path": str(self.raw),
            "output_bytes": self.raw.stat().st_size,
            "output_sha256": mod.sha_file(self.raw),
        }
        doc["report_hash"] = mod.stable(doc)
        self.report.write_text(json.dumps(doc), encoding="utf-8")

    def test_transfer_cleanup_and_repeat_after_source_removed(self):
        result = mod.vault_transfer(self.report, self.active, self.vault)
        self.assertEqual(result["status"], "TRANSFER_VERIFIED")
        self.assertTrue(self.raw.exists())
        self.assertTrue(self.archive.exists())
        result = mod.vault_transfer(self.report, self.active, self.vault, cleanup=True)
        self.assertEqual(result["status"], "ALREADY_VERIFIED")
        self.assertFalse(self.raw.exists())
        self.assertFalse(self.archive.exists())
        self.assertTrue(Path(result["vault_path"]).is_file())
        self.assertTrue(Path(result["receipt_path"]).is_file())
        result = mod.vault_transfer(self.report, self.active, self.vault, cleanup=True)
        self.assertEqual(result["status"], "ALREADY_VERIFIED")

    def test_report_identity_drift_blocks(self):
        data = json.loads(self.report.read_text())
        data["candidate_count"] = 2
        self.report.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "report_identity_mismatch"):
            mod.vault_transfer(self.report, self.active, self.vault, cleanup=True)
        self.assertTrue(self.raw.exists())
        self.assertTrue(self.archive.exists())

    def test_archive_drift_blocks_without_deletion(self):
        self.archive.write_bytes(b"BROKEN_ARCHIVE")
        with self.assertRaisesRegex(RuntimeError, "C_archive_identity_mismatch"):
            mod.vault_transfer(self.report, self.active, self.vault, cleanup=True)
        self.assertTrue(self.raw.exists())
        self.assertTrue(self.archive.exists())

    def test_vault_drift_blocks_cleanup(self):
        first = mod.vault_transfer(self.report, self.active, self.vault)
        Path(first["vault_path"]).write_bytes(b"BROKEN")
        with self.assertRaisesRegex(RuntimeError, "vault_contents_drift"):
            mod.vault_transfer(self.report, self.active, self.vault, cleanup=True)
        self.assertTrue(self.raw.exists())
        self.assertTrue(self.archive.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
