#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_restore_module(path: Path):
    spec = importlib.util.spec_from_file_location("moebot_data_vault_restore", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load restore module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annual-registry", type=Path, required=True)
    ap.add_argument("--data-vault-restorer", type=Path, required=True)
    ap.add_argument("--year", choices=("2023", "2024"), required=True)
    ap.add_argument("--download-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    registry = json.loads(args.annual_registry.read_text(encoding="utf-8"))
    if registry.get("status") != "PASS":
        raise SystemExit("Group 8 annual dependency registry is not PASS")
    source = registry.get("source_databases", {}).get(args.year)
    if not source:
        raise SystemExit(f"missing frozen source identity for {args.year}")

    restore_module = load_restore_module(args.data_vault_restorer)
    db = restore_module.restore(source, args.download_dir, args.output_dir)

    actual_size = db.stat().st_size
    actual_sha = sha256_file(db)
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    con.close()

    passed = (
        actual_size == int(source["database_size_bytes"])
        and actual_sha == source["database_sha256"]
        and quick == "ok"
        and integrity == "ok"
        and fk == 0
    )
    report = {
        "format_version": 1,
        "status": "PASS" if passed else "FAIL",
        "year": int(args.year),
        "database": {
            "filename": db.name,
            "size_bytes": actual_size,
            "sha256": actual_sha,
        },
        "expected_database": {
            "filename": source["database_filename"],
            "size_bytes": int(source["database_size_bytes"]),
            "sha256": source["database_sha256"],
        },
        "sqlite": {
            "quick_check": quick,
            "integrity_check": integrity,
            "foreign_key_errors": fk,
        },
        "source_registry_entry": source,
    }
    report["report_hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
