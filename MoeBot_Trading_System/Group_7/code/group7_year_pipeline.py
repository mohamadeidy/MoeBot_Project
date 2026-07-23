#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from group7_independent_audit import run as independent_audit
from group7_real_visual_audit import run as visual_audit
from moebot_group7_engine import BASE_DEFINITIONS, DEFINITIONS, ENGINE_VERSION, SCHEMA_VERSION, build, file_sha256

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = json.loads((ROOT / "ANNUAL_DEPENDENCY_REQUIREMENTS.json").read_text(encoding="utf-8"))


def require(path: Path, expected: Dict[str, Any]) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size != int(expected["size_bytes"]):
        raise ValueError(f"Unexpected size for {path}: {size} != {expected['size_bytes']}")
    digest = file_sha256(path)
    if digest != expected["sha256"]:
        raise ValueError(f"Unexpected SHA-256 for {path}: {digest} != {expected['sha256']}")
    return {"filename": path.name, "path": str(path.resolve()), "size_bytes": size, "sha256": digest}


def summarize(db: Path) -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    by_definition = {
        r["definition_id"]: {
            "evaluations": r["evaluations"],
            "passed_evaluations": r["passed_evaluations"],
            "zones": r["zones"],
            "fresh": r["fresh"],
            "tested": r["tested"],
            "invalidated": r["invalidated"],
        }
        for r in con.execute("""
            WITH e AS (
              SELECT definition_id,COUNT(*) evaluations,SUM(passed=1) passed_evaluations
              FROM block_evaluations GROUP BY definition_id
            ), z AS (
              SELECT z.definition_id,COUNT(*) zones,
                     SUM(s.freshness='fresh') fresh,SUM(s.freshness='tested') tested,
                     SUM(s.freshness='invalidated') invalidated
              FROM institutional_zones z JOIN zone_lifecycle_summary s USING(zone_id)
              GROUP BY z.definition_id
            )
            SELECT d.definition_id,COALESCE(e.evaluations,0) evaluations,
                   COALESCE(e.passed_evaluations,0) passed_evaluations,
                   COALESCE(z.zones,0) zones,COALESCE(z.fresh,0) fresh,
                   COALESCE(z.tested,0) tested,COALESCE(z.invalidated,0) invalidated
            FROM definition_registry d LEFT JOIN e USING(definition_id) LEFT JOIN z USING(definition_id)
            ORDER BY d.definition_id
        """)
    }
    checks = {
        "candidate_cardinality_errors": con.execute("SELECT COUNT(*) FROM (SELECT source_leg_id,COUNT(*) n FROM definition_candidates GROUP BY source_leg_id HAVING n!=?)", (len(BASE_DEFINITIONS),)).fetchone()[0],
        "match_before_candidate": con.execute("SELECT COUNT(*) FROM definition_matches m JOIN definition_candidates c USING(candidate_id) WHERE m.availability_time<c.availability_time").fetchone()[0],
        "match_before_evidence": con.execute("SELECT COUNT(*) FROM definition_matches WHERE availability_time<evidence_availability_max").fetchone()[0],
        "zone_before_match": con.execute("SELECT COUNT(*) FROM institutional_zones z JOIN definition_matches m USING(match_id) WHERE z.availability_time<m.availability_time").fetchone()[0],
        "base_zone_without_match": con.execute("SELECT COUNT(*) FROM institutional_zones WHERE definition_id IN (%s) AND match_id IS NULL" % ",".join("?" for _ in BASE_DEFINITIONS), BASE_DEFINITIONS).fetchone()[0],
        "evidence_before_zone": con.execute("SELECT COUNT(*) FROM zone_evidence e JOIN institutional_zones z USING(zone_id) WHERE e.availability_time<z.availability_time").fetchone()[0],
        "transition_before_zone": con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE t.transition_time<z.availability_time").fetchone()[0],
        "missing_lifecycle_summary": con.execute("SELECT COUNT(*) FROM institutional_zones z LEFT JOIN zone_lifecycle_summary s USING(zone_id) WHERE s.zone_id IS NULL").fetchone()[0],
        "non_read_only_dependency": con.execute("SELECT COUNT(*) FROM dependency_registry WHERE read_only!=1").fetchone()[0],
    }
    result = {
        "engine_version": con.execute("SELECT value FROM metadata WHERE key='engine_version'").fetchone()[0],
        "schema_version": con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],
        "config_id": con.execute("SELECT value FROM metadata WHERE key='config_id'").fetchone()[0],
        "dataset_id": con.execute("SELECT value FROM metadata WHERE key='dataset_id'").fetchone()[0],
        "candidates": con.execute("SELECT COUNT(*) FROM definition_candidates").fetchone()[0],
        "matches": con.execute("SELECT COUNT(*) FROM definition_matches").fetchone()[0],
        "evaluations": con.execute("SELECT COUNT(*) FROM block_evaluations").fetchone()[0],
        "zones": con.execute("SELECT COUNT(*) FROM institutional_zones").fetchone()[0],
        "transitions": con.execute("SELECT COUNT(*) FROM zone_state_transitions").fetchone()[0],
        "visits": con.execute("SELECT COUNT(*) FROM zone_visit_observations").fetchone()[0],
        "by_definition": by_definition,
        "causality_checks": checks,
        "sqlite_quick_check": con.execute("PRAGMA quick_check").fetchone()[0],
        "sqlite_integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_errors": len(con.execute("PRAGMA foreign_key_check").fetchall()),
    }
    con.close()
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Run one frozen Group 7 annual validation year")
    p.add_argument("--year", required=True, choices=("2023", "2024"))
    p.add_argument("--source", required=True)
    p.add_argument("--group6", required=True)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()
    year = args.year
    source = Path(args.source)
    group6 = Path(args.group6)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    db = outdir / f"MoeBot_Group7_XAUUSD_{year}_v0.7.5_rebuilt_dukascopy_v1.sqlite"
    started = time.time()
    verified = {
        "source": require(source, REQUIRED[year]["source"]),
        "group6": require(group6, REQUIRED[year]["group6"]),
    }
    first = build(source, group6, db, recreate=True)
    second = build(source, group6, db, recreate=False)
    reimport_nonzero = {k: v for k, v in second["inserted"].items() if v != 0}
    audit = independent_audit(db, write_audit=True, source_override=source, group6_override=group6)
    summary = summarize(db)
    visual_dir = outdir / f"visual_audit_{year}"
    visual = visual_audit(source, group6, db, visual_dir)
    gates = {
        "engine_version": summary["engine_version"] == ENGINE_VERSION,
        "schema_version": summary["schema_version"] == SCHEMA_VERSION,
        "first_build_integrity": first["integrity"] == "ok" and first["foreign_key_errors"] == 0,
        "idempotent_reimport": not reimport_nonzero,
        "independent_audit": bool(audit["passed"]),
        "summary_sqlite": summary["sqlite_quick_check"] == "ok" and summary["sqlite_integrity_check"] == "ok" and summary["foreign_key_errors"] == 0,
        "causality_zero_errors": all(v == 0 for v in summary["causality_checks"].values()),
        "all_definitions_registered": set(summary["by_definition"]) == set(DEFINITIONS),
        "all_definitions_nonempty": all(v["zones"] > 0 for v in summary["by_definition"].values()),
        "base_candidates_present": summary["candidates"] > 0,
        "causal_matches_present": summary["matches"] > 0,
        "real_visual_audit": bool(visual["passed"]),
    }
    result = {
        "format_version": 1,
        "year": int(year),
        "lineage": REQUIRED["lineage"],
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "verified_dependencies": verified,
        "database": {
            "filename": db.name,
            "path": str(db.resolve()),
            "size_bytes": db.stat().st_size,
            "sha256": file_sha256(db),
        },
        "first_build": first,
        "reimport_nonzero": reimport_nonzero,
        "independent_audit": audit,
        "summary": summary,
        "visual_audit": visual,
        "gates": gates,
        "passed": all(gates.values()),
        "elapsed_seconds": round(time.time() - started, 3),
        "holdout_policy": "2024 used the unchanged frozen v0.7.5 config and definitions; no result-driven threshold changes",
        "profitability_used": False,
    }
    json_path = outdir / f"GROUP7_YEAR_{year}.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = [
        f"# Group 7 v0.7.5 — {year} Annual Verification",
        "",
        f"- Verdict: **{'PASS' if result['passed'] else 'FAIL'}**",
        f"- Lineage: `{result['lineage']}`",
        f"- Database SHA-256: `{result['database']['sha256']}`",
        f"- Candidates: {summary['candidates']:,}",
        f"- Matches: {summary['matches']:,}",
        f"- Zones: {summary['zones']:,}",
        f"- Transitions: {summary['transitions']:,}",
        f"- Independent audit: {'PASS' if audit['passed'] else 'FAIL'}",
        f"- Idempotent re-import: {'PASS' if not reimport_nonzero else 'FAIL'}",
        f"- Causality errors: {sum(summary['causality_checks'].values())}",
        "",
        "No BUY/SELL/WAIT, entries, SL/TP, PnL, MFE, MAE, or future-return calibration was used.",
    ]
    (outdir / f"GROUP7_YEAR_{year}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
