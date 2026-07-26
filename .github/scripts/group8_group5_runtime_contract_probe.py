#!/usr/bin/env python3
"""Recover the exact frozen Group5 runtime source and inspect pool lifecycle semantics.

Diagnostic only. Exact identities come from Group8's frozen annual dependency
registry. Recovery prefers repository archive branches and verifies source bytes
by SHA-256 and size before inspecting lifecycle-relevant code. No 2024 database
is restored or accessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

EXPECTED_BUNDLE_SHA = "203657ca74ccc6badb27947eb23dc6c4ff9140e73ab943c0fd82bf46c8cfb80f"
EXPECTED_BUNDLE_SIZE = 63540
EXPECTED_G5_SHA = "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc"
EXPECTED_G5_SIZE = 59657
EXPECTED_G5_PATH = "runtime/groups2_5/code/moebot_group5_liquidity_engine_v0_1_6.py"
BASENAME = "moebot_group5_liquidity_engine_v0_1_6.py"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable(x: object) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def git(*args: str, text: bool = True) -> str | bytes:
    cp = subprocess.run(["git", *args], check=True, capture_output=True, text=text)
    return cp.stdout


def recover_exact_source(work: Path) -> tuple[Path, dict[str, Any]]:
    refs_raw = str(git("for-each-ref", "--format=%(refname)", "refs/remotes/origin/agent/"))
    refs = [x.strip() for x in refs_raw.splitlines() if "archive" in x.lower()]
    searched: list[str] = []
    for ref in refs:
        try:
            names = str(git("ls-tree", "-r", "--name-only", ref)).splitlines()
        except subprocess.CalledProcessError:
            continue
        matches = [n for n in names if n.endswith(BASENAME)]
        searched.extend(f"{ref}:{n}" for n in matches)
        for path in matches:
            try:
                data = bytes(git("show", f"{ref}:{path}", text=False))
            except subprocess.CalledProcessError:
                continue
            if len(data) == EXPECTED_G5_SIZE and sha_bytes(data) == EXPECTED_G5_SHA:
                out = work / BASENAME
                out.write_bytes(data)
                return out, {"method": "git_archive_branch", "ref": ref, "path": path, "sha256": EXPECTED_G5_SHA, "size_bytes": EXPECTED_G5_SIZE}
    raise SystemExit(f"exact Group5 runtime source not recovered; searched candidates={searched}")


def snippets(text: str, pattern: str, radius: int = 5) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(lines):
        if rx.search(line):
            a = max(0, i - radius); b = min(len(lines), i + radius + 1)
            out.append({"line": i + 1, "context": [f"{j+1}:{lines[j]}" for j in range(a, b)]})
    return out[:100]


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--group8-root", type=Path, required=True); p.add_argument("--report", type=Path, required=True); a = p.parse_args()
    root = a.group8_root.resolve()
    reg = json.loads((root / "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json").read_text())
    status = json.loads((root / "STATUS.json").read_text())
    rb = reg["runtime_bundle_v3"]; g5 = rb["runtime_engines"]["group5"]
    if rb["bundle_sha256"] != EXPECTED_BUNDLE_SHA or int(rb["bundle_size_bytes"]) != EXPECTED_BUNDLE_SIZE:
        raise SystemExit("runtime bundle identity mismatch")
    if g5["path"] != EXPECTED_G5_PATH or g5["sha256"] != EXPECTED_G5_SHA or int(g5["size_bytes"]) != EXPECTED_G5_SIZE:
        raise SystemExit("Group5 runtime identity mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("authorization boundary mismatch")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        engine, location = recover_exact_source(work)
        data = engine.read_bytes()
        if len(data) != EXPECTED_G5_SIZE or sha_bytes(data) != EXPECTED_G5_SHA:
            raise SystemExit("recovered Group5 runtime bytes mismatch")
        text = data.decode("utf-8")
        probes = {
            "pool_status": snippets(text, r"status.*swept|swept.*status"),
            "first_sweep_time": snippets(text, r"first_sweep_time"),
            "expires_at": snippets(text, r"expires_at"),
            "unswept": snippets(text, r"unswept"),
            "active_pool_filters": snippets(text, r"status\s*=\s*['\"]unswept|status\s*==\s*['\"]unswept|WHERE.*status.*unswept|status.*active"),
            "sweep_mutation": snippets(text, r"UPDATE\s+liquidity_pools|first_sweep|status\s*=\s*['\"]swept"),
        }
        report: dict[str, Any] = {
            "format_version": 2,
            "status": "PASS",
            "scope": "GROUP5_EXACT_RUNTIME_POOL_LIFECYCLE_CONTRACT_PROBE",
            "frozen_runtime_bundle_identity": {"sha256": EXPECTED_BUNDLE_SHA, "size_bytes": EXPECTED_BUNDLE_SIZE},
            "runtime_source_location": location,
            "group5_runtime_path": EXPECTED_G5_PATH,
            "group5_runtime_sha256": EXPECTED_G5_SHA,
            "group5_runtime_size_bytes": EXPECTED_G5_SIZE,
            "probes": probes,
            "observations": {"diagnostic_only": True, "runtime_bytes_verified": True, "recovered_from_repository_archive": True, "oos_2024_accessed": False, "frozen_state_changed": False},
        }
        report["report_hash"] = stable(report)
        a.report.parent.mkdir(parents=True, exist_ok=True); a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
