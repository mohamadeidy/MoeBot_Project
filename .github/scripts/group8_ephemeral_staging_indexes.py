#!/usr/bin/env python3
"""Create execution-only SQLite indexes on a Group 8 staging database.

The script is deliberately outside the frozen Group 8 engine/code directory.
It may create indexes only; it performs no INSERT/UPDATE/DELETE, no ANALYZE,
no VACUUM, and no table/schema-column mutation. The annual engine consumes the
same staging rows and frozen adapter columns as before.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

INDEX_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_g8_exec_source_bars_sym_tf_close", "source__bars", ("symbol", "timeframe", "close_time", "id")),
    ("ix_g8_exec_g3_states_tf_close", "group3__structure_states", ("timeframe", "close_time", "state_id")),
    ("ix_g8_exec_g3_states_sym_tf_layer_close", "group3__structure_states", ("symbol", "timeframe", "layer", "close_time", "state_id")),
    ("ix_g8_exec_g3_break_sym_tf_resolved", "group3__break_events", ("symbol", "timeframe", "resolved_time", "event_id")),
    ("ix_g8_exec_g4_zones_sym_tf_avail_expire", "group4__zones", ("symbol", "timeframe", "available_at", "expires_at", "zone_id")),
    ("ix_g8_exec_g4_trans_zone_time", "group4__zone_transitions", ("zone_id", "transition_time", "transition_id")),
    ("ix_g8_exec_g4_inter_zone_time", "group4__zone_interactions", ("zone_id", "interaction_time", "interaction_id")),
    ("ix_g8_exec_g5_pools_sym_tf_avail_expire", "group5__liquidity_pools", ("symbol", "timeframe", "available_at", "expires_at", "pool_id")),
    ("ix_g8_exec_g5_events_tf_resolved_pool", "group5__liquidity_events", ("timeframe", "resolved_time", "pool_id", "event_id")),
    ("ix_g8_exec_g5_events_pool_resolved", "group5__liquidity_events", ("pool_id", "resolved_time", "event_id")),
    ("ix_g8_exec_g5_draw_tf_close", "group5__draw_states", ("timeframe", "close_time", "draw_id")),
    ("ix_g8_exec_g6_fvg_avail", "group6__fvg_events", ("availability_time", "fvg_id")),
    ("ix_g8_exec_g6_fvg_assoc", "group6__fvg_events", ("associated_group3_event_id", "availability_time", "fvg_id")),
    ("ix_g8_exec_g6_imbalance_avail", "group6__imbalance_variants", ("availability_time", "variant_id")),
    ("ix_g8_exec_g6_void_avail", "group6__liquidity_voids", ("availability_time", "void_id")),
    ("ix_g8_exec_g6_bpr_avail", "group6__bpr_relations", ("availability_time", "bpr_id")),
    ("ix_g8_exec_g6_fvgtr_fvg_time", "group6__fvg_state_transitions", ("fvg_id", "transition_time", "transition_id")),
    ("ix_g8_exec_g6_valid_leg_avail", "group6__displacement_validation_events", ("leg_id", "availability_time", "validation_id")),
    ("ix_g8_exec_g6_evidence_avail", "group6__group6_evidence", ("availability_time", "evidence_id")),
    ("ix_g8_exec_g7_zones_tf_avail", "group7__institutional_zones", ("timeframe", "availability_time", "zone_id")),
    ("ix_g8_exec_g7_zstate_zone_time", "group7__zone_state_transitions", ("zone_id", "transition_time", "transition_ordinal")),
    ("ix_g8_exec_g7_evidence_zone_avail", "group7__zone_evidence", ("zone_id", "availability_time", "evidence_id")),
)


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    db = a.database.resolve()
    if not db.is_file():
        raise SystemExit(f"staging database missing: {db}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    failures: list[str] = []
    table_names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    before_changes = con.total_changes
    before_user_version = int(con.execute("PRAGMA user_version").fetchone()[0])
    existing_exec_indexes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_g8_exec_%'")}
    created: list[dict[str, object]] = []

    for name, table, columns in INDEX_SPECS:
        if table not in table_names:
            failures.append(f"missing_table:{table}")
            continue
        actual = {r[1] for r in con.execute(f"PRAGMA table_info({q(table)})")}
        missing = [c for c in columns if c not in actual]
        if missing:
            failures.append(f"missing_columns:{table}:{','.join(missing)}")
            continue
        sql = f"CREATE INDEX IF NOT EXISTS {q(name)} ON {q(table)} ({','.join(q(c) for c in columns)})"
        if not sql.startswith("CREATE INDEX IF NOT EXISTS "):
            failures.append(f"non_index_sql:{name}")
            continue
        con.execute(sql)
        created.append({"name": name, "table": table, "columns": list(columns), "sql": sql})

    con.commit()
    after_changes = con.total_changes
    if after_changes != before_changes:
        failures.append(f"unexpected_data_changes:{before_changes}->{after_changes}")
    if int(con.execute("PRAGMA user_version").fetchone()[0]) != before_user_version:
        failures.append("user_version_changed")

    qc = con.execute("PRAGMA quick_check").fetchone()[0]
    ic = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if qc != "ok": failures.append(f"quick_check:{qc}")
    if ic != "ok": failures.append(f"integrity_check:{ic}")
    if fk: failures.append(f"foreign_key_errors:{len(fk)}")

    actual_indexes = {
        r[0]: r[1]
        for r in con.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND name LIKE 'ix_g8_exec_%' ORDER BY name")
    }
    for spec in created:
        if spec["name"] not in actual_indexes:
            failures.append(f"index_not_created:{spec['name']}")
    unexpected = sorted(set(actual_indexes) - existing_exec_indexes - {str(s["name"]) for s in created})
    if unexpected:
        failures.append(f"unexpected_exec_indexes:{unexpected}")

    stage_manifest = {}
    if "stage_manifest" in table_names:
        stage_manifest = {str(r[0]): str(r[1]) for r in con.execute("SELECT key,value FROM stage_manifest")}
    con.close()

    report = {
        "format_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "year": int(a.year),
        "phase": a.phase,
        "scope": "EPHEMERAL_STAGING_INDEXES_ONLY",
        "engine_version": stage_manifest.get("engine_version"),
        "schema_version": stage_manifest.get("schema_version"),
        "config_id": stage_manifest.get("config_id"),
        "logical_dependency_lineage_id": stage_manifest.get("logical_dependency_lineage_id"),
        "index_count": len(created),
        "indexes": created,
        "sqlite_total_changes_before": before_changes,
        "sqlite_total_changes_after": after_changes,
        "data_changes": after_changes - before_changes,
        "quick_check": qc,
        "integrity_check": ic,
        "foreign_key_errors": len(fk),
        "prohibitions": {
            "insert": True,
            "update": True,
            "delete": True,
            "analyze": True,
            "vacuum": True,
            "table_or_column_mutation": True,
        },
        "failures": failures,
    }
    report["report_hash"] = stable_hash(report)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
