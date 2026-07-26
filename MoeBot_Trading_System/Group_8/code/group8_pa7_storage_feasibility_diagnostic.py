#!/usr/bin/env python3
"""Prove physical storage feasibility/infeasibility for frozen PA7 transition rows.

This is diagnostic-only. It does not change PA7 semantics, schema, configuration,
upstream lineage, or authorization. It combines:

1. an unconditional structural lower bound from mandatory deterministic IDs and
   SHA-256 hashes that every PA7 candidate + mandatory creation-state row stores;
2. an empirical lower bound from real rows emitted by the exact frozen Group8
   engine against the permanent synthetic fixture, counting only UTF-8 TEXT
   payload bytes and excluding all SQLite record/page/index overhead;
3. the already-frozen 2023 lifecycle-aware partial transition count captured in
   Gap008 evidence (Group4 + Group6 + Group8; Group5/Group7 excluded).

The result is intentionally conservative: numeric columns, JSON-independent
SQLite overhead, indexes, non-PA7 Group8 rows, staging, WAL/journal space,
Group5/Group7 transitions, and clean-reconstruction duplicates are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ENGINE_SHA = "44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"
GAP008_REPORT_HASH = "cdd862c7d725858be54c326300404811deee6245ddcb0da3d32a4be68b4122a8"
FIX008_REPORT_HASH = "b35cee4b2f1500ab5a20e8a1bfb8e0a928047d2875e6c5c2c627e8383af0fc8d"
STANDARD_PUBLIC_UBUNTU_STORAGE_BYTES = 14_000_000_000
STANDARD_RUNNER_DOC = "https://docs.github.com/en/actions/reference/runners/github-hosted-runners"

PA7_DEFINITIONS = ("pa_breakout_exact", "pa_breakout_atr_buffer", "pa_breakout_point_buffer")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def self_hash(record: dict[str, Any], field: str) -> str:
    payload = dict(record)
    payload.pop(field, None)
    return stable_hash(payload)


def utf8_len(value: Any) -> int:
    if value is None:
        return 0
    return len(str(value).encode("utf-8"))


def structural_fixed_text_bytes_per_transition() -> tuple[int, dict[str, int]]:
    # These fields are mandatory in the two physical rows and have fixed-length
    # deterministic identifiers/hashes for every PA7 transition.
    fields = {
        "candidate.candidate_id": len(("g8p_" + "0" * 64).encode()),
        "candidate.feature_hash": 64,
        "candidate.candidate_hash": 64,
        "state.state_event_id": len(("g8pstate_" + "0" * 64).encode()),
        "state.candidate_id": len(("g8p_" + "0" * 64).encode()),
        "state.state_hash": 64,
    }
    return sum(fields.values()), fields


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group8-root", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    root = args.group8_root.resolve()

    engine_path = root / "code/moebot_group8_engine_v0_8_0.py"
    schema_path = root / "02_SCHEMA.sql"
    post_path = root / "code/group8_postprocess_v0_8_0.py"
    gap008_path = root / "reports/40_PA7_LIFECYCLE_RETIREMENT_GAP.json"
    fix008_path = root / "reports/41_PA7_LIFECYCLE_RETIREMENT_FIX.json"

    if sha256_file(engine_path) != ENGINE_SHA:
        raise SystemExit("unexpected exact engine identity")
    registry = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    status = json.loads((root / "STATUS.json").read_text())
    manifest = json.loads((root / "ENGINE_BUILD_MANIFEST.json").read_text())
    gap008 = json.loads(gap008_path.read_text())
    fix008 = json.loads(fix008_path.read_text())

    if registry.get("registry_hash") != REGISTRY_HASH or freeze.get("design_freeze_hash") != FREEZE_HASH:
        raise SystemExit("frozen design identity mismatch")
    if gap008.get("report_hash") != GAP008_REPORT_HASH or self_hash(gap008, "report_hash") != GAP008_REPORT_HASH:
        raise SystemExit("Gap008 evidence identity mismatch")
    if fix008.get("report_hash") != FIX008_REPORT_HASH or self_hash(fix008, "report_hash") != FIX008_REPORT_HASH:
        raise SystemExit("Gap008 fix identity mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("2023/2024 authorization boundary mismatch")
    if status.get("officially_closed") is not False:
        raise SystemExit("premature Group8 closure")
    if status.get("blocking_gap", {}).get("gap_id") != "G8-PA7-LIFECYCLE-RETIREMENT-008" or status.get("blocking_gap", {}).get("status") != "CLOSED_BY_TECHNICAL_REFREEZE":
        raise SystemExit("Gap008 is not technically re-frozen")
    if manifest.get("status") != "TECHNICAL_CANDIDATE_PASS" or manifest.get("identities", {}).get("engine", {}).get("sha256") != ENGINE_SHA:
        raise SystemExit("exact technical candidate manifest mismatch")

    partial_count = int(gap008["exact_2023_evidence"]["lifecycle_aware_partial_transition_total"])
    if partial_count != 54_413_814:
        raise SystemExit("unexpected frozen lifecycle-aware partial transition count")

    engine_text = engine_path.read_text()
    schema_text = schema_path.read_text()
    post_text = post_path.read_text()
    mandatory_contract_checks = {
        "candidate_table_present": "CREATE TABLE IF NOT EXISTS price_action_pattern_candidate" in schema_text,
        "state_table_present": "CREATE TABLE IF NOT EXISTS price_action_pattern_state" in schema_text,
        "candidate_fixed_hash_columns_present": all(x in schema_text for x in ("candidate_id TEXT PRIMARY KEY", "feature_hash TEXT NOT NULL", "candidate_hash TEXT NOT NULL")),
        "state_fixed_hash_columns_present": all(x in schema_text for x in ("state_event_id TEXT PRIMARY KEY", "candidate_id TEXT NOT NULL", "state_hash TEXT NOT NULL")),
        "write_pattern_forces_creation_state": "ensure_pattern_creation_state(self.out, row)" in engine_text,
        "creation_state_deterministic_id": 'deterministic_id("g8pstate"' in post_text,
        "full_2023_single_database_protocol": "Build the full 2023 Group 8 database" in (root / "00_DESIGN_LOCK.md").read_text(),
    }
    if not all(mandatory_contract_checks.values()):
        raise SystemExit(f"mandatory storage contract check failed: {mandatory_contract_checks}")

    fixed_bytes, fixed_fields = structural_fixed_text_bytes_per_transition()
    if fixed_bytes != 401:
        raise SystemExit(f"unexpected fixed text lower bound per transition: {fixed_bytes}")
    structural_total = partial_count * fixed_bytes

    # Emit real frozen-engine PA7 rows on the permanent synthetic fixture and
    # measure only actual TEXT payload bytes from candidate + creation-state.
    tests_dir = root / "tests"
    code_dir = root / "code"
    sys.path.insert(0, str(code_dir))
    sys.path.insert(0, str(tests_dir))
    import test_group8_engine_v0_8_0 as base  # type: ignore
    from moebot_group8_engine_v0_8_0 import Group8Engine  # type: ignore

    empirical_lengths: list[int] = []
    empirical_candidate_lengths: list[int] = []
    empirical_state_lengths: list[int] = []
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        stage = td_path / "stage.sqlite"
        output = td_path / "out.sqlite"
        base.make_stage(stage)
        engine = Group8Engine(staging_db=stage, output_db=output, artifacts_root=root, year=2023, symbol="XAUUSD_")
        try:
            engine.load_bars()
            engine.process_bounded_ranges()
            engine.process_breakouts()
            placeholders = ",".join("?" for _ in PA7_DEFINITIONS)
            rows = engine.out.execute(
                f"SELECT c.candidate_id,c.definition_id,c.symbol,c.timeframe,c.direction,c.reasons_json,c.features_json,c.upstream_refs_json,c.feature_hash,c.candidate_hash,"
                f"s.state_event_id,s.candidate_id AS state_candidate_id,s.state,s.details_json,s.state_hash "
                f"FROM price_action_pattern_candidate c JOIN price_action_pattern_state s ON s.candidate_id=c.candidate_id AND s.state_ordinal=0 "
                f"WHERE c.definition_id IN ({placeholders}) ORDER BY c.candidate_id",
                PA7_DEFINITIONS,
            ).fetchall()
            if not rows:
                raise SystemExit("permanent fixture produced no PA7 transitions")
            candidate_cols = ("candidate_id", "definition_id", "symbol", "timeframe", "direction", "reasons_json", "features_json", "upstream_refs_json", "feature_hash", "candidate_hash")
            state_cols = ("state_event_id", "state_candidate_id", "state", "details_json", "state_hash")
            for row in rows:
                c_len = sum(utf8_len(row[col]) for col in candidate_cols)
                s_len = sum(utf8_len(row[col]) for col in state_cols)
                empirical_candidate_lengths.append(c_len)
                empirical_state_lengths.append(s_len)
                empirical_lengths.append(c_len + s_len)
            sample_db_bytes = output.stat().st_size
            sample_candidate_count = len(rows)
        finally:
            engine.close()

    empirical_min = min(empirical_lengths)
    empirical_total_projection = partial_count * empirical_min
    disk = shutil.disk_usage(root)

    upstream = json.loads((root / "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json").read_text())
    clean_groups = upstream["years"]["2023"]["clean_room"]["groups"]
    dependency_db_sizes = {"source": int(upstream["source_databases"]["2023"]["database_size_bytes"])}
    for group in ("group2", "group3", "group4", "group5", "group6", "group7"):
        dependency_db_sizes[group] = int(clean_groups[group]["database"]["size_bytes"])
    dependency_total = sum(dependency_db_sizes.values())

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "PASS",
        "scope": "PA7_TRANSITION_PHYSICAL_STORAGE_FEASIBILITY_2023",
        "engine_sha256": ENGINE_SHA,
        "definition_registry_hash": REGISTRY_HASH,
        "design_freeze_hash": FREEZE_HASH,
        "engine_build_manifest_hash": manifest.get("manifest_hash"),
        "gap008_report_hash": GAP008_REPORT_HASH,
        "gap008_fix_report_hash": FIX008_REPORT_HASH,
        "partial_transition_count": partial_count,
        "partial_scope_excludes": ["Group5 PA7 boundaries", "Group7 PA7 boundaries"],
        "mandatory_contract_checks": mandatory_contract_checks,
        "structural_text_lower_bound": {
            "fixed_fields": fixed_fields,
            "bytes_per_transition": fixed_bytes,
            "total_bytes": structural_total,
            "total_decimal_gb": structural_total / 1_000_000_000,
            "total_gib": structural_total / (1024 ** 3),
            "excluded_from_bound": [
                "definition_id/symbol/timeframe/direction text",
                "reasons_json/features_json/upstream_refs_json",
                "state/state.details_json",
                "all numeric columns",
                "SQLite record headers and varints",
                "PRIMARY KEY/UNIQUE/secondary indexes",
                "page free-space/fragmentation",
                "non-PA7 Group8 output",
                "Group5/Group7 PA7 transitions",
            ],
        },
        "empirical_frozen_engine_text_payload": {
            "fixture": "tests/test_group8_engine_v0_8_0.py::make_stage",
            "sample_transition_rows": sample_candidate_count,
            "sample_output_db_size_bytes": sample_db_bytes,
            "candidate_text_bytes_min": min(empirical_candidate_lengths),
            "candidate_text_bytes_max": max(empirical_candidate_lengths),
            "creation_state_text_bytes_min": min(empirical_state_lengths),
            "creation_state_text_bytes_max": max(empirical_state_lengths),
            "combined_text_bytes_min_per_transition": empirical_min,
            "combined_text_bytes_max_per_transition": max(empirical_lengths),
            "projected_partial_bytes_using_sample_min": empirical_total_projection,
            "projected_partial_decimal_gb_using_sample_min": empirical_total_projection / 1_000_000_000,
            "projected_partial_gib_using_sample_min": empirical_total_projection / (1024 ** 3),
            "note": "Empirical projection is supporting evidence only; the 401-byte structural bound is the unconditional proof bound.",
        },
        "standard_public_github_runner": {
            "workflow_label": "ubuntu-latest",
            "documented_storage_bytes": STANDARD_PUBLIC_UBUNTU_STORAGE_BYTES,
            "documented_storage_gb": 14,
            "documentation": STANDARD_RUNNER_DOC,
            "standard_public_runner_is_free": True,
            "structural_bound_exceeds_documented_storage": structural_total > STANDARD_PUBLIC_UBUNTU_STORAGE_BYTES,
            "structural_bound_to_storage_ratio": structural_total / STANDARD_PUBLIC_UBUNTU_STORAGE_BYTES,
        },
        "diagnostic_runner_snapshot": {
            "filesystem_total_bytes": disk.total,
            "filesystem_used_bytes": disk.used,
            "filesystem_free_bytes": disk.free,
            "structural_bound_exceeds_snapshot_free": structural_total > disk.free,
            "empirical_min_projection_exceeds_snapshot_free": empirical_total_projection > disk.free,
        },
        "annual_input_context": {
            "frozen_2023_dependency_database_sizes_bytes": dependency_db_sizes,
            "sum_dependency_database_file_sizes_bytes": dependency_total,
            "sum_dependency_database_file_sizes_decimal_gb": dependency_total / 1_000_000_000,
            "note": "Context only, not added to the unconditional output lower bound because source SQLite file sizes can include independent storage overhead/free pages.",
        },
        "conclusion": {
            "standard_public_runner_can_materialize_required_single_database": False,
            "reason": "mandatory candidate+creation-state fixed ID/hash text alone exceeds the documented 14 GB standard-runner SSD before any required JSON, indexes, staging, or other Group8 rows",
            "single_database_protocol_is_frozen": True,
            "infrastructure_or_storage_contract_change_required": True,
        },
        "observations": {
            "diagnostic_only": True,
            "engine_changed": False,
            "definitions_changed": False,
            "thresholds_changed": False,
            "schema_changed": False,
            "upstream_changed": False,
            "authorization_changed": False,
            "oos_2024_accessed": False,
        },
    }
    report["report_hash"] = stable_hash(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
