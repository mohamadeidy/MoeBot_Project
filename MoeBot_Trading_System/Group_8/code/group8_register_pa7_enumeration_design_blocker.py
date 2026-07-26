#!/usr/bin/env python3
"""Register the frozen PA7 annual-cardinality contradiction as a blocking design gap.

No frozen definition is changed here. This tool only binds the post-fix exact
2023 workload evidence to the frozen PA7 enumeration rule and revokes annual
execution until an explicit design decision is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-ENUMERATION-EXPLOSION-007"
EXPECTED_ENGINE_SHA256 = "f77252cc07c5d4e2fe6481a811441674983ec4d00c36c0c07f618950a4f4877d"
EXPECTED_WORKLOAD_REPORT_HASH = "6308c8b0e614fd81bc73f64fbc86f037cdd9ff5dc28696bfe3111997db031dbc"
ENUMERATION_RULE = "one record per qualifying (bar_id,boundary_source_id,boundary_side); all boundaries are evaluated independently"


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def report_hash_valid(record: dict[str, Any]) -> bool:
    payload = dict(record)
    actual = payload.pop("report_hash", None)
    return actual == stable_hash(payload)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()

    engine_path = root / "code" / "moebot_group8_engine_v0_8_0.py"
    status_path = root / "STATUS.json"
    workload_path = root / "reports" / "35_POSTFIX_BREAKOUT_CARDINALITY_DIAGNOSTIC.json"
    defs = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text())
    workload = json.loads(workload_path.read_text())
    status = json.loads(status_path.read_text())

    if shaf(engine_path) != EXPECTED_ENGINE_SHA256:
        raise SystemExit("unexpected corrected engine identity")
    if workload.get("report_hash") != EXPECTED_WORKLOAD_REPORT_HASH or not report_hash_valid(workload) or workload.get("status") != "PASS":
        raise SystemExit("post-fix workload evidence identity invalid")
    pa7 = defs.get("definitions", {}).get("pa_breakout_exact", {})
    if pa7.get("enumeration_rule") != ENUMERATION_RULE or pa7.get("version") != "PA7E.1":
        raise SystemExit("frozen PA7 exact enumeration contract changed unexpectedly")
    for variant in ("pa_breakout_atr_buffer", "pa_breakout_point_buffer"):
        if defs.get("definitions", {}).get(variant, {}).get("enumeration_rule") != "same independent boundary enumeration as pa_breakout_exact":
            raise SystemExit(f"frozen PA7 variant enumeration contract changed:{variant}")
    if status.get("design_frozen") is not True or status.get("officially_closed") is not False:
        raise SystemExit("invalid Group 8 phase")
    if status.get("engine_build", {}).get("engine_sha256") != EXPECTED_ENGINE_SHA256 or status.get("engine_build", {}).get("status") != "TECHNICAL_CANDIDATE_PASS":
        raise SystemExit("expected re-frozen corrected technical candidate missing")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("unexpected pre-blocker annual authorization state")

    lower = workload["minimum_group6_plus_group8_workload"]
    candidates = int(lower["candidate_total"])
    enumerations = int(lower["enumerations"])
    bars = int(workload["bar_count"])
    if candidates != 74600565353 or enumerations != 37433977616:
        raise SystemExit("exact measured workload changed from audited evidence")

    gap: dict[str, Any] = {
        "format_version": 1,
        "status": "OPEN_DESIGN_DECISION_REQUIRED",
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "phase": "ANNUAL_2023_PRE_EXECUTION_GAP_ANALYSIS",
        "classification": "FROZEN_DESIGN_CARDINALITY_CONTRADICTION",
        "engine_sha256": EXPECTED_ENGINE_SHA256,
        "workload_report_hash": workload["report_hash"],
        "frozen_definition_registry_hash": defs.get("definition_registry_hash"),
        "frozen_pa7_exact_version": pa7.get("version"),
        "frozen_pa7_enumeration_rule": ENUMERATION_RULE,
        "frozen_variant_enumeration_binding": "pa_breakout_atr_buffer and pa_breakout_point_buffer use the same independent boundary enumeration",
        "exact_2023_lower_bound": {
            "bars": bars,
            "group6_plus_group8_boundary_enumerations": enumerations,
            "group6_plus_group8_candidate_records": candidates,
            "candidate_records_per_bar_average": candidates / bars,
            "minimum_candidate_plus_creation_state_rows": candidates * 2,
            "excluded_from_lower_bound": ["group4", "group5", "group7"],
        },
        "root_cause": "The frozen PA7 contract requires a distinct immutable record for every qualifying bar x boundary-source x side, and both ATR/point variants inherit that independent enumeration. On exact 2023 data, even after correcting cross-timeframe leakage, Group6+Group8 alone imply 74,600,565,353 candidate records before Group4/5/7. The engine also persists a creation lifecycle state for every pattern candidate, so the physical row lower bound is at least twice the candidate count before other outputs.",
        "why_execution_optimization_is_insufficient": "SQL/index/loop optimization can reduce CPU spent discovering qualifying pairs but cannot remove or aggregate records required by the frozen one-record-per-qualifying-pair contract. Materializing the measured logical output is itself the blocker.",
        "minimal_correct_fix_available_without_design_change": False,
        "design_change_required": True,
        "decision_required": True,
        "non_selected_design_paths": [
            {
                "id": "PA7_TRANSITION_EVENT_ENUMERATION",
                "effect": "Define breakout as a transition event (for example first causal close-through per locked boundary/direction until a frozen reset condition) instead of every bar remaining beyond the boundary.",
                "changes_frozen_contract": True,
            },
            {
                "id": "PA7_EXPLICIT_TIMEFRAME_SCOPE",
                "effect": "Freeze an explicit subset of Group 8 execution timeframes instead of consuming every source timeframe available in the annual lineage.",
                "changes_frozen_contract": True,
            },
            {
                "id": "PA7_ACTIVE_LIFECYCLE_BOUNDARIES_ONLY",
                "effect": "Require boundary eligibility to end at a frozen upstream/derived lifecycle invalidation rather than allowing every causally available historical boundary indefinitely.",
                "changes_frozen_contract": True,
            },
            {
                "id": "PA7_COMPRESSED_LOGICAL_REPRESENTATION",
                "effect": "Keep the logical bar-boundary enumeration but replace one-row-per-candidate materialization with a new compressed/virtual storage and validation contract.",
                "changes_frozen_contract": True,
            },
        ],
        "forbidden_shortcuts": [
            "silently drop qualifying records",
            "lower validation quality",
            "change thresholds to reduce count",
            "use 2024 OOS to choose a reduction rule",
            "collapse IDs or deduplicate distinct bar-boundary candidates contrary to PA7E.1",
        ],
        "definitions_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "config_changed": False,
        "upstream_changed": False,
        "engine_changed": False,
        "oos_2024_accessed": False,
    }
    gap["report_hash"] = stable_hash(gap)
    gap_path = root / "reports" / "36_PA7_ENUMERATION_DESIGN_BLOCKER.json"
    gap_path.write_text(json.dumps(gap, indent=2, sort_keys=True) + "\n")

    previous = status.get("blocking_gap", {})
    if previous.get("gap_id") != "G8-PA7-CROSS-TIMEFRAME-006" or previous.get("status") != "CLOSED_BY_TECHNICAL_REFREEZE":
        raise SystemExit("previous closed gap lineage not in expected state")
    status["blocking_gap"] = {
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "status": "OPEN_DESIGN_DECISION_REQUIRED",
        "classification": "FROZEN_DESIGN_CARDINALITY_CONTRADICTION",
        "report_hash": gap["report_hash"],
        "workload_report_hash": workload["report_hash"],
        "engine_sha256": EXPECTED_ENGINE_SHA256,
        "previous_closed_gap_id": "G8-PA7-CROSS-TIMEFRAME-006",
        "design_change_required": True,
        "decision_required": True,
    }
    status["engine_build_authorized"] = False
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status.setdefault("engine_build", {})["status"] = "TECHNICAL_CANDIDATE_BLOCKED_BY_DESIGN_GAP"
    status["status"] = "BLOCKING_DESIGN_GAP_G8_PA7_ENUMERATION_007_DECISION_REQUIRED"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "status": gap["status"],
        "gap_id": GAP_ID,
        "report_hash": gap["report_hash"],
        "candidate_lower_bound": candidates,
        "minimum_candidate_plus_creation_state_rows": candidates * 2,
        "2023_authorized": False,
        "2024_authorized": False,
        "officially_closed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
