#!/usr/bin/env python3
"""Package annual Group 2-5 SQLite dependencies as additive Data Vault assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

MAX_PART_BYTES = 1_900_000_000
GROUPS = ("group2", "group3", "group4", "group5")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def split_file(source: Path, output_dir: Path) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    with source.open("rb") as src:
        index = 0
        while True:
            chunk = src.read(MAX_PART_BYTES)
            if not chunk:
                break
            name = f"{source.name}.part-{index:03d}"
            path = output_dir / name
            path.write_bytes(chunk)
            parts.append({"filename": name, "size_bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
            index += 1
    if not parts:
        raise RuntimeError(f"no parts generated for {source}")
    return parts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=(2023, 2024))
    ap.add_argument("--pipeline-report", type=Path, required=True)
    ap.add_argument("--g6-equivalence", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--repository", required=True)
    ap.add_argument("--release-tag", required=True)
    args = ap.parse_args()

    pipeline = json.loads(args.pipeline_report.read_text(encoding="utf-8"))
    equivalence = json.loads(args.g6_equivalence.read_text(encoding="utf-8"))
    if equivalence.get("status") != "PASS":
        raise RuntimeError("Group 6 semantic equivalence must PASS before packaging G2-G5")
    if int(pipeline.get("year", -1)) != args.year:
        raise RuntimeError("pipeline report year mismatch")

    out = args.output_dir.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    packages: dict[str, Any] = {}
    for group in GROUPS:
        row = pipeline["artifacts"][group]
        db = Path(row["path"]).resolve()
        if not db.is_file():
            raise FileNotFoundError(db)
        actual_size = db.stat().st_size
        actual_sha = sha256_file(db)
        if actual_size != int(row["size_bytes"]) or actual_sha != row["sha256"]:
            raise RuntimeError(f"pipeline artifact identity drift for {group}")

        compressed = out / f"{db.name}.zst"
        proc = subprocess.run(
            ["zstd", "-q", "-19", "--long=31", "-T0", "-f", str(db), "-o", str(compressed)],
            text=True,
            capture_output=True,
        )
        if proc.returncode:
            raise RuntimeError(f"zstd failed for {group}: {proc.stderr}")
        compressed_size = compressed.stat().st_size
        compressed_sha = sha256_file(compressed)
        parts = split_file(compressed, out)
        compressed.unlink()
        for part in parts:
            part["url"] = f"https://github.com/{args.repository}/releases/download/{args.release_tag}/{part['filename']}"
        packages[group] = {
            "database_filename": db.name,
            "database_size_bytes": actual_size,
            "database_sha256": actual_sha,
            "compressed_filename": f"{db.name}.zst",
            "compressed_size_bytes": compressed_size,
            "compressed_sha256": compressed_sha,
            "compression": "zstd -19 --long=31",
            "parts": parts,
            "sqlite_check": pipeline["sqlite_checks"][group],
        }

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "PASS_PACKAGED",
        "lineage": "dukascopy_rebuild_v1",
        "purpose": "Group 8 real annual upstream dependencies for frozen Groups 2-5",
        "year": args.year,
        "repository": args.repository,
        "release_tag": args.release_tag,
        "source_sha256": pipeline["source_sha256"],
        "runtime_engines": pipeline["engines"],
        "group6_semantic_equivalence": {
            "status": equivalence["status"],
            "report_hash": equivalence["report_hash"],
            "published_group6_sha256": equivalence["published"]["sha256"],
            "candidate_group6_sha256": equivalence["candidate"]["sha256"],
        },
        "packages": packages,
    }
    report["manifest_hash"] = hashlib.sha256(canonical_json(report)).hexdigest()
    manifest = out / f"MoeBot_Group8_Upstream_G2-G5_{args.year}_manifest.json"
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "manifest": manifest.name, "manifest_hash": report["manifest_hash"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
