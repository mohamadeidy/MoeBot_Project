#!/usr/bin/env python3
"""Register PA7 lifecycle-retirement implementation gap 008 and fail closed.

Gap008 is not a design amendment. PA7E.2/A.2/P.2 already freeze the rule that
lifecycle termination retires the exact boundary identity. The current engine
implements causal retirement for Group4/Group7, but Group6 and Group8 fall
through active forever. Exact 2023 diagnostics proved terminal FVG transitions
and bounded-range invalidations exist. This script records the contradiction and
revokes annual authorization until a minimal correctness fix is independently
retested and re-frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-LIFECYCLE-RETIREMENT-008"
ENGINE_SHA = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"
BUILD_MANIFEST_HASH = "2c89bce52ef8473d55fdc612249f85026554b41666a2ee1595736edab14ed032"
TRANSITION_COUNT_REPORT_HASH = "40d6ec46455faf26793488fd8a715dc107428aef594b8c68198bc10016c7e6b2"
GROUP6_LIFECYCLE_PROBE_HASH = "7fc11390048db7e3bfeaf6741250bbd2de78a485f21651372e9a545cc6ed76bb"
LIFETIME_COUNT_HASH = "82a5c4a3a27385a9fa425c49ba99f9187d1d721004a62bea42bb68b696c2f03d"
GROUP5_POOL_PROBE_HASH = "98e0621ba60924da8739584d1b49bfc0636bb7eda7e8e41be31175a8fd12282d"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def self_hash(record: dict[str, Any], field: str) -> str:
    p = dict(record); p.pop(field, None); return stable_hash(p)


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--group8-root", type=Path, required=True); a = p.parse_args()
    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    engine_path = root / "code/moebot_group8_engine_v0_8_0.py"
    registry_path = root / "01_DEFINITION_REGISTRY.json"
    freeze_path = root / "DESIGN_FREEZE_MANIFEST.json"
    count_path = root / "reports/39A_PA7_TRANSITION_COUNTONLY_DIAGNOSTIC.json"

    status = json.loads(status_path.read_text())
    registry = json.loads(registry_path.read_text())
    freeze = json.loads(freeze_path.read_text())
    count = json.loads(count_path.read_text())
    engine = engine_path.read_text()

    if sha256_file(engine_path) != ENGINE_SHA:
        raise SystemExit("unexpected engine identity")
    if registry.get("registry_hash") != REGISTRY_HASH or self_hash(registry, "registry_hash") != REGISTRY_HASH:
        raise SystemExit("definition registry identity mismatch")
    if freeze.get("design_freeze_hash") != FREEZE_HASH or freeze.get("definition_registry_hash") != REGISTRY_HASH:
        raise SystemExit("Design Freeze identity mismatch")
    if status.get("engine_build", {}).get("engine_build_manifest_hash") != BUILD_MANIFEST_HASH:
        raise SystemExit("technical build manifest binding mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("expected pre-gap 2023-only authorization state")
    q = dict(count); count_hash = q.pop("report_hash", None)
    if stable_hash(q) != count_hash or count_hash != TRANSITION_COUNT_REPORT_HASH:
        raise SystemExit(f"transition count diagnostic identity mismatch:{count_hash}")

    versions = {"pa_breakout_exact": "PA7E.2", "pa_breakout_atr_buffer": "PA7A.2", "pa_breakout_point_buffer": "PA7P.2"}
    frozen_lifecycle = True
    for did, ver in versions.items():
        d = registry["definitions"][did]
        frozen_lifecycle = frozen_lifecycle and d.get("version") == ver and "lifecycle termination" in str(d.get("lifecycle_identity_rule", "")).lower() and "retires" in str(d.get("lifecycle_identity_rule", "")).lower()
    if not frozen_lifecycle:
        raise SystemExit("PA7 lifecycle retirement is not frozen as expected")

    # Current exact engine catalog/active predicate: Group6 and Group8 boundaries
    # are catalogued, but active_at has no branch for either group and falls through True.
    current_bug = (
        'rows.append({"group":"group6"' in engine
        and 'rows.append({"group":"group8"' in engine
        and 'if bnd["group"]=="group7"' in engine
        and 'return True\n\n    def _pa7_beyond' in engine
        and 'if bnd["group"]=="group6"' not in engine[engine.index("    def _pa7_boundary_active_at"):engine.index("    def _pa7_beyond")]
        and 'if bnd["group"]=="group8"' not in engine[engine.index("    def _pa7_boundary_active_at"):engine.index("    def _pa7_beyond")]
    )
    if not current_bug:
        raise SystemExit("engine no longer matches the proven lifecycle fall-through defect")

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "OPEN_CORRECTNESS_FIX_REQUIRED",
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "classification": "FROZEN_IMPLEMENTATION_SEMANTIC_VIOLATION",
        "design_change_required": False,
        "decision_required": False,
        "engine_sha256": ENGINE_SHA,
        "definition_registry_hash": REGISTRY_HASH,
        "design_freeze_hash": FREEZE_HASH,
        "engine_build_manifest_hash": BUILD_MANIFEST_HASH,
        "frozen_contract": {
            "variants": versions,
            "rule": "lifecycle termination retires the exact boundary identity state; state is not carried beyond lifecycle termination",
            "transition_semantics_unchanged": "NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY",
        },
        "root_cause": "_pa7_boundary_active_at applies causal lifetime to Group4 and Group7 but has no Group6 or Group8 branch, so Group6 FVG and Group8 bounded-range boundary identities fall through active after causally known lifecycle termination.",
        "exact_2023_evidence": {
            "transition_count_report_hash": TRANSITION_COUNT_REPORT_HASH,
            "pre_lifecycle_transition_total_group6_plus_group8": int(count["transition_counts"]["total"]),
            "group6_lifecycle_probe_hash": GROUP6_LIFECYCLE_PROBE_HASH,
            "group6_fvg_total": 121953,
            "group6_fvg_traversed_invalidated_terminal_count": 121174,
            "bounded_range_count": 93834,
            "bounded_range_post_invalidation_fraction_historical_diagnostic": 0.843955759,
            "lifecycle_aware_count_report_hash": LIFETIME_COUNT_HASH,
            "lifecycle_aware_partial_transition_total": 54413814,
            "lifecycle_aware_group6_fvg_transition_total": 361050,
            "lifecycle_aware_group8_bounded_range_transition_total": 2128551,
            "group5_pool_probe_hash": GROUP5_POOL_PROBE_HASH,
            "group5_swept_pool_count": 8735,
            "group5_retirement_not_applied_without_exact_contract_confirmation": True,
        },
        "minimal_correct_fix": {
            "group6_fvg": "retire at first causal group6__fvg_state_transitions transition with event_type=traversed and directional_validity=invalidated; transition_time is the causal timestamp",
            "group8_bounded_range": "retire at first causal invalidation of either locked Group4 boundary, matching frozen PA6G.1 invalidation rule",
            "group5": "retain existing expires_at handling unless exact frozen Group5 runtime contract separately proves first_sweep_time is lifecycle termination",
            "other_group6": "do not infer retirement from final state without a causal timestamp in the frozen adapter",
        },
        "forbidden_shortcuts": [
            "do not disable M1 or any timeframe to make workload smaller",
            "do not suppress valid PA7 variants",
            "do not change Exact/ATR/Point predicates or thresholds",
            "do not use 2024 to select a fix",
            "do not back-project final lifecycle states without causal timestamps",
        ],
        "oos_2024_accessed": False,
    }
    report["report_hash"] = stable_hash(report)
    report_path = root / "reports/40_PA7_LIFECYCLE_RETIREMENT_GAP.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    previous = status.get("blocking_gap")
    status["previous_closed_blocking_gap"] = previous
    status["blocking_gap"] = {
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "status": "OPEN_CORRECTNESS_FIX_REQUIRED",
        "classification": "FROZEN_IMPLEMENTATION_SEMANTIC_VIOLATION",
        "decision_required": False,
        "design_change_required": False,
        "report_hash": report["report_hash"],
        "engine_sha256": ENGINE_SHA,
        "definition_registry_hash": REGISTRY_HASH,
        "design_freeze_hash": FREEZE_HASH,
        "oos_2024_accessed": False,
    }
    status["engine_build_authorized"] = False
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["engine_build"]["status"] = "TECHNICAL_CANDIDATE_BLOCKED_BY_CORRECTNESS_GAP"
    status["status"] = "BLOCKING_CORRECTNESS_GAP_G8_PA7_LIFECYCLE_RETIREMENT_008"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({"status": "PASS", "gap_id": GAP_ID, "report_hash": report["report_hash"], "2023_authorized": False, "2024_authorized": False, "decision_required": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
