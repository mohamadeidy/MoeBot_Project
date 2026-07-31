#!/usr/bin/env python3
"""Restore a verified Annual Core checkpoint, execute one frozen stage, and publish the next checkpoint/final release."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

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
        raise RuntimeError(f"SQLite integrity failure:{value}")


def verify_manifest(manifest: dict[str, Any]) -> str:
    saved = str(manifest["report_hash"])
    payload = dict(manifest)
    payload.pop("report_hash")
    if stable_hash(payload) != saved:
        raise RuntimeError("checkpoint manifest self-hash mismatch")
    return saved


def restore_staging(root: Path, work: Path) -> Path:
    release = json.loads((root / "reports/48_FULL_2023_STAGING_RELEASE.json").read_text())
    parts_dir = work / "staging_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for expected in release["parts"]:
        target = parts_dir / expected["filename"]
        command("curl", "-fL", "--retry", "6", "--retry-delay", "2", expected["url"], "-o", str(target))
        if target.stat().st_size != expected["size_bytes"] or sha256_file(target) != expected["sha256"]:
            raise RuntimeError("staging part verification failure")
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
    return database


def restore_checkpoint(repo: str, tag: str, checkpoint: int, work: Path) -> tuple[Path, dict[str, Any], str]:
    prefix = f"checkpoint{checkpoint}"
    destination = work / prefix
    destination.mkdir(parents=True, exist_ok=True)
    command("gh", "release", "download", tag, "--repo", repo, "--pattern", f"{prefix}.*", "--dir", str(destination), "--clobber")
    manifest = json.loads((destination / f"{prefix}.json").read_text())
    manifest_hash = verify_manifest(manifest)
    if manifest["stage_end"] != checkpoint + 1:
        raise RuntimeError("checkpoint stage identity mismatch")
    parts = sorted(destination.glob(f"{prefix}.sqlite.zst.part-*"))
    if [part.name for part in parts] != [item["filename"] for item in manifest["parts"]]:
        raise RuntimeError("checkpoint part coverage mismatch")
    for actual, expected in zip(parts, manifest["parts"]):
        if actual.stat().st_size != expected["size_bytes"] or sha256_file(actual) != expected["sha256"]:
            raise RuntimeError("checkpoint part verification failure")
    archive = destination / f"{prefix}.sqlite.zst"
    with archive.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
    if archive.stat().st_size != manifest["compressed_size_bytes"] or sha256_file(archive) != manifest["compressed_sha256"]:
        raise RuntimeError("checkpoint compressed verification failure")
    database = destination / f"{prefix}.sqlite"
    command("zstd", "-q", "-d", "-f", str(archive), "-o", str(database))
    if database.stat().st_size != manifest["raw_size_bytes"] or sha256_file(database) != manifest["raw_sha256"]:
        raise RuntimeError("checkpoint raw verification failure")
    integrity(database)
    return database, manifest, manifest_hash


def publish_checkpoint(repo: str, tag: str, checkpoint: int, database: Path, parent_hash: str, result: dict[str, Any], work: Path) -> dict[str, Any]:
    prefix = f"checkpoint{checkpoint}"
    archive = work / f"{prefix}.sqlite.zst"
    command("zstd", "-q", "-3", "-T0", "-f", str(database), "-o", str(archive))
    command("split", "-b", "1750000000", "-d", "-a", "3", str(archive), str(work / f"{prefix}.sqlite.zst.part-"))
    parts = [{"filename": part.name, "size_bytes": part.stat().st_size, "sha256": sha256_file(part)} for part in sorted(work.glob(f"{prefix}.sqlite.zst.part-*"))]
    manifest = {
        "status": "PASS", "year": 2023, "stage_end": checkpoint + 1,
        "source_checkpoint_report_hash": parent_hash,
        "raw_size_bytes": database.stat().st_size, "raw_sha256": sha256_file(database),
        "compressed_size_bytes": archive.stat().st_size, "compressed_sha256": sha256_file(archive),
        "parts": parts, "segment_report": result, "free_only": True,
        "paid_runner_used": False, "paid_service_used": False, "oos_2024_accessed": False,
    }
    manifest["report_hash"] = stable_hash(manifest)
    manifest_path = work / f"{prefix}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    command("gh", "release", "upload", tag, *[str(work / item["filename"]) for item in parts], str(manifest_path), "--repo", repo, "--clobber")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(5, 6, 7), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    status = json.loads((args.artifacts_root / "STATUS.json").read_text())
    if status["annual_execution_2024_authorized"] is not False:
        raise RuntimeError("2024 lock failure")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    staging = restore_staging(args.artifacts_root, args.work_dir)
    input_checkpoint = args.stage - 2
    database, _, parent_hash = restore_checkpoint(args.repo, args.tag, input_checkpoint, args.work_dir)
    core = args.work_dir / "core.sqlite"
    shutil.copy2(database, core)
    result = run_segment(
        staging_db=staging,
        output_db=core,
        artifacts_root=args.artifacts_root,
        year=2023,
        symbol="XAUUSD_",
        start=args.stage,
        end=args.stage,
    )
    integrity(core)
    output = {"status": "PASS", "stage": args.stage, "segment_report": result, "oos_2024_accessed": False, "free_only": True}
    if args.stage < 7:
        output["checkpoint_manifest"] = publish_checkpoint(args.repo, args.tag, input_checkpoint + 1, core, parent_hash, result, args.work_dir)
    else:
        fingerprint = args.work_dir / "CORE_FINGERPRINT.json"
        command("python", str(args.artifacts_root / "code/group8_sqlite_fingerprint.py"), "--database", str(core), "--output", str(fingerprint))
        fp = json.loads(fingerprint.read_text())
        archive = args.work_dir / "MoeBot_Group8_ANNUAL_CORE_2023_v4_segmented.sqlite.zst"
        command("zstd", "-q", "-6", "-T0", "-f", str(core), "-o", str(archive))
        command("split", "-b", "1750000000", "-d", "-a", "3", str(archive), str(args.work_dir / "MoeBot_Group8_ANNUAL_CORE_2023_v4_segmented.sqlite.zst.part-"))
        parts = [{"filename": part.name, "size_bytes": part.stat().st_size, "sha256": sha256_file(part), "url": f"https://github.com/{args.repo}/releases/download/{args.tag}/{part.name}"} for part in sorted(args.work_dir.glob("MoeBot_Group8_ANNUAL_CORE_2023_v4_segmented.sqlite.zst.part-*"))]
        release = {
            "format_version": 4, "status": "PASS", "artifact_kind": "GROUP8_ANNUAL_CORE", "year": 2023,
            "physical_role": "ANNUAL_CORE_NON_PA7", "execution_mode": "EXACT_SEGMENTED_RESUMABLE_PARTITIONED_STAGE4",
            "release_tag": args.tag, "archive_filename": archive.name, "parts": parts, "part_count": len(parts),
            "raw_size_bytes": fp["database_size_bytes"], "raw_sha256": fp["database_sha256"],
            "logical_sha256": fp["logical_sha256"], "table_fingerprints": {key: value["logical_sha256"] for key, value in fp["tables"].items()},
            "table_row_counts": {key: value["row_count"] for key, value in fp["tables"].items()},
            "source_checkpoint_report_hash": parent_hash, "final_segment_report": result,
            "free_only": True, "paid_runner_used": False, "paid_service_used": False, "oos_2024_accessed": False,
        }
        release["report_hash"] = stable_hash(release)
        repository_report = args.artifacts_root / "reports/50_ANNUAL_2023_CORE_RELEASE.json"
        repository_report.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")
        public_report = args.work_dir / "MoeBot_Group8_ANNUAL_CORE_2023_v4_segmented.json"
        public_report.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")
        command("gh", "release", "upload", args.tag, *[str(args.work_dir / item["filename"]) for item in parts], str(public_report), str(fingerprint), "--repo", args.repo, "--clobber")
        output["official_release"] = release
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
