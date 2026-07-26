#!/usr/bin/env python3
"""Deterministic logical SQLite fingerprinting for Group 8 annual validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    def norm(v: Any) -> Any:
        if isinstance(v, bytes):
            return {"__blob_hex__": v.hex()}
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError("non-finite float in SQLite fingerprint")
            return {"__float_hex__": v.hex()}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        if isinstance(v, dict):
            return {str(k): norm(v[k]) for k in sorted(v)}
        return v
    return json.dumps(norm(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprint(db: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if quick != "ok" or integrity != "ok" or fk:
            raise RuntimeError(f"SQLite integrity failure quick={quick} integrity={integrity} fk={len(fk)}")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        table_reports: dict[str, Any] = {}
        logical = hashlib.sha256()
        for table in tables:
            info = con.execute(f"PRAGMA table_info({q(table)})").fetchall()
            cols = [r[1] for r in info]
            pk = [r[1] for r in sorted((r for r in info if int(r[5]) > 0), key=lambda r: int(r[5]))]
            order = pk or cols
            schema_sql_row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            schema_sql = schema_sql_row[0] if schema_sql_row else ""
            th = hashlib.sha256()
            header = {"table": table, "columns": cols, "pk": pk, "schema_sql": schema_sql}
            th.update(canonical(header)); th.update(b"\n")
            query = f"SELECT {','.join(q(c) for c in cols)} FROM {q(table)}"
            if order:
                query += " ORDER BY " + ",".join(q(c) for c in order)
            count = 0
            cur = con.execute(query)
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                for row in rows:
                    th.update(canonical([row[c] for c in cols])); th.update(b"\n")
                    count += 1
            table_hash = th.hexdigest()
            rec = {"row_count": count, "columns": cols, "primary_key": pk, "logical_sha256": table_hash}
            table_reports[table] = rec
            logical.update(canonical({"table": table, **rec})); logical.update(b"\n")
        report = {
            "format_version": 1,
            "status": "PASS",
            "database_filename": db.name,
            "database_size_bytes": db.stat().st_size,
            "database_sha256": shaf(db),
            "logical_sha256": logical.hexdigest(),
            "table_count": len(tables),
            "tables": table_reports,
            "quick_check": quick,
            "integrity_check": integrity,
            "foreign_key_errors": len(fk),
        }
        report["report_hash"] = hashlib.sha256(canonical(report)).hexdigest()
        return report
    finally:
        con.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = fingerprint(a.database)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "logical_sha256": report["logical_sha256"], "database_sha256": report["database_sha256"], "table_count": report["table_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
