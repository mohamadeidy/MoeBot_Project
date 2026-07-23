#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", required=True, choices=("2023", "2024"))
    p.add_argument("--db", required=True)
    p.add_argument("--verification", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--part-size", type=int, default=1800 * 1024 * 1024)
    args = p.parse_args()
    db = Path(args.db)
    verification = Path(args.verification)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    compressed = out / f"{db.name}.zst"
    subprocess.run(["zstd", "-T0", "-19", "--long=31", "-f", str(db), "-o", str(compressed)], check=True)
    parts = []
    with compressed.open("rb") as src:
        index = 0
        while True:
            data = src.read(args.part_size)
            if not data:
                break
            part = out / f"{compressed.name}.part-{index:03d}"
            part.write_bytes(data)
            parts.append({
                "filename": part.name,
                "size_bytes": part.stat().st_size,
                "sha256": sha256_file(part),
                "url": f"https://github.com/{args.repository}/releases/download/{args.tag}/{part.name}",
            })
            index += 1
    verification_data = json.loads(verification.read_text(encoding="utf-8"))
    manifest = {
        "format_version": 1,
        "year": int(args.year),
        "repository": args.repository,
        "release_tag": args.tag,
        "lineage": verification_data["lineage"],
        "engine_version": verification_data["engine_version"],
        "schema_version": verification_data["schema_version"],
        "config_id": verification_data["summary"]["config_id"],
        "passed": verification_data["passed"],
        "database_filename": db.name,
        "database_size_bytes": db.stat().st_size,
        "database_sha256": sha256_file(db),
        "compressed_filename": compressed.name,
        "compressed_size_bytes": compressed.stat().st_size,
        "compressed_sha256": sha256_file(compressed),
        "compression": "zstd -19 --long=31",
        "parts": parts,
        "verification_filename": verification.name,
        "summary": verification_data["summary"],
        "gates": verification_data["gates"],
    }
    manifest_path = out / f"GROUP7_MANIFEST_{args.year}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    compressed.unlink()
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
