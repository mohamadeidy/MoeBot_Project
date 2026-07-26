#!/usr/bin/env python3
"""Independent annual validation for MoeBot Group 8 v0.8.0 outputs.

This auditor is deliberately separate from the engine. It verifies frozen identities,
SQLite/schema integrity, causal availability, duplicate prevention, lifecycle closure,
output prohibitions, evidence-chain subject/source integrity, and annual distributions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

FORBIDDEN = {
    "buy", "sell", "wait", "exit", "entry", "stop_loss", "take_profit",
    "position_size", "lot_size", "leverage", "pnl", "mfe", "mae",
    "future_return", "profit_factor", "expectancy", "sharpe", "hit_rate",
    "preferred_school", "preferred_setup", "setup_grade", "trade_score",
}
GENERATED_TEXT_COLUMNS = {
    "price_action_pattern_candidate": ["reasons_json", "features_json"],
    "price_action_pattern_state": ["details_json"],
    "school_interpretation": ["evidence_strength_json", "upstream_refs_json", "reasons_json"],
    "narrative_hypothesis": ["evidence_strength_json", "upstream_refs_json", "reasons_json"],
    "hypothesis_lifecycle_event": ["details_json"],
    "invalidation_record": ["reasons_json", "details_json"],
    "shared_evidence": ["details_json"],
    "conflicting_evidence": ["details_json"],
    "multi_timeframe_context_relation": ["details_json"],
    "evidence_chain": ["details_json"],
}
SUBJECT_ID = {
    "price_action_pattern_candidate": "candidate_id",
    "school_interpretation": "interpretation_id",
    "narrative_hypothesis": "hypothesis_id",
}
GROUP8_SOURCE_ID = {
    "price_action_pattern_candidate": "candidate_id",
    "price_action_pattern_state": "state_event_id",
    "school_interpretation": "interpretation_id",
    "narrative_hypothesis": "hypothesis_id",
    "hypothesis_lifecycle_event": "lifecycle_event_id",
    "invalidation_record": "invalidation_id",
    "shared_evidence": "shared_evidence_id",
    "conflicting_evidence": "conflict_id",
    "multi_timeframe_context_relation": "relation_id",
    "evidence_chain": "evidence_chain_id",
}


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def schema_inventory(con: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for t in sorted(tables(con)):
        out[t] = [
            {"name": r[1], "type": (r[2] or "").upper(), "notnull": int(r[3]), "pk": int(r[5])}
            for r in con.execute(f"PRAGMA table_info({q(t)})")
        ]
    return out


def first_id_column(required: list[str]) -> str | None:
    if "id" in required:
        return "id"
    for c in required:
        if c.endswith("_id") and not c.endswith("bar_id") and not c.startswith(("source_", "parent_", "associated_", "nearest_", "selected_", "protected_", "last_", "group2_", "group3_")):
            return c
    for c in required:
        if c.endswith("_id"):
            return c
    return None


def exists(con: sqlite3.Connection, table: str, col: str, value: str) -> bool:
    return con.execute(f"SELECT 1 FROM {q(table)} WHERE {q(col)}=? LIMIT 1", (value,)).fetchone() is not None


def distribution(con: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {str(k): int(n) for k, n in con.execute(f"SELECT {q(column)},COUNT(*) FROM {q(table)} GROUP BY {q(column)} ORDER BY {q(column)}")}


def validate(args: argparse.Namespace) -> dict[str, Any]:
    root = args.group8_root.resolve()
    status = json.loads((root / "STATUS.json").read_text())
    build = json.loads((root / "ENGINE_BUILD_MANIFEST.json").read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    definitions = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text())
    adapter = json.loads((root / "UPSTREAM_ADAPTER_MAP.json").read_text())
    material = json.loads(args.materializer_report.read_text())
    engine_audit = json.loads(args.engine_audit.read_text())
    failures: list[str] = []

    if build.get("status") != "TECHNICAL_CANDIDATE_PASS": failures.append("engine_build_manifest_not_pass")
    if status.get("engine_build", {}).get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("status_engine_manifest_hash_mismatch")
    if status.get("config_id") != build.get("config_id") or status.get("config_id") != freeze.get("config_id"): failures.append("config_identity_mismatch")
    if status.get("design_frozen") is not True or freeze.get("status") != "FROZEN": failures.append("design_not_frozen")
    if int(args.year) == 2023:
        if status.get("annual_execution_2023_authorized") is not True: failures.append("2023_not_authorized")
        if status.get("annual_execution_2024_authorized") is not False: failures.append("2024_prematurely_authorized")
    elif int(args.year) == 2024:
        if status.get("annual_execution_2024_authorized") is not True: failures.append("2024_oos_not_authorized")
        oos = root / "OOS_FREEZE_MANIFEST.json"
        if not oos.is_file(): failures.append("missing_oos_freeze_manifest")
        else:
            od = json.loads(oos.read_text())
            if od.get("status") != "FROZEN_FOR_2024_OOS" or od.get("engine_build_manifest_hash") != build.get("manifest_hash") or od.get("config_id") != build.get("config_id"):
                failures.append("oos_freeze_identity_mismatch")
    else:
        failures.append("unsupported_year")

    for name, ident in build.get("identities", {}).items():
        p = root / ident["path"]
        if not p.is_file(): failures.append(f"missing_identity:{name}:{ident['path']}"); continue
        if p.stat().st_size != int(ident["size_bytes"]): failures.append(f"identity_size:{name}")
        if shaf(p) != ident["sha256"]: failures.append(f"identity_sha256:{name}")

    if material.get("status") != "PASS" or int(material.get("year", 0)) != int(args.year): failures.append("materializer_report_not_pass")
    if material.get("config_id") != build.get("config_id") or material.get("engine_version") != build.get("engine_version") or material.get("schema_version") != build.get("schema_version"): failures.append("materializer_frozen_identity_mismatch")
    if engine_audit.get("status") != "PASS" or int(engine_audit.get("year", 0)) != int(args.year): failures.append("engine_audit_not_pass")
    if engine_audit.get("config_id") != build.get("config_id"): failures.append("engine_audit_config_mismatch")

    stage = sqlite3.connect(f"file:{args.staging_db.resolve()}?mode=ro&immutable=1", uri=True); stage.row_factory = sqlite3.Row
    out = sqlite3.connect(f"file:{args.output_db.resolve()}?mode=ro", uri=True); out.row_factory = sqlite3.Row
    try:
        for label, con in (("staging", stage), ("output", out)):
            qc = con.execute("PRAGMA quick_check").fetchone()[0]
            ic = con.execute("PRAGMA integrity_check").fetchone()[0]
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if qc != "ok": failures.append(f"{label}_quick_check:{qc}")
            if ic != "ok": failures.append(f"{label}_integrity_check:{ic}")
            if fk: failures.append(f"{label}_foreign_key_errors:{len(fk)}")

        stage_manifest = {r["key"]: r["value"] for r in stage.execute("SELECT key,value FROM stage_manifest")}
        expected_stage = {
            "status": "PASS", "year": str(args.year), "engine_version": build["engine_version"],
            "schema_version": build["schema_version"], "config_id": build["config_id"],
            "logical_dependency_lineage_id": status["logical_dependency_lineage_id"], "adapter_map_hash": status["adapter_map_hash"],
        }
        for k, v in expected_stage.items():
            if stage_manifest.get(k) != str(v): failures.append(f"stage_manifest:{k}:{stage_manifest.get(k)}!={v}")

        expected_schema = sqlite3.connect(":memory:")
        try:
            expected_schema.executescript((root / "02_SCHEMA.sql").read_text())
            if schema_inventory(expected_schema) != schema_inventory(out): failures.append("output_schema_inventory_mismatch")
        finally:
            expected_schema.close()

        metadata = {r["key"]: r["value"] for r in out.execute("SELECT key,value FROM metadata")}
        for k, v in {"engine_version": build["engine_version"], "schema_version": build["schema_version"], "config_id": build["config_id"], "design_freeze_hash": build["design_freeze_hash"], "year": str(args.year)}.items():
            if metadata.get(k) != str(v): failures.append(f"output_metadata:{k}:{metadata.get(k)}!={v}")
        if metadata.get("engine_audit_hash") != engine_audit.get("report_hash"): failures.append("output_engine_audit_hash_mismatch")

        causal = {
            "price_action_pattern_candidate": "availability_time<confirmation_time OR confirmation_time<event_time",
            "school_interpretation": "availability_time<confirmation_time OR confirmation_time<event_time",
            "narrative_hypothesis": "availability_time<confirmation_time OR confirmation_time<event_time",
            "invalidation_record": "availability_time<confirmation_time OR confirmation_time<event_time",
            "price_action_pattern_state": "availability_time<event_time",
            "hypothesis_lifecycle_event": "availability_time<event_time",
            "conflicting_evidence": "availability_time<event_time",
            "multi_timeframe_context_relation": "availability_time<event_time",
            "evidence_chain": "event_time IS NOT NULL AND availability_time<event_time",
        }
        causal_errors: dict[str, int] = {}
        for t, where in causal.items():
            n = int(out.execute(f"SELECT COUNT(*) FROM {q(t)} WHERE {where}").fetchone()[0])
            causal_errors[t] = n
            if n: failures.append(f"causality:{t}:{n}")

        before_creation = int(out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0])
        if before_creation: failures.append(f"lifecycle_before_creation:{before_creation}")
        terminal = int(out.execute("SELECT COUNT(DISTINCT hypothesis_id) FROM hypothesis_lifecycle_event WHERE lifecycle_state IN ('invalidated','completed_descriptive','right_censored')").fetchone()[0])
        hypotheses = int(out.execute("SELECT COUNT(*) FROM narrative_hypothesis").fetchone()[0])
        initial = int(out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event WHERE lifecycle_ordinal=0").fetchone()[0])
        if terminal != hypotheses: failures.append(f"terminal_lifecycle:{terminal}!={hypotheses}")
        if initial != hypotheses: failures.append(f"initial_lifecycle:{initial}!={hypotheses}")
        audit_dupes = out.execute("SELECT check_name,scope,checked_at,COUNT(*) n FROM group8_audit_evidence GROUP BY check_name,scope,checked_at HAVING n>1").fetchall()
        if audit_dupes: failures.append(f"duplicate_audit_evidence_keys:{len(audit_dupes)}")
        checkpoint_bad = int(out.execute("SELECT COUNT(*) FROM processing_checkpoint WHERE status!='PASS' OR snapshot_hash IS NULL OR snapshot_hash='' ").fetchone()[0])
        if checkpoint_bad: failures.append(f"invalid_checkpoints:{checkpoint_bad}")

        frozen_defs = set(definitions.get("definitions", {}))
        for t in ("price_action_pattern_candidate", "school_interpretation", "narrative_hypothesis"):
            unknown = [r[0] for r in out.execute(f"SELECT DISTINCT definition_id FROM {q(t)}") if r[0] not in frozen_defs]
            if unknown: failures.append(f"unknown_definition:{t}:{unknown[:20]}")

        future_evidence = 0
        for subject_type, idc in SUBJECT_ID.items():
            future_evidence += int(out.execute(
                f"SELECT COUNT(*) FROM evidence_chain e JOIN {q(subject_type)} s ON s.{q(idc)}=e.subject_id WHERE e.subject_type=? AND e.availability_time>s.availability_time",
                (subject_type,),
            ).fetchone()[0])
        if future_evidence: failures.append(f"evidence_after_subject_availability:{future_evidence}")

        missing_subjects = 0
        for subject_type, idc in SUBJECT_ID.items():
            missing_subjects += int(out.execute(
                f"SELECT COUNT(*) FROM evidence_chain e LEFT JOIN {q(subject_type)} s ON s.{q(idc)}=e.subject_id WHERE e.subject_type=? AND s.{q(idc)} IS NULL",
                (subject_type,),
            ).fetchone()[0])
        if missing_subjects: failures.append(f"evidence_missing_subjects:{missing_subjects}")

        unresolved_group8 = 0
        unresolved_upstream = 0
        unknown_source_types: list[str] = []
        refs = out.execute("SELECT DISTINCT source_group,source_type,source_id FROM evidence_chain ORDER BY source_group,source_type,source_id").fetchall()
        for ref in refs:
            g, typ, sid = str(ref["source_group"]), str(ref["source_type"]), str(ref["source_id"])
            if g == "group8":
                idc = GROUP8_SOURCE_ID.get(typ)
                if idc is None or typ not in tables(out) or not exists(out, typ, idc, sid): unresolved_group8 += 1
                continue
            rec = adapter.get("adapters", {}).get(g, {}).get(typ)
            table = f"{g}__{typ}"
            if rec is None or table not in tables(stage):
                unknown_source_types.append(f"{g}:{typ}"); continue
            idc = first_id_column(list(rec.get("required_columns", [])))
            if idc is None or not exists(stage, table, idc, sid): unresolved_upstream += 1
        if unknown_source_types: failures.append(f"unknown_upstream_source_types:{sorted(set(unknown_source_types))[:20]}")
        if unresolved_group8: failures.append(f"unresolved_group8_refs:{unresolved_group8}")
        if unresolved_upstream: failures.append(f"unresolved_upstream_refs:{unresolved_upstream}")

        prohibited_hits: list[str] = []
        for t, cols in GENERATED_TEXT_COLUMNS.items():
            for col in cols:
                for rowid, value in out.execute(f"SELECT rowid,{q(col)} FROM {q(t)}"):
                    hit = sorted(set(re.findall(r"[a-z_]+", str(value).lower())) & FORBIDDEN)
                    if hit:
                        prohibited_hits.append(f"{t}:{rowid}:{col}:{hit}")
                        if len(prohibited_hits) >= 20: break
                if len(prohibited_hits) >= 20: break
            if len(prohibited_hits) >= 20: break
        if prohibited_hits: failures.append(f"prohibited_generated_values:{prohibited_hits}")

        counts = {t: int(out.execute(f"SELECT COUNT(*) FROM {q(t)}").fetchone()[0]) for t in sorted(tables(out))}
        distributions = {
            "patterns_by_definition": distribution(out, "price_action_pattern_candidate", "definition_id"),
            "interpretations_by_definition": distribution(out, "school_interpretation", "definition_id"),
            "hypotheses_by_definition": distribution(out, "narrative_hypothesis", "definition_id"),
            "interpretations_by_school": distribution(out, "school_interpretation", "school_id"),
            "hypotheses_by_school": distribution(out, "narrative_hypothesis", "school_id"),
            "hypothesis_terminal_states": distribution(out, "hypothesis_lifecycle_event", "lifecycle_state"),
            "patterns_by_timeframe": distribution(out, "price_action_pattern_candidate", "timeframe"),
        }
    finally:
        stage.close(); out.close()

    report = {
        "format_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "phase": "ANNUAL_VALIDATION",
        "year": int(args.year),
        "engine_version": build.get("engine_version"),
        "schema_version": build.get("schema_version"),
        "config_id": build.get("config_id"),
        "engine_build_manifest_hash": build.get("manifest_hash"),
        "engine_sha256": build.get("identities", {}).get("engine", {}).get("sha256"),
        "postprocessor_sha256": build.get("identities", {}).get("postprocessor", {}).get("sha256"),
        "materializer_report_hash": material.get("report_hash"),
        "engine_audit_hash": engine_audit.get("report_hash"),
        "causality_errors": causal_errors,
        "upstream_reference_integrity": {"unresolved_group8": unresolved_group8, "unresolved_upstream": unresolved_upstream, "unknown_source_types": sorted(set(unknown_source_types))},
        "lifecycle": {"hypotheses": hypotheses, "initial": initial, "terminal": terminal, "before_creation": before_creation},
        "counts": counts,
        "distributions": distributions,
        "no_trading_outputs": not prohibited_hits,
        "read_only_upstream": True,
        "failures": failures,
    }
    report["report_hash"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--materializer-report", type=Path, required=True)
    p.add_argument("--engine-audit", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = validate(a)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "year": report["year"], "report_hash": report["report_hash"], "failures": report["failures"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
