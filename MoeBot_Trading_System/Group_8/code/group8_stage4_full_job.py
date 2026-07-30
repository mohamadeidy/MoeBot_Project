#!/usr/bin/env python3
"""Full wall-clock stage-4 benchmark/official job with SHA-bound public verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from group8_context_rejection_fastpath import IndexedContextRejectionEngine, STAGE4_PARTITION_COUNT
from group8_segmented_annual_core import run_segment
from moebot_group8_engine_v0_8_0 import stable_hash


def command(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        value = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    if value != "ok":
        raise RuntimeError(f"SQLite integrity failure:{path.name}:{value}")


def verify_self_hash(manifest: dict[str, Any]) -> str:
    key = "report_hash" if "report_hash" in manifest else "manifest_hash"
    saved = str(manifest[key])
    payload = dict(manifest)
    payload.pop(key)
    if stable_hash(payload) != saved:
        raise RuntimeError("manifest self-hash mismatch")
    return saved


def staging_restore(root: Path, work: Path) -> tuple[Path, float]:
    started = time.monotonic()
    release = json.loads((root / "reports/48_FULL_2023_STAGING_RELEASE.json").read_text())
    parts_dir = work / "staging_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for expected in release["parts"]:
        target = parts_dir / expected["filename"]
        command("curl", "-fL", "--retry", "6", "--retry-delay", "2", expected["url"], "-o", str(target))
        if target.stat().st_size != expected["size_bytes"] or sha256_file(target) != expected["sha256"]:
            raise RuntimeError(f"staging part verification failure:{target.name}")
        parts.append(target)
    archive = work / "staging.sqlite.zst"
    with archive.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
    if archive.stat().st_size != release["compressed_size_bytes"] or sha256_file(archive) != release["compressed_sha256"]:
        raise RuntimeError("staging archive verification failure")
    database = work / "staging.sqlite"
    command("zstd", "-q", "-d", "-f", str(archive), "-o", str(database))
    integrity(database)
    return database, time.monotonic() - started


def prefix(partition: int) -> str:
    return "checkpoint2" if partition < 0 else f"stage4p{partition:02d}"


def parent_restore(repo: str, tag: str, parent_partition: int, work: Path) -> tuple[Path, dict[str, Any], str, float]:
    started = time.monotonic()
    name = prefix(parent_partition)
    destination = work / f"parent-{name}"
    destination.mkdir(parents=True, exist_ok=True)
    command("gh", "release", "download", tag, "--repo", repo, "--pattern", f"{name}.*", "--dir", str(destination), "--clobber")
    manifest = json.loads((destination / f"{name}.json").read_text())
    manifest_hash = verify_self_hash(manifest)
    expected_parts = manifest["parts"]
    parts = sorted(destination.glob(f"{name}.sqlite.zst.part-*"))
    if [item.name for item in parts] != [item["filename"] for item in expected_parts]:
        raise RuntimeError("parent filename coverage mismatch")
    for actual, expected in zip(parts, expected_parts):
        if actual.stat().st_size != expected["size_bytes"] or sha256_file(actual) != expected["sha256"]:
            raise RuntimeError(f"parent part verification failure:{actual.name}")
    archive = destination / f"{name}.sqlite.zst"
    with archive.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
    if archive.stat().st_size != manifest["compressed_size_bytes"] or sha256_file(archive) != manifest["compressed_sha256"]:
        raise RuntimeError("parent compressed verification failure")
    database = destination / f"{name}.sqlite"
    command("zstd", "-q", "-d", "-f", str(archive), "-o", str(database))
    if database.stat().st_size != manifest["raw_size_bytes"] or sha256_file(database) != manifest["raw_sha256"]:
        raise RuntimeError("parent raw verification failure")
    integrity(database)
    if parent_partition >= 0:
        plan = IndexedContextRejectionEngine.stage4_partition_plan()
        if manifest["partition_index"] != parent_partition or manifest["plan_hash"] != plan["plan_hash"]:
            raise RuntimeError("parent plan identity mismatch")
        if manifest.get("checkpoint_3_published") is not False:
            raise RuntimeError("partition illegally published checkpoint 3")
    return database, manifest, manifest_hash, time.monotonic() - started


def publish_and_verify(repo: str, tag: str, asset_prefix: str, database: Path, payload: dict[str, Any], work: Path) -> dict[str, float]:
    archive = work / f"{asset_prefix}.sqlite.zst"
    started = time.monotonic()
    command("zstd", "-q", "-3", "-T0", "-f", str(database), "-o", str(archive))
    command("split", "-b", "1750000000", "-d", "-a", "3", str(archive), str(work / f"{asset_prefix}.sqlite.zst.part-"))
    compression_seconds = time.monotonic() - started

    started = time.monotonic()
    parts = [
        {"filename": item.name, "size_bytes": item.stat().st_size, "sha256": sha256_file(item)}
        for item in sorted(work.glob(f"{asset_prefix}.sqlite.zst.part-*"))
    ]
    payload.update({
        "raw_size_bytes": database.stat().st_size,
        "raw_sha256": sha256_file(database),
        "compressed_size_bytes": archive.stat().st_size,
        "compressed_sha256": sha256_file(archive),
        "parts": parts,
        "compression_seconds": compression_seconds,
    })
    hash_seconds = time.monotonic() - started
    payload["hash_seconds"] = hash_seconds
    payload["manifest_hash"] = stable_hash(payload)
    manifest_path = work / f"{asset_prefix}.json"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    started = time.monotonic()
    command("gh", "release", "upload", tag, *[str(work / item["filename"]) for item in parts], str(manifest_path), "--repo", repo, "--clobber")
    upload_seconds = time.monotonic() - started

    verify_dir = work / f"verify-{asset_prefix}"
    verify_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    command("gh", "release", "download", tag, "--repo", repo, "--pattern", f"{asset_prefix}.*", "--dir", str(verify_dir), "--clobber")
    downloaded_manifest = json.loads((verify_dir / f"{asset_prefix}.json").read_text())
    verify_self_hash(downloaded_manifest)
    downloaded_parts = sorted(verify_dir.glob(f"{asset_prefix}.sqlite.zst.part-*"))
    if [item.name for item in downloaded_parts] != [item["filename"] for item in downloaded_manifest["parts"]]:
        raise RuntimeError("public redownload filename mismatch")
    for actual, expected in zip(downloaded_parts, downloaded_manifest["parts"]):
        if actual.stat().st_size != expected["size_bytes"] or sha256_file(actual) != expected["sha256"]:
            raise RuntimeError("public redownload part mismatch")
    redownload_verify_seconds = time.monotonic() - started
    return {
        "compression_seconds": compression_seconds,
        "hash_seconds": hash_seconds,
        "upload_seconds": upload_seconds,
        "redownload_verify_seconds": redownload_verify_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("benchmark", "official"), required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--partition", type=int, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--job-start-epoch", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.partition < STAGE4_PARTITION_COUNT:
        raise ValueError("invalid partition")

    status = json.loads((args.artifacts_root / "STATUS.json").read_text())
    if status["annual_execution_2024_authorized"] is not False:
        raise RuntimeError("2024 lock is not confirmed")
    if status["free_only_policy"]["paid_runner_allowed"] or status["free_only_policy"]["paid_service_allowed"]:
        raise RuntimeError("FREE-only policy failure")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    staging, staging_restore_seconds = staging_restore(args.artifacts_root, args.work_dir)
    parent_partition = -1 if args.mode == "benchmark" or args.partition == 0 else args.partition - 1
    parent_db, parent_manifest, parent_hash, parent_restore_seconds = parent_restore(args.repo, args.tag, parent_partition, args.work_dir)
    core = args.work_dir / "core.sqlite"
    shutil.copy2(parent_db, core)

    plan = IndexedContextRejectionEngine.stage4_partition_plan()
    range_identity = f"{plan['plan_id']}:range-{args.partition:02d}-{args.partition:02d}"
    started = time.monotonic()
    result = run_segment(
        staging_db=staging,
        output_db=core,
        artifacts_root=args.artifacts_root,
        year=2023,
        symbol="XAUUSD_",
        start=4,
        end=4,
        stage4_partition=args.partition,
    )
    execution_seconds = time.monotonic() - started
    integrity(core)

    head_sha = command("git", "rev-parse", "HEAD", capture=True)
    asset_prefix = f"stage4bench{args.partition:02d}-{head_sha[:12]}" if args.mode == "benchmark" else prefix(args.partition)
    payload: dict[str, Any] = {
        "status": "PASS",
        "role": "STAGE4_FULL_JOB_BENCHMARK" if args.mode == "benchmark" else "STAGE4_PARTITION_CHECKPOINT",
        "mode": args.mode,
        "year": 2023,
        "github_head_sha": head_sha,
        "partition_index": args.partition,
        "range_identity": range_identity,
        "first_partition": args.partition,
        "last_partition": args.partition,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "parent_manifest_hash": parent_hash,
        "receipt": result["receipt"],
        "restore_seconds": staging_restore_seconds + parent_restore_seconds,
        "staging_restore_seconds": staging_restore_seconds,
        "parent_restore_seconds": parent_restore_seconds,
        "execution_seconds": execution_seconds,
        "checkpoint_3_published": False,
        "free_only": True,
        "oos_2024_accessed": False,
    }
    phase_timings = publish_and_verify(args.repo, args.tag, asset_prefix, core, payload, args.work_dir)
    full_job_wall_seconds = time.time() - args.job_start_epoch
    payload.update(phase_timings)
    payload["full_job_wall_seconds"] = full_job_wall_seconds
    payload["safety_limit_seconds"] = 14400
    payload["runtime_safety_pass"] = full_job_wall_seconds <= 14400
    payload["manifest_hash"] = stable_hash({key: value for key, value in payload.items() if key != "manifest_hash"})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if not payload["runtime_safety_pass"]:
        raise RuntimeError(f"full job safety failure:{full_job_wall_seconds}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
