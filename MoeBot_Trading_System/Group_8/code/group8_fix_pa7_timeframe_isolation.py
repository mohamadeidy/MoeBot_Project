#!/usr/bin/env python3
"""Fail-closed minimal correction for G8-PA7-CROSS-TIMEFRAME-006.

The frozen Design Lock requires every timeframe to run independently before
cross-timeframe relations are created. The frozen engine already enforces this
for Group4, Group5 and Group7 breakout boundaries, but the Group6 branch of
_boundary_rows_for_bar omitted the timeframe predicate and therefore mixed
D1/H1/H4/M1/M5/M15/M30 objects inside PA7 creation.

This correction changes only that missing predicate. Definitions, thresholds,
schema, upstream data and config remain frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-CROSS-TIMEFRAME-006"
PREVIOUS_ENGINE_SHA256 = "61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
DESIGN_RULE = "Run every timeframe independently before creating cross-timeframe relations."

OLD = 'for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE {avc}<=?", (bar.available_at,)): yield {"group":"group6","type":t,"id":r["id"],"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"])}'
NEW = 'for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=? AND {avc}<=?", (bar.timeframe, bar.available_at,)): yield {"group":"group6","type":t,"id":r["id"],"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"])}'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_hashed(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["report_hash"] = stable_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()
    engine_path = root / "code" / "moebot_group8_engine_v0_8_0.py"
    status_path = root / "STATUS.json"
    design_path = root / "00_DESIGN_LOCK.md"
    cats_path = root / "UPSTREAM_CATEGORICAL_DICTIONARY.json"

    if sha256_file(engine_path) != PREVIOUS_ENGINE_SHA256:
        raise SystemExit("unexpected pre-fix engine identity")
    design = design_path.read_text()
    if DESIGN_RULE not in design:
        raise SystemExit("frozen timeframe-independence rule missing")

    text = engine_path.read_text()
    if text.count(OLD) != 1:
        raise SystemExit(f"authoritative Group6 breakout query count={text.count(OLD)}")
    if NEW in text:
        raise SystemExit("timeframe fix already present unexpectedly")

    cats = json.loads(cats_path.read_text())
    g6 = cats["cross_year"]["group6"]
    measured_tables = ["fvg_events", "imbalance_variants", "liquidity_voids", "bpr_relations"]
    timeframes = {table: list(g6[table]["timeframe"]["2023"]) for table in measured_tables}
    if any(len(set(values)) <= 1 for values in timeframes.values()):
        raise SystemExit("Group6 multi-timeframe evidence unexpectedly absent")

    diagnostic = write_hashed(root / "reports" / "32_BREAKOUT_TIMEFRAME_GAP_DIAGNOSTIC.json", {
        "format_version": 1,
        "status": "FAIL_BLOCKING_GAP_CONFIRMED",
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "phase": "ANNUAL_2023_ROOT_CAUSE",
        "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
        "design_rule": DESIGN_RULE,
        "design_rule_present": True,
        "group6_breakout_query_missing_timeframe_predicate": True,
        "group6_source_timeframes_2023": timeframes,
        "group4_group5_group7_same_timeframe_guards_present": all(marker in text for marker in [
            "group4__zones WHERE symbol=? AND timeframe=?",
            "group5__liquidity_pools WHERE symbol=? AND timeframe=?",
            "group7__institutional_zones WHERE timeframe=?",
        ]),
        "cross_timeframe_boundary_mixing_possible": True,
        "mtf_relation_layer_bypassed": True,
        "definitions_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "upstream_changed": False,
    })

    engine_path.write_text(text.replace(OLD, NEW, 1))
    corrected_sha = sha256_file(engine_path)
    if corrected_sha == PREVIOUS_ENGINE_SHA256:
        raise SystemExit("engine identity did not change")
    corrected_text = engine_path.read_text()
    if OLD in corrected_text or corrected_text.count(NEW) != 1:
        raise SystemExit("minimal timeframe patch verification failed")

    gap = write_hashed(root / "reports" / "33_BREAKOUT_TIMEFRAME_GAP_ANALYSIS.json", {
        "format_version": 1,
        "status": "BLOCKING_GAP_FIXED_PENDING_TECHNICAL_REFREEZE",
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "diagnostic_report_hash": diagnostic["report_hash"],
        "root_cause": "Group6 breakout-boundary enumeration omitted the current bar timeframe predicate, violating the frozen rule that every timeframe runs independently before MTF relations.",
        "minimal_correct_fix": "Require group6 boundary row timeframe == current bar.timeframe inside _boundary_rows_for_bar; no other evaluator semantics changed.",
        "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
        "corrected_engine_sha256": corrected_sha,
        "definitions_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "upstream_changed": False,
        "config_changed": False,
        "2024_accessed": False,
        "required_regression": "test_group8_breakout_timeframe_isolation_v0_8_0.py",
    })

    status = json.loads(status_path.read_text())
    if status.get("officially_closed") is not False or status.get("design_frozen") is not True:
        raise SystemExit("unexpected Group8 status phase")
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["engine_build_authorized"] = False
    status["blocking_gap"] = {
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "status": "FIXED_PENDING_REFREEZE",
        "diagnostic_report_hash": diagnostic["report_hash"],
        "gap_analysis_report_hash": gap["report_hash"],
        "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
        "corrected_engine_sha256": corrected_sha,
        "definitions_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "upstream_changed": False,
        "config_changed": False,
        "previous_closed_gap_id": "G8-ICT-LOCKED-CONTEXT-005",
    }
    status.setdefault("engine_build", {})["status"] = "STALE_PENDING_TECHNICAL_REFREEZE"
    status["status"] = "BLOCKING_GAP_G8_PA7_CROSS_TIMEFRAME_FIXED_PENDING_TECHNICAL_REFREEZE"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "status": "PASS",
        "gap_id": GAP_ID,
        "diagnostic_report_hash": diagnostic["report_hash"],
        "gap_analysis_report_hash": gap["report_hash"],
        "previous_engine_sha256": PREVIOUS_ENGINE_SHA256,
        "corrected_engine_sha256": corrected_sha,
        "2023_authorized": False,
        "2024_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
