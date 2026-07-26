#!/usr/bin/env python3
"""Recover the exact frozen Group5 runtime bundle and inspect pool lifecycle semantics.

Diagnostic only. The exact runtime engine identity is taken from Group8's frozen
annual dependency registry. No 2024 database is restored or accessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

EXPECTED_BUNDLE_SHA = "203657ca74ccc6badb27947eb23dc6c4ff9140e73ab943c0fd82bf46c8cfb80f"
EXPECTED_BUNDLE_SIZE = 63540
EXPECTED_G5_SHA = "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc"
EXPECTED_G5_SIZE = 59657
EXPECTED_G5_PATH = "runtime/groups2_5/code/moebot_group5_liquidity_engine_v0_1_6.py"
REPO = "mohamadeidy/MoeBot_Project"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable(x: object) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def api(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "MoeBot-Group8-Audit"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "MoeBot-Group8-Audit"})
    with urllib.request.urlopen(req, timeout=120) as r, path.open("wb") as f:
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            f.write(b)


def extract_engine(bundle: Path, work: Path) -> Path:
    # Runtime bundle may be zip/tar or a direct file. Inspect content signatures.
    if zipfile.is_zipfile(bundle):
        with zipfile.ZipFile(bundle) as z:
            names = z.namelist()
            match = next((n for n in names if n.endswith("moebot_group5_liquidity_engine_v0_1_6.py")), None)
            if not match:
                raise RuntimeError("Group5 engine not found in zip runtime bundle")
            out = work / "group5.py"; out.write_bytes(z.read(match)); return out
    try:
        if tarfile.is_tarfile(bundle):
            with tarfile.open(bundle) as t:
                member = next((m for m in t.getmembers() if m.name.endswith("moebot_group5_liquidity_engine_v0_1_6.py")), None)
                if member is None:
                    raise RuntimeError("Group5 engine not found in tar runtime bundle")
                fh = t.extractfile(member)
                if fh is None:
                    raise RuntimeError("Group5 engine member unreadable")
                out = work / "group5.py"; out.write_bytes(fh.read()); return out
    except tarfile.ReadError:
        pass
    if bundle.stat().st_size == EXPECTED_G5_SIZE and sha(bundle) == EXPECTED_G5_SHA:
        return bundle
    raise RuntimeError("unsupported runtime bundle format")


def snippets(text: str, pattern: str, radius: int = 4) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(lines):
        if rx.search(line):
            a = max(0, i - radius); b = min(len(lines), i + radius + 1)
            out.append({"line": i + 1, "context": [f"{j+1}:{lines[j]}" for j in range(a, b)]})
    return out[:80]


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

    releases = []
    page = 1
    while page <= 10:
        chunk = api(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}")
        if not chunk: break
        releases.extend(chunk); page += 1
    candidates = []
    for rel in releases:
        for asset in rel.get("assets", []):
            if int(asset.get("size", -1)) == EXPECTED_BUNDLE_SIZE:
                candidates.append({"release": rel.get("tag_name"), "name": asset.get("name"), "url": asset.get("browser_download_url")})

    found = None
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for c in candidates:
            path = work / str(c["name"])
            download(str(c["url"]), path)
            if path.stat().st_size == EXPECTED_BUNDLE_SIZE and sha(path) == EXPECTED_BUNDLE_SHA:
                found = {**c, "bundle_sha256": sha(path)}
                engine = extract_engine(path, work)
                break
            path.unlink(missing_ok=True)
        if found is None:
            raise SystemExit(f"exact runtime bundle not found among {len(candidates)} size-matched release assets")
        if engine.stat().st_size != EXPECTED_G5_SIZE or sha(engine) != EXPECTED_G5_SHA:
            raise SystemExit("recovered Group5 runtime bytes mismatch")
        text = engine.read_text()
        probes = {
            "pool_status": snippets(text, r"status.*swept|swept.*status"),
            "first_sweep_time": snippets(text, r"first_sweep_time"),
            "expires_at": snippets(text, r"expires_at"),
            "unswept": snippets(text, r"unswept"),
            "active_pool_filters": snippets(text, r"status\s*=\s*['\"]unswept|status\s*==\s*['\"]unswept|WHERE.*status.*unswept|status.*active"),
        }
        # Preserve only relevant code contexts, not the whole runtime source.
        report: dict[str, Any] = {
            "format_version": 1,
            "status": "PASS",
            "scope": "GROUP5_EXACT_RUNTIME_POOL_LIFECYCLE_CONTRACT_PROBE",
            "runtime_bundle": found,
            "group5_runtime_path": EXPECTED_G5_PATH,
            "group5_runtime_sha256": EXPECTED_G5_SHA,
            "group5_runtime_size_bytes": EXPECTED_G5_SIZE,
            "probes": probes,
            "observations": {"diagnostic_only": True, "runtime_bytes_verified": True, "oos_2024_accessed": False, "frozen_state_changed": False},
        }
        report["report_hash"] = stable(report)
        a.report.parent.mkdir(parents=True, exist_ok=True); a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
