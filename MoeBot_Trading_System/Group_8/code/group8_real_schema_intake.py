#!/usr/bin/env python3
# Dependency intake trigger: closure tag verified before execution.
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows_as_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [item[0] for item in cursor.description or []]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def pragma_rows(conn: sqlite3.Connection, pragma: str) -> list[dict[str, Any]]:
    return rows_as_dicts(conn.execute(pragma))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)

    actual_size = database.stat().st_size
    actual_sha = sha256_file(database)
    identity_pass = actual_size == args.expected_size and actual_sha == args.expected_sha256

    uri = f"file:{database.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        quick_check = [row[0] for row in conn.execute("PRAGMA quick_check").fetchall()]
        integrity_check = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        foreign_key_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]

        objects = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE type IN ('table','view','index','trigger') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()

        tables: dict[str, Any] = {}
        views: dict[str, Any] = {}
        indexes: list[dict[str, Any]] = []
        triggers: list[dict[str, Any]] = []

        for obj in objects:
            record = {
                "type": obj["type"],
                "name": obj["name"],
                "table": obj["tbl_name"],
                "sql": obj["sql"],
            }
            if obj["type"] == "table":
                name_escaped = obj["name"].replace("'", "''")
                table_record = {
                    **record,
                    "columns": pragma_rows(conn, f"PRAGMA table_info('{name_escaped}')"),
                    "foreign_keys": pragma_rows(conn, f"PRAGMA foreign_key_list('{name_escaped}')"),
                    "indexes": pragma_rows(conn, f"PRAGMA index_list('{name_escaped}')"),
                }
                table_record["schema_hash"] = hashlib.sha256(canonical_json(table_record).encode()).hexdigest()
                tables[obj["name"]] = table_record
            elif obj["type"] == "view":
                views[obj["name"]] = record
            elif obj["type"] == "index":
                indexes.append(record)
            elif obj["type"] == "trigger":
                triggers.append(record)

        report = {
            "format_version": 1,
            "year": args.year,
            "database": {
                "filename": database.name,
                "size_bytes": actual_size,
                "expected_size_bytes": args.expected_size,
                "sha256": actual_sha,
                "expected_sha256": args.expected_sha256,
                "identity_pass": identity_pass,
            },
            "sqlite": {
                "quick_check": quick_check,
                "integrity_check": integrity_check,
                "foreign_key_error_count": len(foreign_key_errors),
                "foreign_key_errors": foreign_key_errors[:100],
                "pass": quick_check == ["ok"] and integrity_check == ["ok"] and not foreign_key_errors,
            },
            "schema": {
                "table_count": len(tables),
                "view_count": len(views),
                "index_count": len(indexes),
                "trigger_count": len(triggers),
                "tables": dict(sorted(tables.items())),
                "views": dict(sorted(views.items())),
                "indexes": indexes,
                "triggers": triggers,
            },
        }
        report["status"] = "pass" if identity_pass and report["sqlite"]["pass"] else "fail"
        report["report_hash"] = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    finally:
        conn.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report_hash": report["report_hash"]}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
