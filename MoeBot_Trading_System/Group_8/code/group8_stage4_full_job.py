#!/usr/bin/env python3
"""Full wall-clock stage-4 BENCHMARK_ONLY/official job with verified release I/O."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from group8_context_rejection_fastpath import IndexedContextRejectionEngine, STAGE4_PARTITION_COUNT
from group8_segmented_annual_core import run_segment
from moebot_group8_engine_v0_8_0 import stable_hash

MAX_RELEASE_ATTEMPTS = 5
T = TypeVar("T")


def command(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


cmd = command


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


sha = sha256_file


def integrity(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        value = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    if value != "ok":
        raise RuntimeError(f"SQLite integrity failure:{path.name}:{value}")


def self_hash(manifest: dict[str, Any]) -> str:
    key = "report_hash" if "report_hash" in manifest else "manifest_hash"
    saved = str(manifest[key])
    payload = dict(manifest)
    payload.pop(key)
    if stable_hash(payload) != saved:
        raise RuntimeError("manifest self-hash mismatch")
    return saved


def _clean_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _retry(operation: str, callback: Callable[[], T]) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_RELEASE_ATTEMPTS + 1):
        try:
            return callback()
        except BaseException as exc:
            last_error = exc
            if attempt == MAX_RELEASE_ATTEMPTS:
                break
            delay = 2 ** attempt
            print({"operation": operation, "attempt": attempt, "status": "RETRY", "backoff_seconds": delay, "error": str(exc)})
            time.sleep(delay)
    raise RuntimeError(f"{operation} failed after {MAX_RELEASE_ATTEMPTS} attempts") from last_error


def restore_staging(root: Path, work: Path) -> tuple[Path, float]:
    started = time.monotonic()
    manifest = json.loads((root / "reports/48_FULL_2023_STAGING_RELEASE.json").read_text())
    parts_dir = work / "staging_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for expected in manifest["parts"]:
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
    if archive.stat().st_size != manifest["compressed_size_bytes"] or sha256_file(archive) != manifest["compressed_sha256"]:
        raise RuntimeError("staging archive verification failure")
    database = work / "staging.sqlite"
    command("zstd", "-q", "-d", "-f", str(archive), "-o", str(database))
    integrity(database)
    return database, time.monotonic() - started


staging_restore = restore_staging


def prefix(index: int) -> str:
    return "checkpoint2" if index < 0 else f"stage4p{index:02d}"


def _verify_downloaded_database(destination: Path, name: str) -> tuple[Path, dict[str, Any], str]:
    manifest = json.loads((destination / f"{name}.json").read_text())
    manifest_hash = self_hash(manifest)
    parts = sorted(destination.glob(f"{name}.sqlite.zst.part-*"))
    if [part.name for part in parts] != [item["filename"] for item in manifest["parts"]]:
        raise RuntimeError("release part filename coverage mismatch")
    for actual, expected in zip(parts, manifest["parts"]):
        if actual.stat().st_size != expected["size_bytes"] or sha256_file(actual) != expected["sha256"]:
            raise RuntimeError(f"release part verification failure:{actual.name}")
    archive = destination / f"{name}.sqlite.zst"
    with archive.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
    if archive.stat().st_size != manifest["compressed_size_bytes"] or sha256_file(archive) != manifest["compressed_sha256"]:
        raise RuntimeError("release compressed verification failure")
    database = destination / f"{name}.sqlite"
    command("zstd", "-q", "-d", "-f", str(archive), "-o", str(database))
    if database.stat().st_size != manifest["raw_size_bytes"] or sha256_file(database) != manifest["raw_sha256"]:
        raise RuntimeError("release raw verification failure")
    integrity(database)
    return database, manifest, manifest_hash


def restore_parent(repo: str, tag: str, index: int, work: Path) -> tuple[Path, dict[str, Any], str, float]:
    started = time.monotonic()
    name = prefix(index)
    destination = work / f"parent-{name}"

    def attempt() -> tuple[Path, dict[str, Any], str]:
        _clean_directory(destination)
        command("gh", "release", "download", tag, "--repo", repo, "--pattern", f"{name}.*", "--dir", str(destination), "--clobber")
        database, manifest, manifest_hash = _verify_downloaded_database(destination, name)
        if index >= 0:
            plan = IndexedContextRejectionEngine.stage4_partition_plan()
            if manifest["partition_index"] != index or manifest["plan_hash"] != plan["plan_hash"]:
                raise RuntimeError("parent official partition identity failure")
            if manifest.get("checkpoint_3_published") is not False:
                raise RuntimeError("parent partition illegally published checkpoint 3")
        return database, manifest, manifest_hash

    database, manifest, manifest_hash = _retry(f"gh release download {tag}/{name}", attempt)
    return database, manifest, manifest_hash, time.monotonic() - started


parent_restore = restore_parent


def ensure_bench_release(repo: str, tag: str, head: str) -> None:
    if not tag.startswith("moebot-group8-stage4-benchmark-") or head[:12] not in tag:
        raise RuntimeError("benchmark output tag is not exact-head isolated")
    view = subprocess.run(["gh", "release", "view", tag, "--repo", repo], text=True, capture_output=True)
    if view.returncode:
        create = subprocess.run([
            "gh", "release", "create", tag, "--repo", repo,
            "--title", f"Group8 stage4 benchmark {head[:12]}",
            "--notes", "BENCHMARK_ONLY diagnostics; not official Annual 2023 evidence.",
        ], text=True, capture_output=True)
        if create.returncode and subprocess.run(["gh", "release", "view", tag, "--repo", repo], text=True, capture_output=True).returncode:
            raise RuntimeError(f"cannot create benchmark release:{create.stderr}")


def publish_verify(repo: str, tag: str, name: str, database: Path, payload: dict[str, Any], work: Path) -> dict[str, float]:
    archive = work / f"{name}.sqlite.zst"
    started = time.monotonic()
    command("zstd", "-q", "-3", "-T0", "-f", str(database), "-o", str(archive))
    for old in work.glob(f"{name}.sqlite.zst.part-*"):
        old.unlink()
    command("split", "-b", "1750000000", "-d", "-a", "3", str(archive), str(work / f"{name}.sqlite.zst.part-"))
    compression_seconds = time.monotonic() - started

    started = time.monotonic()
    parts = [{"filename": part.name, "size_bytes": part.stat().st_size, "sha256": sha256_file(part)} for part in sorted(work.glob(f"{name}.sqlite.zst.part-*"))]
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
    manifest_path = work / f"{name}.json"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    upload_started = time.monotonic()
    verify_elapsed = 0.0

    def upload_attempt() -> None:
        nonlocal verify_elapsed
        command("gh", "release", "upload", tag, *[str(work / item["filename"]) for item in parts], str(manifest_path), "--repo", repo, "--clobber")
        verify_dir = work / f"verify-{name}"
        verify_started = time.monotonic()
        _clean_directory(verify_dir)
        command("gh", "release", "download", tag, "--repo", repo, "--pattern", f"{name}.*", "--dir", str(verify_dir), "--clobber")
        verified_database, downloaded_manifest, _ = _verify_downloaded_database(verify_dir, name)
        if downloaded_manifest != payload:
            raise RuntimeError("public manifest content mismatch")
        if sha256_file(verified_database) != payload["raw_sha256"]:
            raise RuntimeError("public database SHA mismatch")
        verify_elapsed += time.monotonic() - verify_started

    _retry(f"gh release upload+verify {tag}/{name}", upload_attempt)
    return {
        "compression_seconds": compression_seconds,
        "hash_seconds": hash_seconds,
        "upload_seconds": time.monotonic() - upload_started - verify_elapsed,
        "redownload_verify_seconds": verify_elapsed,
        "release_io_attempt_limit": MAX_RELEASE_ATTEMPTS,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("benchmark", "official"), required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--source-tag")
    parser.add_argument("--output-tag")
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
    head = command("git", "rev-parse", "HEAD", capture=True)
    source = args.source_tag or args.tag
    if not source:
        raise ValueError("source tag is required")
    output = args.output_tag or (f"moebot-group8-stage4-benchmark-{head[:12]}" if args.mode == "benchmark" else source)
    if args.mode == "benchmark":
        if output == source:
            raise RuntimeError("BENCHMARK_ONLY cannot write official source tag")
        ensure_bench_release(args.repo, output, head)
    elif output != source:
        raise RuntimeError("official chain must remain on canonical release tag")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    staging, staging_seconds = restore_staging(args.artifacts_root, args.work_dir)
    parent_index = -1 if args.mode == "benchmark" or args.partition == 0 else args.partition - 1
    parent, _, parent_hash, parent_seconds = restore_parent(args.repo, source, parent_index, args.work_dir)
    core = args.work_dir / "core.sqlite"
    shutil.copy2(parent, core)
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
        benchmark_only=args.mode == "benchmark",
    )
    execution_seconds = time.monotonic() - started
    integrity(core)
    if args.mode == "benchmark" and not (
        result.get("benchmark_only") is True
        and result.get("official_chain_progress") is False
        and result.get("official_receipt_published") is False
    ):
        raise RuntimeError("BENCHMARK_ONLY role contract failure")

    name = f"stage4bench{args.partition:02d}-{head[:12]}" if args.mode == "benchmark" else prefix(args.partition)
    payload: dict[str, Any] = {
        "status": "PASS",
        "role": "STAGE4_FULL_JOB_BENCHMARK_ONLY" if args.mode == "benchmark" else "STAGE4_PARTITION_CHECKPOINT",
        "mode": args.mode,
        "year": 2023,
        "github_head_sha": head,
        "partition_index": args.partition,
        "range_identity": range_identity,
        "first_partition": args.partition,
        "last_partition": args.partition,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "parent_manifest_hash": parent_hash,
        "source_tag": source,
        "output_tag": output,
        "receipt_preview": result["receipt"],
        "official_receipt_published": False if args.mode == "benchmark" else True,
        "restore_seconds": staging_seconds + parent_seconds,
        "staging_restore_seconds": staging_seconds,
        "parent_restore_seconds": parent_seconds,
        "execution_seconds": execution_seconds,
        "checkpoint_3_published": False,
        "free_only": True,
        "oos_2024_accessed": False,
    }
    timings = publish_verify(args.repo, output, name, core, payload, args.work_dir)
    full_wall = time.time() - args.job_start_epoch
    payload.update(timings)
    payload["full_job_wall_seconds"] = full_wall
    payload["safety_limit_seconds"] = 14400
    payload["runtime_safety_pass"] = full_wall <= 14400
    payload["manifest_hash"] = stable_hash({key: value for key, value in payload.items() if key != "manifest_hash"})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if not payload["runtime_safety_pass"]:
        raise RuntimeError(f"full job safety failure:{full_wall}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
