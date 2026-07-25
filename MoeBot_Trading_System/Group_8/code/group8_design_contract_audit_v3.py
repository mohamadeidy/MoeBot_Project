#!/usr/bin/env python3
"""Independent fail-closed audit for coherent-only Group 8 design candidate v3."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ALLOWED_SCHOOLS = {"classical_price_action", "dow_theory", "wyckoff", "ict_smc"}
REQUIRED_TABLES = {
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
}
IMMUTABLE_TABLES = {
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
}
FORBIDDEN_SQL_COLUMNS = {
    "entry", "entry_price", "stop", "stop_loss", "take_profit", "target",
    "position_size", "lot", "risk", "pnl", "mfe", "mae", "future_return",
    "profitability", "expectancy", "sharpe", "profit_factor",
}
CONFIG_ALIASES = {
    "doji_strict_body_ratio": "pattern_thresholds.doji_strict_body_to_range_max",
    "doji_broad_body_ratio": "pattern_thresholds.doji_broad_body_to_range_max",
    "pin_dominant_wick_ratio": "pattern_thresholds.pin_dominant_wick_to_range_min",
    "pin_max_body_ratio": "pattern_thresholds.pin_body_to_range_max",
    "pin_max_opposite_wick_ratio": "pattern_thresholds.pin_opposite_wick_to_range_max",
    "rejection_min_wick_ratio": "pattern_thresholds.rejection_wick_to_range_min",
    "rejection_close_outer_fraction": "pattern_thresholds.rejection_close_outer_fraction",
    "context_proximity_atr": "feature_parameters.proximity_atr_fraction",
    "breakout_atr_buffer": "pattern_thresholds.atr_buffer_breakout_fraction",
}
REQUIRED_DATASET_COLUMNS = {
    "logical_dependency_lineage_id",
    "dependency_release_anchor_tag",
    "group7_logic_source_closure_tag",
    "group7_logic_source_closure_commit_sha",
    "coherent_lineage_amendment_hash",
    "annual_dependency_registry_hash",
    "adapter_map_hash",
    "categorical_dictionary_hash",
    "value_bindings_hash",
    "definition_registry_hash",
}
FORBIDDEN_LEGACY_DATASET_COLUMNS = {
    "group7_recovery_anchor_tag",
    "group7_recovery_anchor_commit_sha",
    "group7_source_closure_tag",
    "group7_source_closure_commit_sha",
    "upstream_lineage_bridge_hash",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--schema", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    root = args.root.resolve()
    failures: list[str] = []
    checks: dict[str, Any] = {}
    defs = json.loads((root / "01_DEFINITION_REGISTRY_CANDIDATE_v2.json").read_text())
    cfg = json.loads((root / "FROZEN_CONFIG_DRAFT.json").read_text())
    semantics = json.loads((root / "UPSTREAM_SOURCE_SEMANTICS_EVIDENCE.json").read_text())
    definitions = defs.get("definitions", {})

    checks["definition_count"] = len(definitions)
    if len(definitions) != 45:
        failures.append(f"definition_count:{len(definitions)}")

    versions: list[str | None] = []
    for name, spec in sorted(definitions.items()):
        for key in ("school", "kind", "version", "mandatory_inputs", "availability"):
            if key not in spec:
                failures.append(f"{name}:missing:{key}")
        if "pass_rule" not in spec and "resolution_rule" not in spec:
            failures.append(f"{name}:missing_pass_or_resolution_rule")
        if spec.get("school") not in ALLOWED_SCHOOLS:
            failures.append(f"{name}:school:{spec.get('school')}")
        versions.append(spec.get("version"))
    if len(set(versions)) != len(versions):
        failures.append("duplicate_definition_version")

    if semantics.get("status") != "PASS" or semantics.get("failures"):
        failures.append("source_semantics_not_pass")

    for text in strings(defs):
        for alias in re.findall(r"\bconfig\.([A-Za-z_][A-Za-z0-9_]*)", text):
            target = CONFIG_ALIASES.get(alias)
            if not target:
                failures.append(f"unknown_config_alias:{alias}")
            else:
                try:
                    get_path(cfg, target)
                except KeyError:
                    failures.append(f"missing_config_target:{alias}:{target}")

    bindings = sorted(
        set(
            path
            for text in strings(defs)
            for path in re.findall(r"UPSTREAM_VALUE_BINDINGS\.(group[0-9]+(?:\.[A-Za-z0-9_]+)+)", text)
        )
    )
    expected_bindings = {
        "group3.advancing_bias_values",
        "group3.declining_bias_values",
        "group3.indeterminate_bias_values",
        "group3.bullish_transition_event_types",
        "group3.bearish_transition_event_types",
        "group3.bullish_direction_values",
        "group3.bearish_direction_values",
        "group3.mss_or_bos_event_types",
    }
    if set(bindings) != expected_bindings:
        failures.append(f"binding_reference_set:{bindings}")

    global_text = " ".join(defs.get("global_rules", [])).lower()
    for phrase in (
        "no future-return",
        "creation records are immutable",
        "no implicit horizon",
        "never select a preferred object or school",
    ):
        if phrase not in global_text:
            failures.append(f"missing_global_rule:{phrase}")

    con = sqlite3.connect(":memory:")
    sql = args.schema.read_text()
    con.executescript(sql)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for table in sorted(REQUIRED_TABLES - tables):
        failures.append(f"missing_table:{table}")
    if "upstream_id_bridge" in tables:
        failures.append("rejected_bridge_table_present")
    for table in sorted(IMMUTABLE_TABLES):
        if f"no_update_{table}" not in triggers:
            failures.append(f"missing_update_guard:{table}")
        if f"no_delete_{table}" not in triggers:
            failures.append(f"missing_delete_guard:{table}")
    for table in tables:
        cols = {str(r[1]).lower() for r in con.execute(f'PRAGMA table_info("{table}")')}
        for col in sorted(cols & FORBIDDEN_SQL_COLUMNS):
            failures.append(f"forbidden_column:{table}.{col}")

    dataset_cols = {r[1] for r in con.execute("PRAGMA table_info('dataset_registry')")}
    missing_dataset_cols = sorted(REQUIRED_DATASET_COLUMNS - dataset_cols)
    legacy_dataset_cols = sorted(FORBIDDEN_LEGACY_DATASET_COLUMNS & dataset_cols)
    for col in missing_dataset_cols:
        failures.append(f"dataset_registry_missing:{col}")
    for col in legacy_dataset_cols:
        failures.append(f"dataset_registry_legacy_column:{col}")
    con.close()

    checks.update(
        {
            "definition_versions_unique": len(set(versions)) == len(versions),
            "source_semantics_status": semantics.get("status"),
            "binding_references": bindings,
            "schema_table_count": len(tables),
            "schema_trigger_count": len(triggers),
            "immutable_table_count": len(IMMUTABLE_TABLES),
            "rejected_bridge_table_absent": "upstream_id_bridge" not in tables,
            "required_dataset_columns_present": not missing_dataset_cols,
            "legacy_dataset_columns_absent": not legacy_dataset_cols,
        }
    )
    report = {
        "format_version": 3,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": sorted(set(failures)),
        "governance": "coherent corrected-v3 Groups2-7 lineage only; no lossy upstream-ID bridge",
    }
    report["report_hash"] = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
