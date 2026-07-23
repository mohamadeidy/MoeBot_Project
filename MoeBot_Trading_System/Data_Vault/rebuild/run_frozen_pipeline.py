#!/usr/bin/env python3
"""Run the exact frozen MoeBot Group 2 through Group 6 engines on one rebuilt source year."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def locate(root: Path, basename: str) -> Path:
    matches = sorted(root.rglob(basename))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {basename} under {root}, found {matches}")
    return matches[0]


def run(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = {"command": command, "returncode": proc.returncode, "elapsed_seconds": round(time.time() - started, 3), "output": proc.stdout}
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def sqlite_check(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    conn.close()
    result = {"quick_check": quick, "integrity_check": integrity, "foreign_key_errors": len(fk), "tables": tables}
    if quick != "ok" or integrity != "ok" or fk:
        raise RuntimeError(f"SQLite verification failed for {path}: {result}")
    return result


def build(year: int, source: Path, runtime_root: Path, work_dir: Path, group6_output: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    group6_output.parent.mkdir(parents=True, exist_ok=True)
    engines = {
        "g2": locate(runtime_root, "moebot_group2_engine_v0_2_1.py"),
        "g3": locate(runtime_root, "moebot_group3_structure_engine_v0_1_1.py"),
        "g4": locate(runtime_root, "moebot_group4_zones_engine_v0_1_6.py"),
        "g5": locate(runtime_root, "moebot_group5_liquidity_engine_v0_1_6.py"),
        "g6": locate(runtime_root, "moebot_group6_engine.py"),
    }
    source_sha = sha256_file(source)
    source_meta_path = work_dir / f"source_meta_{year}.json"
    source_meta = {
        "source_kind": "dukascopy_public_rebuild",
        "source_locator": source.name,
        "source_fingerprint_sha256": source_sha,
        "archive_sha256": None,
        "stream_identity": {
            "provider": "Dukascopy Jetta public candles API",
            "instrument": "XAU-USD",
            "symbol": "XAUUSD_",
            "price_type": "BID",
            "year": year,
            "base_timeframe": "M1",
            "time_basis": "UTC",
            "aggregation": "deterministic UTC buckets",
            "rebuild_version": "dukascopy_rebuild_v1",
        },
        "boundaries": {"year": year, "inclusive_start_utc": f"{year}-01-01T00:00:00Z", "exclusive_end_utc": f"{year+1}-01-01T00:00:00Z"},
    }
    source_meta_path.write_text(json.dumps(source_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = {
        "group2": work_dir / f"MoeBot_Group2_XAUUSD_{year}_v0.2.1_rebuilt_dukascopy_v1.sqlite",
        "group3": work_dir / f"MoeBot_Group3_XAUUSD_{year}_v0.1.1_rebuilt_dukascopy_v1.sqlite",
        "group4": work_dir / f"MoeBot_Group4_XAUUSD_{year}_v0.1.6_rebuilt_dukascopy_v1.sqlite",
        "group5": work_dir / f"MoeBot_Group5_XAUUSD_{year}_v0.1.6_rebuilt_dukascopy_v1.sqlite",
        "group6": group6_output,
    }
    for path in paths.values():
        if path.exists():
            path.unlink()

    py = sys.executable
    logs: dict[str, Any] = {}
    logs["runtime_dependency_sortedcontainers"] = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "sortedcontainers"])
    logs["group2_build"] = run([py, str(engines["g2"]), "build", "--source-db", str(source), "--output-db", str(paths["group2"]), "--source-meta", str(source_meta_path)])
    logs["group2_verify"] = run([py, str(engines["g2"]), "verify", "--db", str(paths["group2"])])
    logs["group3_build"] = run([py, str(engines["g3"]), "--source", str(source), "--out", str(paths["group3"]), "--year", str(year)])
    logs["group4_build"] = run([py, str(engines["g4"]), "--source-db", str(source), "--group3-db", str(paths["group3"]), "--out-db", str(paths["group4"])])
    logs["group5_tests"] = run([py, str(engines["g5"]), "tests"])
    logs["group5_build"] = run([py, str(engines["g5"]), "build", "--source-db", str(source), "--group3-db", str(paths["group3"]), "--group4-db", str(paths["group4"]), "--output-db", str(paths["group5"])])
    logs["group6_selftest"] = run([py, str(engines["g6"]), "selftest"])
    logs["group6_build"] = run([py, str(engines["g6"]), "build", "--source", str(source), "--out", str(paths["group6"]), "--year", str(year),
                                "--g2", str(paths["group2"]), "--g3", str(paths["group3"]), "--g4", str(paths["group4"]), "--g5", str(paths["group5"])])
    logs["group6_finalize_mtf"] = run([py, str(engines["g6"]), "finalize-mtf", "--db", str(paths["group6"])])
    logs["group6_verify"] = run([py, str(engines["g6"]), "verify", "--db", str(paths["group6"])])

    checks = {name: sqlite_check(path) for name, path in paths.items()}
    artifacts = {name: {"path": str(path), "filename": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)} for name, path in paths.items()}
    return {"year": year, "source_sha256": source_sha, "engines": {k: {"path": str(v), "sha256": sha256_file(v)} for k,v in engines.items()},
            "artifacts": artifacts, "sqlite_checks": checks, "logs": logs}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True, choices=(2023, 2024))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--group6-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.year, args.source, args.runtime_root, args.work_dir, args.group6_output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"year": args.year, "artifacts": result["artifacts"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
