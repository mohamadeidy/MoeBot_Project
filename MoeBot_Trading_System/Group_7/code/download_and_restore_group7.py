#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True)
    p.add_argument("--year", choices=("2023", "2024", "both"), default="both")
    p.add_argument("--download-dir", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    years = ("2023", "2024") if args.year == "both" else (args.year,)
    downloads = Path(args.download_dir); outputs = Path(args.output_dir)
    downloads.mkdir(parents=True, exist_ok=True); outputs.mkdir(parents=True, exist_ok=True)
    restored = {}
    for year in years:
        entry = registry["years"][year]
        part_paths = []
        for part in entry["parts"]:
            target = downloads / part["filename"]
            if not target.exists() or target.stat().st_size != part["size_bytes"] or sha256_file(target) != part["sha256"]:
                urllib.request.urlretrieve(part["url"], target)
            if target.stat().st_size != part["size_bytes"] or sha256_file(target) != part["sha256"]:
                raise SystemExit(f"Part verification failed: {target}")
            part_paths.append(target)
        compressed = downloads / entry["compressed_filename"]
        with compressed.open("wb") as out:
            for part in part_paths:
                with part.open("rb") as src:
                    while chunk := src.read(8 * 1024 * 1024):
                        out.write(chunk)
        if compressed.stat().st_size != entry["compressed_size_bytes"] or sha256_file(compressed) != entry["compressed_sha256"]:
            raise SystemExit(f"Compressed stream verification failed: {compressed}")
        db = outputs / entry["database_filename"]
        subprocess.run(["zstd", "-d", "-f", str(compressed), "-o", str(db)], check=True)
        if db.stat().st_size != entry["database_size_bytes"] or sha256_file(db) != entry["database_sha256"]:
            raise SystemExit(f"Database verification failed: {db}")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
        con.close()
        if quick != "ok" or integrity != "ok" or fk:
            raise SystemExit(f"SQLite verification failed: {db}")
        restored[year] = {"path": str(db.resolve()), "size_bytes": db.stat().st_size, "sha256": sha256_file(db), "quick_check": quick, "integrity_check": integrity, "foreign_key_errors": fk}
    print(json.dumps({"status": "pass", "restored": restored}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
