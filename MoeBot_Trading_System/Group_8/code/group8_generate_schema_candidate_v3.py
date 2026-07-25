#!/usr/bin/env python3
"""Generate coherent-only Group 8 schema candidate v3.

This removes the rejected upstream-ID bridge persistence model and historical
Group7 recovery-anchor fields. Group8 consumes one coherent corrected-v3
Groups2-7 annual lineage and records that lineage explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

IMMUTABLE_TABLES = (
    "config_registry",
    "dataset_registry",
    "dependency_registry",
    "school_registry",
    "pattern_definition_registry",
    "interpretation_definition_registry",
    "price_action_pattern_candidate",
    "price_action_pattern_state",
    "school_interpretation",
    "shared_evidence",
    "conflicting_evidence",
    "narrative_hypothesis",
    "hypothesis_lifecycle_event",
    "multi_timeframe_context_relation",
    "evidence_chain",
    "invalidation_record",
    "group8_audit_evidence",
)

EXISTING_TRIGGER_TABLES = {
    "price_action_pattern_candidate",
    "school_interpretation",
    "narrative_hypothesis",
    "shared_evidence",
    "conflicting_evidence",
}

REQUIRED_DATASET_COLUMNS = {
    "dataset_id",
    "symbol",
    "year",
    "lineage",
    "logical_dependency_lineage_id",
    "dependency_release_anchor_tag",
    "source_db_filename",
    "source_db_size_bytes",
    "source_db_sha256",
    "group7_db_filename",
    "group7_db_size_bytes",
    "group7_db_sha256",
    "group7_logic_source_closure_tag",
    "group7_logic_source_closure_commit_sha",
    "coherent_lineage_amendment_hash",
    "annual_dependency_registry_hash",
    "adapter_map_hash",
    "categorical_dictionary_hash",
    "value_bindings_hash",
    "definition_registry_hash",
    "created_at",
    "record_hash",
}

FORBIDDEN_LEGACY_DATASET_COLUMNS = {
    "group7_recovery_anchor_tag",
    "group7_recovery_anchor_commit_sha",
    "group7_source_closure_tag",
    "group7_source_closure_commit_sha",
    "upstream_lineage_bridge_hash",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    sql = args.draft.read_text(encoding="utf-8")
    start = sql.index("CREATE TABLE IF NOT EXISTS dataset_registry(")
    end = sql.index("CREATE TABLE IF NOT EXISTS dependency_registry(")

    dataset = """CREATE TABLE IF NOT EXISTS dataset_registry(
    dataset_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    year INTEGER NOT NULL,
    lineage TEXT NOT NULL,
    logical_dependency_lineage_id TEXT NOT NULL,
    dependency_release_anchor_tag TEXT NOT NULL,
    source_db_filename TEXT NOT NULL,
    source_db_size_bytes INTEGER NOT NULL,
    source_db_sha256 TEXT NOT NULL,
    group7_db_filename TEXT NOT NULL,
    group7_db_size_bytes INTEGER NOT NULL,
    group7_db_sha256 TEXT NOT NULL,
    group7_logic_source_closure_tag TEXT NOT NULL,
    group7_logic_source_closure_commit_sha TEXT NOT NULL,
    coherent_lineage_amendment_hash TEXT NOT NULL,
    annual_dependency_registry_hash TEXT NOT NULL,
    adapter_map_hash TEXT NOT NULL,
    categorical_dictionary_hash TEXT NOT NULL,
    value_bindings_hash TEXT NOT NULL,
    definition_registry_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    record_hash TEXT NOT NULL
);

"""
    sql = sql[:start] + dataset + sql[end:]

    extra = [
        "",
        "-- All registries, creation records, evidence, lifecycle and invalidation rows are append-only.",
    ]
    for table in IMMUTABLE_TABLES:
        if table in EXISTING_TRIGGER_TABLES:
            continue
        extra.append(
            f"CREATE TRIGGER IF NOT EXISTS no_update_{table}\n"
            f"BEFORE UPDATE ON {table} BEGIN\n"
            f"    SELECT RAISE(ABORT,'immutable record: {table}');\nEND;"
        )
        extra.append(
            f"CREATE TRIGGER IF NOT EXISTS no_delete_{table}\n"
            f"BEFORE DELETE ON {table} BEGIN\n"
            f"    SELECT RAISE(ABORT,'immutable record: {table}');\nEND;"
        )
    sql = sql.rstrip() + "\n" + "\n".join(extra) + "\n"

    con = sqlite3.connect(":memory:")
    con.executescript(sql)
    tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    triggers = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))
    missing_triggers: list[str] = []
    for table in IMMUTABLE_TABLES:
        for prefix in ("no_update_", "no_delete_"):
            if prefix + table not in triggers:
                missing_triggers.append(prefix + table)
    dataset_cols = {r[1] for r in con.execute("PRAGMA table_info('dataset_registry')")}
    con.close()

    failures: list[str] = []
    if "upstream_id_bridge" in tables:
        failures.append("rejected_bridge_table_present")
    missing_cols = sorted(REQUIRED_DATASET_COLUMNS - dataset_cols)
    legacy_cols = sorted(FORBIDDEN_LEGACY_DATASET_COLUMNS & dataset_cols)
    if missing_cols:
        failures.append("missing_dataset_columns:" + ",".join(missing_cols))
    if legacy_cols:
        failures.append("legacy_dataset_columns_present:" + ",".join(legacy_cols))
    failures.extend(missing_triggers)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8")
    report = {
        "format_version": 3,
        "status": "PASS" if not failures else "FAIL",
        "source_draft": args.draft.name,
        "output": args.output.name,
        "schema_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "table_count": len(tables),
        "trigger_count": len(triggers),
        "immutable_table_count": len(IMMUTABLE_TABLES),
        "rejected_bridge_table_absent": "upstream_id_bridge" not in tables,
        "dataset_columns": sorted(dataset_cols),
        "missing_dataset_columns": missing_cols,
        "legacy_dataset_columns_present": legacy_cols,
        "missing_immutability_triggers": missing_triggers,
        "failures": failures,
        "governance": "coherent corrected-v3 Groups2-7 lineage only; no lossy upstream-ID bridge",
    }
    report["report_hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
