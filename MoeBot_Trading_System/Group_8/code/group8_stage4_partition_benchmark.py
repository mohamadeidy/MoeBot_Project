#!/usr/bin/env python3
"""Measure full-data stage-4 partition engine phases; workflow owns full-job wall time."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_context_rejection_fastpath import STAGE4_PARTITION_COUNT
from group8_stage4_partition_regression import _filtered_process


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_engine(staging: Path, database: Path, root: Path) -> tuple[AnnualCoreEngine, float]:
    started = time.monotonic()
    engine = AnnualCoreEngine(
        staging_db=staging,
        output_db=database,
        artifacts_root=root,
        year=2023,
        symbol="XAUUSD_",
    )
    return engine, time.monotonic() - started


def measure_context_rebuild(staging: Path, database: Path, root: Path) -> dict[str, float]:
    engine, init_seconds = build_engine(staging, database, root)
    try:
        started = time.monotonic()
        engine.load_bars()
        load_bars_seconds = time.monotonic() - started
        started = time.monotonic()
        _filtered_process(engine, None, set())
        context_index_rebuild_seconds = time.monotonic() - started
        return {
            "engine_init_seconds": init_seconds,
            "load_bars_seconds": load_bars_seconds,
            "context_index_rebuild_seconds": context_index_rebuild_seconds,
        }
    finally:
        engine.close()


def execute_partition(staging: Path, database: Path, root: Path, partition: int) -> dict[str, float]:
    engine, init_seconds = build_engine(staging, database, root)
    try:
        started = time.monotonic()
        engine.load_bars()
        load_bars_seconds = time.monotonic() - started
        started = time.monotonic()
        engine.process_context_rejections_fast(partition_index=partition)
        execution_seconds = time.monotonic() - started
        started = time.monotonic()
        engine.out.commit()
        commit_seconds = time.monotonic() - started
        return {
            "engine_init_seconds": init_seconds,
            "load_bars_seconds": load_bars_seconds,
            "execution_seconds": execution_seconds,
            "commit_seconds": commit_seconds,
        }
    finally:
        engine.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-db", type=Path, required=True)
    parser.add_argument("--checkpoint2-db", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--partition", type=int, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.partition < STAGE4_PARTITION_COUNT:
        raise ValueError("invalid partition")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    baseline = args.work_dir / "baseline.sqlite"
    actual = args.work_dir / "actual.sqlite"
    shutil.copy2(args.checkpoint2_db, baseline)
    shutil.copy2(args.checkpoint2_db, actual)

    rebuild = measure_context_rebuild(args.staging_db, baseline, args.artifacts_root)
    execution = execute_partition(args.staging_db, actual, args.artifacts_root, args.partition)

    started = time.monotonic()
    connection = sqlite3.connect(actual)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    integrity_seconds = time.monotonic() - started

    started = time.monotonic()
    database_sha256 = sha256_file(actual)
    hash_seconds = time.monotonic() - started

    report = {
        "status": "PASS",
        "role": "FULL_DATA_PARTITION_ENGINE_BENCHMARK",
        "partition": args.partition,
        "partition_count": STAGE4_PARTITION_COUNT,
        "context_rebuild": rebuild,
        "partition_execution": execution,
        "integrity_seconds": integrity_seconds,
        "hash_seconds": hash_seconds,
        "database_size_bytes": actual.stat().st_size,
        "database_sha256": database_sha256,
        "sqlite_integrity": integrity,
        "oos_2024_accessed": False,
        "free_only": True,
    }
    if integrity != "ok":
        raise RuntimeError(f"benchmark SQLite integrity failure:{report}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
