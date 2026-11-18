#!/usr/bin/env python3
"""Offline validation of Group9 PA7 official release chunk downloader."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "code" / "group9_recover_official_pa7_staging.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("g9_pa7_download", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "segments").mkdir()
        self.patch_root = patch.object(module, "DEST_ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.content = b"a" * 1000
        self.calls = 0
        self.status = "206"
        self.range_offset = 0

    def fake_curl(self, cmd, *, capture_output, text, timeout):
        self.calls += 1
        output = Path(cmd[cmd.index("-o") + 1])
        headers = Path(cmd[cmd.index("-D") + 1])
        output.write_bytes(self.content)
        headers.write_text(
            "HTTP/1.1 302 Found\n\n"
            f"HTTP/1.1 {self.status} Partial Content\n"
            f"Content-Range: bytes {self.range_offset}-999/1000\n\n"
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def test_206_range_is_verified_and_idempotently_reused(self):
        with patch.object(module.subprocess, "run", self.fake_curl):
            self.assertEqual(module.fetch("https://example.invalid/file", 0, 1000), 1000)
            self.assertEqual(module.fetch("https://example.invalid/file", 0, 1000), 1000)
        self.assertEqual(self.calls, 1)

    def test_bad_status_fails_closed(self):
        self.status = "200"
        with patch.object(module.subprocess, "run", self.fake_curl):
            with patch.object(module.time, "sleep", lambda _: None):
                with self.assertRaisesRegex(RuntimeError, "http_not_206"):
                    module.fetch("https://example.invalid/file", 0, 1000)
        self.assertFalse((self.root / "segments" / "0000.part").exists())

    def test_checksum_tamper_forces_redownload(self):
        with patch.object(module.subprocess, "run", self.fake_curl):
            module.fetch("https://example.invalid/file", 0, 1000)
            (self.root / "segments" / "0000.part").write_bytes(b"x" * 1000)
            module.fetch("https://example.invalid/file", 0, 1000)
        self.assertEqual(self.calls, 2)
        self.assertEqual((self.root / "segments" / "0000.part").read_bytes(), self.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
