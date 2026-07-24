#!/usr/bin/env python3
"""Prove semantic equivalence between two Group 6 annual SQLite databases.

The comparator intentionally excludes operational registries/checkpoints whose byte-level
content may contain runtime paths, dependency database file hashes, or wall-clock metadata.
Every Group 6 research table that carries a stable record_hash is compared by its immutable
identity column and record_hash, after schema and SQLite integrity checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

CORE_TABLES: dict[str, str] = {
    "displacement_legs": "leg_id",
    "displacement_validation_events": "validation_id",
    "fvg_events": "fvg_id",
    "fvg_lifecycle_summary": "fvg_id",
    "fvg_state_transitions": "transition_id",
    "fvg_visit_observations": "visit_id",
    "fvg_visit_reactions": "reaction_id",
    "group6_evidence": "evidence_id",
    "imbalance_variants": "variant_id",
    "inversion_fvg_relations": "inversion_id",
    "inversion_retest_observations": "observation_id",
    "liquidity_voids": "void_id",
    "liquidity_void_members": "member_id",
    "liquidity_void_state_transitions": "transition_id",
    "liquidity_void_lifecycle_summary": "void_id",
    "bpr_relations": "bpr_id",
    "bpr_state_transitions": "transition_id",
    "bpr_lifecycle_summary": "bpr_id",
    "mtf_imbalance_relations": "relation_id",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def integrity(path: Path) -> dict[str, Any]:
    con = connect_ro(path)
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    full = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    con.close()
    return {
        "quick_check": quick,
        "integrity_check": full,
        "foreign_key_errors": len(fk),
        "tables": tables,
        "pass": quick == "ok" and full == "ok" and len(fk) == 0,
    }


def table_columns(con: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in con.execute(f'PRAGMA table_info("{table}")')]


def table_identity_rows(con: sqlite3.Connection, table: str, id_col: str) -> list[tuple[str, str]]:
    cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    missing = {id_col, "record_hash"} - cols
    if missing:
        raise RuntimeError(f"{table} missing required columns: {sorted(missing)}")
    rows = con.execute(
        f'SELECT CAST("{id_col}" AS TEXT), CAST(record_hash AS TEXT) FROM "{table}" ORDER BY "{id_col}"'
    ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def digest_rows(rows: list[tuple[str, str]]) -> str:
    return hashlib.sha256(canonical_json(rows)).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--published", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    candidate = args.candidate.resolve()
    published = args.published.resolve()
    if not candidate.is_file() or not published.is_file():
        raise FileNotFoundError("candidate and published Group 6 databases are required")

    ci = integrity(candidate)
    pi = integrity(published)
    if not ci["pass"] or not pi["pass"]:
        raise RuntimeError("SQLite integrity gate failed")

    cc = connect_ro(candidate)
    pc = connect_ro(published)
    candidate_tables = set(ci["tables"])
    published_tables = set(pi["tables"])
    missing_candidate = sorted(set(CORE_TABLES) - candidate_tables)
    missing_published = sorted(set(CORE_TABLES) - published_tables)

    table_results: dict[str, Any] = {}
    failures: list[str] = []
    if missing_candidate:
        failures.append(f"candidate_missing_tables:{','.join(missing_candidate)}")
    if missing_published:
        failures.append(f"published_missing_tables:{','.join(missing_published)}")

    for table, id_col in CORE_TABLES.items():
        if table not in candidate_tables or table not in published_tables:
            continue
        c_schema = table_columns(cc, table)
        p_schema = table_columns(pc, table)
        schema_equal = c_schema == p_schema
        c_rows = table_identity_rows(cc, table, id_col)
        p_rows = table_identity_rows(pc, table, id_col)
        c_digest = digest_rows(c_rows)
        p_digest = digest_rows(p_rows)
        rows_equal = c_rows == p_rows
        passed = schema_equal and rows_equal
        table_results[table] = {
            "identity_column": id_col,
            "candidate_count": len(c_rows),
            "published_count": len(p_rows),
            "candidate_identity_record_hash_digest": c_digest,
            "published_identity_record_hash_digest": p_digest,
            "schema_equal": schema_equal,
            "rows_equal": rows_equal,
            "pass": passed,
        }
        if not passed:
            failures.append(f"semantic_table_mismatch:{table}")

    # Source/year/config metadata must agree semantically even if operational fields differ.
    def one(con: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
        return [dict(r) for r in con.execute(sql)]

    c_dataset = one(cc, "SELECT year,source_sha256,symbol FROM dataset_registry ORDER BY dataset_id")
    p_dataset = one(pc, "SELECT year,source_sha256,symbol FROM dataset_registry ORDER BY dataset_id")
    c_config = one(cc, "SELECT engine_version,schema_version,config_json FROM config_registry ORDER BY config_id")
    p_config = one(pc, "SELECT engine_version,schema_version,config_json FROM config_registry ORDER BY config_id")
    metadata_equal = c_dataset == p_dataset and c_config == p_config
    if not metadata_equal:
        failures.append("dataset_or_config_semantic_mismatch")

    cc.close()
    pc.close()

    report: dict[str, Any] = {
        "format_version": 1,
        "comparison_scope": "Group6 immutable research tables by stable identity + record_hash; operational registries/checkpoints/audit timestamps excluded",
        "candidate": {"filename": candidate.name, "size_bytes": candidate.stat().st_size, "sha256": sha256_file(candidate), "sqlite": ci},
        "published": {"filename": published.name, "size_bytes": published.stat().st_size, "sha256": sha256_file(published), "sqlite": pi},
        "dataset_config_semantics_equal": metadata_equal,
        "core_tables": table_results,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    report["report_hash"] = hashlib.sha256(canonical_json(report)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report_hash": report["report_hash"], "tables": len(table_results)}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
