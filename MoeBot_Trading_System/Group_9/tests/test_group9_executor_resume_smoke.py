#!/usr/bin/env python3
"""Bounded resume tests for the existing shared Group 9-15 executor.

All workers, checkpoints and stage artifacts are synthetic and created in a
TemporaryDirectory. No real EXECUTION_COMMAND, upstream or annual data is used.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXECUTOR = Path(__file__).resolve().parents[2] / "groups9_15_shared" / "group_executor.py"


class Group9SyntheticResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.group = self.base / "Group_9"
        self.group.mkdir()
        self.work = self.base / "work"
        self.plan = self.base / "plan.json"
        self.preflight = self.base / "preflight.json"
        plan = {
            "group": 9, "shards": [
                {"shard_id": "synthetic_a", "bucket_index": 0, "bucket_count": 2},
                {"shard_key": "synthetic_b", "bucket_index": 1, "bucket_count": 2},
            ],
        }
        plan["report_hash"] = hashlib.sha256(json.dumps(
            plan, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        pf = {
            "status": "PASS", "group": 9,
            "purpose": "FULL_ANNUAL_SHARDS",
            "real_execution_authorized": True, "fixture_only": True,
            "plan_hash": plan["report_hash"],
        }
        pf["report_hash"] = hashlib.sha256(json.dumps(
            pf, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        self.preflight.write_text(json.dumps(pf), encoding="utf-8")
        (self.group / "EXECUTION_COMMAND.json").write_text(json.dumps({
            "status": "FROZEN", "entrypoint": "fixture_worker.py",
            "args_template": ["{shard_id}", "{work_root}"],
        }), encoding="utf-8")
        (self.group / "fixture_worker.py").write_text(
            "import pathlib,sys\n"
            "sid,root=sys.argv[1:]\n"
            "p=pathlib.Path(root)\n"
            "with (p/'attempts.txt').open('a') as f:f.write(sid+'\\n')\n"
            "if sid=='synthetic_b' and not (p/'permit_b.txt').exists():sys.exit(17)\n"
            "(p/(sid+'.done')).write_text('ok')\n",
            encoding="utf-8",
        )

    def invoke(self):
        return subprocess.run([
            sys.executable, str(EXECUTOR), "--group-dir", str(self.group),
            "--plan", str(self.plan), "--preflight", str(self.preflight),
            "--work-root", str(self.work), "--python", sys.executable,
        ], capture_output=True, text=True, timeout=15)

    def test_retry_failed_shard_without_reexecuting_completed_one(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 17, first.stdout + first.stderr)
        cp = json.loads((self.work / "progress.json").read_text())
        self.assertEqual(cp["status"], "FAILED")
        self.assertEqual(cp["completed"], ["synthetic_a"])
        self.assertTrue((self.work / "synthetic_a.done").is_file())
        (self.work / "permit_b.txt").write_text("ok")
        second = self.invoke()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        cp = json.loads((self.work / "progress.json").read_text())
        self.assertEqual(cp["status"], "SHARDS_COMPLETE")
        self.assertEqual(cp["completed"], ["synthetic_a", "synthetic_b"])
        attempts = (self.work / "attempts.txt").read_text().splitlines()
        self.assertEqual(attempts, ["synthetic_a", "synthetic_b", "synthetic_b"])

    def test_preflight_blocks_before_work_root_is_created(self):
        self.preflight.write_text(json.dumps({
            "status": "BLOCKED", "real_execution_authorized": False,
        }))
        run = self.invoke()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("preflight does not authorize real execution",
                      run.stdout + run.stderr)
        self.assertFalse(self.work.exists())

    def test_dependency_intake_cannot_launch_annual_execution(self):
        pf = json.loads(self.preflight.read_text())
        pf.pop("purpose")
        self.preflight.write_text(json.dumps(pf))
        run = self.invoke()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("preflight does not authorize real execution",
                      run.stdout + run.stderr)
        self.assertFalse(self.work.exists())

    def test_checkpoint_identity_drift_blocks_resume(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 17, first.stdout + first.stderr)
        cp = self.work / "progress.json"
        state = json.loads(cp.read_text())
        state["plan_hash"] = "modified"
        cp.write_text(json.dumps(state))
        (self.work / "permit_b.txt").write_text("ok")
        second = self.invoke()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("checkpoint identity mismatch",
                      second.stdout + second.stderr)
        self.assertEqual((self.work / "attempts.txt").read_text().splitlines(),
                         ["synthetic_a", "synthetic_b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
