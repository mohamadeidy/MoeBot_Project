#!/usr/bin/env python3
"""Build and validate the exact Group 8 upstream adapter map from real annual schemas."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED: dict[str, dict[str, list[str]]] = {
    "source": {
        "bars": ["id","symbol","timeframe","open_time","close_time","available_at","open","high","low","close","tick_volume","content_hash"],
    },
    "group2": {
        "regime_states": ["state_id","symbol","timeframe_code","open_time_server","close_time_server","decision_time_server","direction_code","volatility_code","phase_code","stable_label_code","confidence","uncertain","baseline_mature","source_bar_hash"],
        "timeframe_dictionary": ["timeframe_code","timeframe","seconds","parent_timeframe_code"],
    },
    "group3": {
        "structure_states": ["state_id","symbol","timeframe","bar_id","open_time","close_time","layer","sequence_bias","active_bias","leg","protected_high_id","protected_low_id","last_event_type","last_event_id","atr","state_hash"],
        "break_events": ["event_id","symbol","timeframe","layer","candidate_id","event_type","direction","break_kind","level_price","level_swing_id","candidate_time","resolved_time","candidate_bar_id","resolved_bar_id","strength_score","strong_break","outcome","feature_hash"],
        "swings": ["swing_id","symbol","timeframe","layer","swing_type","extreme_time","confirmation_time","available_at","price","atr","relation","source_bar_id","event_hash"],
    },
    "group4": {
        "zones": ["zone_id","symbol","timeframe","source_timeframe","zone_class","initial_role","current_role","layer","origin_time","available_at","expires_at","lower","upper","origin_atr","origin_strength","status","touch_count","max_penetration","current_strength","broken_direction","source_swing_id","source_event_id","source_bar_id","feature_hash"],
        "zone_interactions": ["interaction_id","zone_id","timeframe","bar_id","interaction_time","event_type","status_after","role_after","touch_count","penetration_ratio","arrival_speed","arrival_efficiency","confluence_count","current_strength","feature_hash"],
        "zone_transitions": ["transition_id","zone_id","bar_id","transition_time","from_status","to_status","role_after","reason","transition_hash"],
    },
    "group5": {
        "liquidity_pools": ["pool_id","symbol","timeframe","pool_class","side","layer","origin_time","available_at","expires_at","anchor_price","lower","upper","origin_atr","status","first_sweep_time","first_event_id","source_swing_id","source_zone_id","pool_hash"],
        "liquidity_events": ["event_id","pool_id","timeframe","side","event_type","candidate_time","resolved_time","start_bar_id","resolved_bar_id","duration_bars","depth_atr","reclaimed","same_bar","closed_beyond","is_sweep","is_liquidity_grab","is_stop_run","is_false_breakout","resolution","parent_event_id","event_hash"],
        "draw_states": ["draw_id","timeframe","bar_id","open_time","close_time","active_bias","draw_side","selected_pool_id","nearest_buy_pool_id","nearest_sell_pool_id","confidence","draw_hash"],
        "inducements": ["inducement_id","source_event_id","source_pool_id","target_pool_id","timeframe","direction","candidate_time","expires_time","status","resolved_time","resolution_event_id","inducement_hash"],
        "liquidity_voids": ["void_id","timeframe","direction","start_bar_id","end_bar_id","origin_time","available_at","expires_at","lower","upper","origin_atr","status","max_fill_ratio","void_hash"],
    },
    "group6": {
        "displacement_legs": ["leg_id","timeframe","leg_kind","direction","start_bar_id","end_bar_id","start_time","end_time","confirmation_time","availability_time","origin_bar_id","origin_window_start","origin_window_end","body_lower","body_upper","wick_lower","wick_upper","full_lower","full_upper","last_opposing_bar_id","origin_label","initial_classification","uncertain","record_hash"],
        "displacement_validation_events": ["validation_id","leg_id","fvg_id","confirmation_bar_id","confirmation_time","availability_time","validation_type","result","record_hash"],
        "fvg_events": ["fvg_id","timeframe","direction","creation_time","confirmation_time","availability_time","lower","upper","ce","size_atr","associated_leg_id","associated_group3_event_id","associated_group5_event_id","group2_state_id","group3_state_id","clean_displacement","formation_quality","record_hash"],
        "fvg_lifecycle_summary": ["fvg_id","fill_state","directional_validity","max_penetration","first_touch_time","ce_time","full_fill_time","traverse_time","visit_count","record_hash"],
        "fvg_state_transitions": ["transition_id","fvg_id","transition_ordinal","bar_id","transition_time","event_type","fill_state","directional_validity","max_penetration","record_hash"],
        "group6_evidence": ["evidence_id","subject_type","subject_id","source_group","source_id","relation_type","source_timeframe","availability_time","details_json","record_hash"],
        "imbalance_variants": ["variant_id","timeframe","variant_type","direction","start_bar_id","end_bar_id","availability_time","lower","upper","size_atr","classification","separation_reason","record_hash"],
        "inversion_fvg_relations": ["inversion_id","original_fvg_id","confirmation_bar_id","confirmation_time","availability_time","direction_before","direction_after","close_through_evidence","inversion_status","first_retest_time","first_retest_bar_id","record_hash"],
        "liquidity_voids": ["void_id","timeframe","direction","start_time","end_time","availability_time","lower","upper","width_atr","member_count","state","max_fill","record_hash"],
        "bpr_relations": ["bpr_id","bullish_fvg_id","bearish_fvg_id","timeframe","lower","upper","width","creation_time","availability_time","second_fvg_direction","group2_state_id","group3_state_id","state","max_consumption","record_hash"],
        "mtf_imbalance_relations": ["relation_id","child_type","child_id","child_timeframe","parent_type","parent_id","parent_timeframe","relation_type","direction_alignment","overlap_ratio","availability_time","record_hash"],
    },
    "group7": {
        "definition_registry": ["definition_id","definition_version","derived","range_policy","invalidation_closes","definition_json","definition_hash"],
        "definition_candidates": ["candidate_id","definition_id","source_leg_id","candidate_time","availability_time","lower","upper","source_bar_id","intrinsic_pass","candidate_hash"],
        "definition_matches": ["match_id","candidate_id","definition_id","source_leg_id","match_time","availability_time","evidence_availability_max","evidence_ids_json","match_hash"],
        "institutional_zones": ["zone_id","definition_id","timeframe","direction","zone_label","lower","upper","event_time","confirmation_time","availability_time","source_leg_id","candidate_id","match_id","origin_bar_id","source_bar_id","parent_zone_id","creation_hash"],
        "zone_evidence": ["evidence_id","zone_id","evidence_type","source_group","source_id","relation_type","availability_time","evidence_hash"],
        "zone_relations": ["relation_id","subject_zone_id","object_zone_id","relation_type","availability_time","overlap_ratio","relation_hash"],
        "zone_state_transitions": ["transition_id","zone_id","transition_ordinal","bar_id","transition_time","event_type","status","freshness","visit_count","mitigation_count","max_penetration","transition_hash"],
        "zone_lifecycle_summary": ["zone_id","status","freshness","visit_count","mitigation_count","max_penetration","first_touch_time","invalidated_time","summary_hash"],
    },
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def cols_from_g2g5(registry: dict[str, Any], year: str, group: str, table: str) -> list[str]:
    tables = registry["years"][year]["groups2_5_clean_room"]["groups"][group]["sqlite"]["tables"]
    if table not in tables:
        return []
    return [str(row["name"]) for row in tables[table]["columns"]]


def cols_from_real_schema(report: dict[str, Any], table: str) -> list[str]:
    tables = report["schema"]["tables"]
    if table not in tables:
        return []
    return [str(row["name"]) for row in tables[table]["columns"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--source-schema-2023", type=Path, required=True)
    ap.add_argument("--source-schema-2024", type=Path, required=True)
    ap.add_argument("--g6-schema-2023", type=Path, required=True)
    ap.add_argument("--g6-schema-2024", type=Path, required=True)
    ap.add_argument("--g7-schema-2023", type=Path, required=True)
    ap.add_argument("--g7-schema-2024", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    if registry.get("status") != "PASS":
        raise RuntimeError("annual upstream registry is not PASS")
    external = {
        "source": {"2023": json.loads(args.source_schema_2023.read_text()), "2024": json.loads(args.source_schema_2024.read_text())},
        "group6": {"2023": json.loads(args.g6_schema_2023.read_text()), "2024": json.loads(args.g6_schema_2024.read_text())},
        "group7": {"2023": json.loads(args.g7_schema_2023.read_text()), "2024": json.loads(args.g7_schema_2024.read_text())},
    }
    failures: list[str] = []
    adapters: dict[str, Any] = {}
    for group, tables in REQUIRED.items():
        adapters[group] = {}
        for table, required_cols in tables.items():
            actual_by_year: dict[str, list[str]] = {}
            for year in ("2023", "2024"):
                if group in ("group2", "group3", "group4", "group5"):
                    actual = cols_from_g2g5(registry, year, group, table)
                else:
                    actual = cols_from_real_schema(external[group][year], table)
                actual_by_year[year] = actual
                missing = sorted(set(required_cols) - set(actual))
                if missing:
                    failures.append(f"{group}:{table}:{year}:missing:{','.join(missing)}")
            common = sorted(set(actual_by_year["2023"]) & set(actual_by_year["2024"]))
            stable = all(col in common for col in required_cols)
            if not stable:
                failures.append(f"{group}:{table}:cross_year_schema_unstable")
            row = {
                "table": table,
                "required_columns": required_cols,
                "actual_columns_2023": actual_by_year["2023"],
                "actual_columns_2024": actual_by_year["2024"],
                "required_columns_cross_year_stable": stable,
            }
            row["adapter_hash"] = hashlib.sha256(canonical_json(row).encode()).hexdigest()
            adapters[group][table] = row

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "group": 8,
        "adapter_policy": "read-only exact table/column bindings verified against real annual SQLite schemas for both 2023 and 2024; no guessed identifiers",
        "annual_upstream_registry_hash": registry["registry_hash"],
        "group7_closure_tag": registry["group7_source_closure_tag"],
        "group7_closure_commit_sha": registry["group7_source_closure_commit_sha"],
        "adapters": adapters,
        "failures": failures,
    }
    report["adapter_map_hash"] = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "adapter_map_hash": report["adapter_map_hash"], "failures": failures[:20]}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
