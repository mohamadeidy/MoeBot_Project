#!/usr/bin/env python3
"""Clean-room verify a published annual Group 2-5 dependency pack."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sqlite_inventory(path: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = [tuple(r) for r in con.execute("PRAGMA foreign_key_check")]
    tables: dict[str, Any] = {}
    for row in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        name = row["name"]
        columns = [dict(r) for r in con.execute(f'PRAGMA table_info("{name}")')]
        foreign_keys = [dict(r) for r in con.execute(f'PRAGMA foreign_key_list("{name}")')]
        indexes = []
        for idx in con.execute(f'PRAGMA index_list("{name}")'):
            idxd = dict(idx)
            idxd["columns"] = [dict(r) for r in con.execute(f'PRAGMA index_info("{idxd["name"]}")')]
            indexes.append(idxd)
        tables[name] = {"create_sql": row["sql"], "columns": columns, "foreign_keys": foreign_keys, "indexes": indexes}
    con.close()
    return {
        "quick_check": quick,
        "integrity_check": integrity,
        "foreign_key_errors": len(fk_errors),
        "pass": quick == "ok" and integrity == "ok" and not fk_errors,
        "tables": tables,
    }


def download(url: str, destination: Path) -> None:
    proc = subprocess.run(
        ["curl", "-L", "--fail", "--retry", "5", "--retry-all-errors", url, "-o", str(destination)],
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise RuntimeError(f"download failed {url}: {proc.stderr[-2000:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS_PACKAGED":
        raise RuntimeError("manifest is not PASS_PACKAGED")
    work = args.work_dir.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    results: dict[str, Any] = {}
    failures: list[str] = []
    for group in ("group2", "group3", "group4", "group5"):
        row = manifest["packages"][group]
        group_dir = work / group
        group_dir.mkdir()
        compressed = group_dir / row["compressed_filename"]
        with compressed.open("wb") as out:
            for part in row["parts"]:
                part_path = group_dir / part["filename"]
                download(part["url"], part_path)
                if part_path.stat().st_size != int(part["size_bytes"]) or sha256_file(part_path) != part["sha256"]:
                    raise RuntimeError(f"part identity mismatch: {group}/{part['filename']}")
                with part_path.open("rb") as src:
                    shutil.copyfileobj(src, out, length=16 * 1024 * 1024)
                part_path.unlink()
        compressed_ok = compressed.stat().st_size == int(row["compressed_size_bytes"]) and sha256_file(compressed) == row["compressed_sha256"]
        if not compressed_ok:
            raise RuntimeError(f"compressed identity mismatch: {group}")
        database = group_dir / row["database_filename"]
        proc = subprocess.run(["zstd", "-d", "--long=31", "-f", str(compressed), "-o", str(database)], text=True, capture_output=True)
        if proc.returncode:
            raise RuntimeError(f"zstd decompression failed {group}: {proc.stderr[-2000:]}")
        compressed.unlink()
        db_ok = database.stat().st_size == int(row["database_size_bytes"]) and sha256_file(database) == row["database_sha256"]
        inventory = sqlite_inventory(database)
        passed = compressed_ok and db_ok and inventory["pass"]
        results[group] = {
            "database_filename": database.name,
            "database_size_bytes": database.stat().st_size,
            "database_sha256": sha256_file(database),
            "compressed_size_bytes": int(row["compressed_size_bytes"]),
            "compressed_sha256": row["compressed_sha256"],
            "sqlite": inventory,
            "pass": passed,
        }
        if not passed:
            failures.append(group)
        database.unlink()
        group_dir.rmdir()

    report: dict[str, Any] = {
        "format_version": 1,
        "year": manifest["year"],
        "lineage": manifest["lineage"],
        "release_tag": manifest["release_tag"],
        "source_manifest_hash": manifest["manifest_hash"],
        "group6_semantic_equivalence": manifest["group6_semantic_equivalence"],
        "groups": results,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    report["report_hash"] = hashlib.sha256(canonical_json(report)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "year": report["year"], "report_hash": report["report_hash"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
