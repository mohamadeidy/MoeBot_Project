#!/usr/bin/env python3
"""C: active shard -> D: verified vault. No Group8 writes or annual execution.

Copies a complete, self-hashed Group9 shard archive to a new vault location,
verifies content SHA-256, writes a durable transfer receipt, then optionally
removes C: copies only after all proofs. Fail-closed on missing/corrupt evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

STATUS = "PASS_ONE_EXACT_COMPLETE_SHARD"


def stable(doc: dict) -> str:
    return hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def within(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except (OSError, ValueError):
        return False


def atomic_json(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".incomplete")
    if tmp.exists():
        raise RuntimeError("previous_incomplete_receipt_requires_review")
    with tmp.open("x", encoding="utf-8") as stream:
        json.dump(doc, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def vault_transfer(report: Path, active: Path, vault: Path, *,
                   cleanup: bool = False) -> dict:
    active = active.resolve()
    vault = vault.resolve()
    if active.drive.upper() != "C:" or vault.drive.upper() != "D:":
        raise RuntimeError("required_C_active_and_D_vault")
    if active == vault or not active.is_dir():
        raise RuntimeError("invalid_active_root")
    r = json.loads(report.read_text(encoding="utf-8"))
    digest = r.get("report_hash")
    probe = dict(r)
    probe.pop("report_hash", None)
    if not digest or digest != stable(probe):
        raise RuntimeError("report_identity_mismatch")
    if r.get("status") != STATUS or r.get("archive_compression_roundtrip_verified") is not True:
        raise RuntimeError("not_a_complete_verified_shard")
    if r.get("source_roots_complete") is not True or int(r.get("candidate_count", 0)) <= 0:
        raise RuntimeError("full_shard_coverage_not_proven")
    archive = Path(r["archive_path"]).resolve()
    raw = Path(r["output_path"]).resolve()
    if not within(archive, active) or not within(raw, active):
        raise RuntimeError("source_not_inside_C_active_root")
    if archive.suffix != ".zst" or raw.suffix != ".sqlite":
        raise RuntimeError("invalid_output_extensions")
    if archive.name != raw.name + ".zst":
        raise RuntimeError("archive_raw_identity_mismatch")
    expected_size = int(r["archive_bytes"])
    expected_hash = str(r["archive_sha256"])
    if not expected_hash or len(expected_hash) != 64 or expected_size < 1:
        raise RuntimeError("invalid_archive_expected_identity")
    destination = vault / archive.name
    receipt = vault / (archive.name + ".transfer.json")
    vault.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or receipt.is_symlink():
        raise RuntimeError("vault_link_not_allowed")
    if not within(destination, vault) or not within(receipt, vault):
        raise RuntimeError("vault_escape")
    if destination.exists() != receipt.exists():
        raise RuntimeError("incomplete_vault_pair_requires_review")
    existing = destination.exists()
    if existing:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        recorded_hash = record.get("receipt_hash")
        content = dict(record)
        content.pop("receipt_hash", None)
        if recorded_hash != stable(content) or content.get("shard_report_hash") != digest:
            raise RuntimeError("vault_receipt_identity_mismatch")
        if record.get("archive_sha256") != expected_hash or record.get("archive_bytes") != expected_size:
            raise RuntimeError("vault_receipt_archive_mismatch")
        if destination.stat().st_size != expected_size or sha_file(destination) != expected_hash:
            raise RuntimeError("vault_contents_drift")
    else:
        if not archive.is_file():
            raise FileNotFoundError("source_archive_missing")
        if archive.stat().st_size != expected_size or sha_file(archive) != expected_hash:
            raise RuntimeError("C_archive_identity_mismatch")
        if shutil.disk_usage(vault).free < expected_size + 1024 ** 3:
            raise RuntimeError("D_vault_insufficient_free_bytes")
        temp = destination.with_suffix(destination.suffix + ".incomplete")
        if temp.exists():
            raise RuntimeError("incomplete_destination_requires_review")
        with archive.open("rb") as src, temp.open("xb") as dest:
            shutil.copyfileobj(src, dest, length=8 * 1024 * 1024)
            dest.flush()
            os.fsync(dest.fileno())
        if temp.stat().st_size != expected_size or sha_file(temp) != expected_hash:
            raise RuntimeError("copied_archive_sha256_mismatch")
        os.replace(temp, destination)
        rec = {
            "format_version": 1, "status": "PASS",
            "source_group": 9, "shard_key": r["shard_key"],
            "shard_report_hash": digest,
            "archive_bytes": expected_size, "archive_sha256": expected_hash,
            "vault_file": str(destination), "copy_verified": True,
            "group9_annual_closed": False,
        }
        rec["receipt_hash"] = stable(rec)
        atomic_json(receipt, rec)
    if cleanup:
        # Source deletion is strictly after vault + durable receipt verification.
        if not receipt.is_file() or not destination.is_file():
            raise RuntimeError("verified_vault_pair_required_before_cleanup")
        if archive.exists():
            if archive.stat().st_size != expected_size or sha_file(archive) != expected_hash:
                raise RuntimeError("C_archive_drift_before_cleanup")
        if raw.exists():
            if raw.stat().st_size != int(r["output_bytes"]) or sha_file(raw) != r["output_sha256"]:
                raise RuntimeError("C_raw_drift_before_cleanup")
        if archive.exists():
            archive.unlink()
        if raw.exists():
            raw.unlink()
    return {
        "status": "ALREADY_VERIFIED" if existing else "TRANSFER_VERIFIED",
        "vault_path": str(destination), "receipt_path": str(receipt),
        "archive_bytes": expected_size,
        "archive_sha256": expected_hash,
        "C_sources_retained": not cleanup,
        "group9_annual_closed": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--active-root", type=Path, required=True)
    p.add_argument("--vault-root", type=Path, required=True)
    p.add_argument("--cleanup-verified-C", action="store_true")
    a = p.parse_args()
    result = vault_transfer(a.report, a.active_root, a.vault_root,
                            cleanup=a.cleanup_verified_C)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
