#!/usr/bin/env python3
"""Inspect exact 2023 Group6 lifecycle evidence relevant to PA7 boundary retirement.

Diagnostic only. It does not infer a new lifecycle rule, mutate frozen state, or
access 2024 OOS. The purpose is to determine whether PA7 currently keeps Group6
boundaries eligible after an upstream causally timestamped lifecycle termination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

ENGINE_SHA = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def grouped(con: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()

    if sha256_file(root / "code/moebot_group8_engine_v0_8_0.py") != ENGINE_SHA:
        raise SystemExit("unexpected engine identity")
    registry = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    status = json.loads((root / "STATUS.json").read_text())
    if registry.get("registry_hash") != REGISTRY_HASH or freeze.get("design_freeze_hash") != FREEZE_HASH:
        raise SystemExit("frozen design identity mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("authorization boundary mismatch")

    con = sqlite3.connect(a.staging_db)
    try:
        required = [
            "group6__fvg_events", "group6__fvg_lifecycle_summary", "group6__fvg_state_transitions",
            "group6__imbalance_variants", "group6__liquidity_voids", "group6__bpr_relations",
        ]
        missing = [t for t in required if not table_exists(con, t)]
        if missing:
            raise SystemExit(f"missing exact Group6 lifecycle tables: {missing}")

        fvg_summary = grouped(con, """
            SELECT COALESCE(fill_state,'<NULL>') AS fill_state,
                   COALESCE(directional_validity,'<NULL>') AS directional_validity,
                   COUNT(*) AS n,
                   SUM(CASE WHEN first_touch_time IS NOT NULL THEN 1 ELSE 0 END) AS with_first_touch,
                   SUM(CASE WHEN ce_time IS NOT NULL THEN 1 ELSE 0 END) AS with_ce_time,
                   SUM(CASE WHEN full_fill_time IS NOT NULL THEN 1 ELSE 0 END) AS with_full_fill_time,
                   SUM(CASE WHEN traverse_time IS NOT NULL THEN 1 ELSE 0 END) AS with_traverse_time
            FROM group6__fvg_lifecycle_summary
            GROUP BY fill_state,directional_validity
            ORDER BY n DESC,fill_state,directional_validity
        """)
        fvg_transitions = grouped(con, """
            SELECT COALESCE(event_type,'<NULL>') AS event_type,
                   COALESCE(fill_state,'<NULL>') AS fill_state,
                   COALESCE(directional_validity,'<NULL>') AS directional_validity,
                   COUNT(*) AS n,
                   MIN(transition_time) AS min_transition_time,
                   MAX(transition_time) AS max_transition_time
            FROM group6__fvg_state_transitions
            GROUP BY event_type,fill_state,directional_validity
            ORDER BY n DESC,event_type,fill_state,directional_validity
        """)
        fvg_counts = grouped(con, """
            SELECT e.timeframe AS timeframe,
                   COUNT(*) AS fvg_count,
                   SUM(CASE WHEN s.first_touch_time IS NOT NULL THEN 1 ELSE 0 END) AS with_first_touch,
                   SUM(CASE WHEN s.ce_time IS NOT NULL THEN 1 ELSE 0 END) AS with_ce_time,
                   SUM(CASE WHEN s.full_fill_time IS NOT NULL THEN 1 ELSE 0 END) AS with_full_fill_time,
                   SUM(CASE WHEN s.traverse_time IS NOT NULL THEN 1 ELSE 0 END) AS with_traverse_time
            FROM group6__fvg_events e
            LEFT JOIN group6__fvg_lifecycle_summary s ON s.fvg_id=e.fvg_id
            GROUP BY e.timeframe ORDER BY e.timeframe
        """)
        boundary_states = {
            "bpr_relations": grouped(con, "SELECT timeframe,COALESCE(state,'<NULL>') AS state,COUNT(*) AS n FROM group6__bpr_relations GROUP BY timeframe,state ORDER BY timeframe,n DESC,state"),
            "liquidity_voids": grouped(con, "SELECT timeframe,COALESCE(state,'<NULL>') AS state,COUNT(*) AS n FROM group6__liquidity_voids GROUP BY timeframe,state ORDER BY timeframe,n DESC,state"),
            "imbalance_variants": grouped(con, "SELECT timeframe,COALESCE(variant_type,'<NULL>') AS variant_type,COALESCE(classification,'<NULL>') AS classification,COUNT(*) AS n FROM group6__imbalance_variants GROUP BY timeframe,variant_type,classification ORDER BY timeframe,n DESC,variant_type,classification"),
        }
        boundary_counts = grouped(con, """
            SELECT source_type,timeframe,SUM(n) AS n FROM (
              SELECT 'fvg_events' AS source_type,timeframe,COUNT(*) AS n FROM group6__fvg_events GROUP BY timeframe
              UNION ALL SELECT 'imbalance_variants',timeframe,COUNT(*) FROM group6__imbalance_variants GROUP BY timeframe
              UNION ALL SELECT 'liquidity_voids',timeframe,COUNT(*) FROM group6__liquidity_voids GROUP BY timeframe
              UNION ALL SELECT 'bpr_relations',timeframe,COUNT(*) FROM group6__bpr_relations GROUP BY timeframe
            ) GROUP BY source_type,timeframe ORDER BY timeframe,source_type
        """)
        integrity = con.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        con.close()

    engine_text = (root / "code/moebot_group8_engine_v0_8_0.py").read_text()
    report: dict[str, Any] = {
        "format_version": 1,
        "status": "PASS",
        "scope": "GROUP6_PA7_LIFECYCLE_ROOT_CAUSE_2023_ONLY",
        "engine_sha256": ENGINE_SHA,
        "definition_registry_hash": REGISTRY_HASH,
        "design_freeze_hash": FREEZE_HASH,
        "sqlite_quick_check": integrity,
        "engine_group6_active_at_falls_through_true": 'if bnd["group"]=="group7"' in engine_text and 'return True\n\n    def _pa7_beyond' in engine_text,
        "fvg_lifecycle_summary_distribution": fvg_summary,
        "fvg_transition_distribution": fvg_transitions,
        "fvg_counts_by_timeframe": fvg_counts,
        "other_group6_boundary_state_distributions": boundary_states,
        "group6_boundary_counts_by_type_timeframe": boundary_counts,
        "observations": {
            "diagnostic_only": True,
            "engine_changed": False,
            "definitions_changed": False,
            "thresholds_changed": False,
            "schema_changed": False,
            "upstream_changed": False,
            "authorization_changed": False,
            "oos_2024_accessed": False,
            "no_lifecycle_semantics_inferred_by_probe": True,
        },
    }
    report["report_hash"] = stable_hash(report)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if integrity == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
