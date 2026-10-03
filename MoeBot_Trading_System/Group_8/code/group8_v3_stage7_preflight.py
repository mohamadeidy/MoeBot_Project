#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from moebot_group8_engine_v0_8_0 import sha256_file, stable_hash

ICT_DEFINITIONS = (
    "ict_liquidity_sweep_displacement",
    "ict_mss_fvg_delivery",
    "ict_premium_discount_context",
    "ict_return_to_imbalance",
    "ict_block_delivery_context",
    "ict_draw_on_liquidity_context",
)


def _git_head(artifacts_root: Path) -> str:
    repo = artifacts_root.resolve().parent.parent
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _verify_self_hash(record: dict[str, Any], field: str) -> None:
    if field not in record:
        raise RuntimeError(f"missing {field}")
    payload = dict(record)
    saved = str(payload.pop(field))
    if stable_hash(payload) != saved:
        raise RuntimeError(f"{field} mismatch")


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _status_active(status: str | None) -> bool:
    s = (status or "").lower()
    return not any(x in s for x in ("invalid", "expired", "broken", "deleted", "inactive"))


def _first_after(times: list[int], availability: int) -> int | None:
    i = bisect.bisect_right(times, availability)
    return None if i >= len(times) else int(times[i])


def _load_zone_invalidators(staging: sqlite3.Connection) -> dict[str, list[int]]:
    by_zone: dict[str, list[int]] = defaultdict(list)
    for r in staging.execute(
        "SELECT zone_id,transition_time,to_status FROM group4__zone_transitions "
        "ORDER BY zone_id,transition_time,transition_id"
    ):
        if not _status_active(str(r["to_status"])):
            by_zone[str(r["zone_id"])].append(int(r["transition_time"]))
    for r in staging.execute(
        "SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions "
        "ORDER BY zone_id,interaction_time,interaction_id"
    ):
        if not _status_active(str(r["status_after"])):
            by_zone[str(r["zone_id"])].append(int(r["interaction_time"]))
    for times in by_zone.values():
        times.sort()
    return by_zone


def _premium_discount_cardinality(
    staging: sqlite3.Connection,
    stage5: sqlite3.Connection,
    symbol: str,
) -> dict[str, Any]:
    bars_by_key: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    bar_pos: dict[int, tuple[tuple[str, str], int]] = {}
    for r in staging.execute(
        "SELECT id,symbol,timeframe,available_at FROM source__bars WHERE symbol=? "
        "ORDER BY symbol,timeframe,available_at,id",
        (symbol,),
    ):
        key = (str(r["symbol"]), str(r["timeframe"]))
        idx = len(bars_by_key[key])
        bars_by_key[key].append((int(r["id"]), int(r["available_at"])))
        bar_pos[int(r["id"])] = (key, idx)
    avails = {k: [x[1] for x in v] for k, v in bars_by_key.items()}
    invalidators = _load_zone_invalidators(staging)

    total = 0
    ranges = 0
    missing_source_bar = 0
    no_future_bars = 0
    by_tf: dict[str, int] = defaultdict(int)
    by_window: dict[str, int] = defaultdict(int)

    for rg in stage5.execute(
        "SELECT candidate_id,symbol,timeframe,source_bar_id,event_time,availability_time,features_json "
        "FROM price_action_pattern_candidate "
        "WHERE definition_id='pa_bounded_range_context' AND symbol=? "
        "ORDER BY timeframe,availability_time,candidate_id",
        (symbol,),
    ):
        ranges += 1
        src_id = int(rg["source_bar_id"]) if rg["source_bar_id"] is not None else None
        if src_id is None or src_id not in bar_pos:
            missing_source_bar += 1
            continue
        key, src_idx = bar_pos[src_id]
        availability = int(rg["availability_time"])
        left = max(src_idx, bisect.bisect_left(avails[key], availability))
        features = json.loads(str(rg["features_json"] or "{}"))
        zone_ids = [features.get("lower_zone_id"), features.get("upper_zone_id")]
        inv_times: list[int] = []
        for zid in zone_ids:
            if not zid:
                continue
            t = _first_after(invalidators.get(str(zid), []), availability)
            if t is not None:
                inv_times.append(t)
        invalidation = min(inv_times) if inv_times else None
        right = len(avails[key]) if invalidation is None else bisect.bisect_left(avails[key], invalidation)
        n = max(0, right - left)
        if n == 0:
            no_future_bars += 1
        total += n
        tf = str(rg["timeframe"])
        by_tf[tf] += n
        import datetime as _dt
        month = _dt.datetime.fromtimestamp(int(rg["event_time"]), tz=_dt.timezone.utc).strftime("%Y-%m")
        by_window[f"{tf}:{month}"] += n

    return {
        "range_roots": ranges,
        "interpretations": total,
        "missing_source_bar": missing_source_bar,
        "zero_row_ranges": no_future_bars,
        "by_timeframe": dict(sorted(by_tf.items())),
        "by_root_window": dict(sorted(by_window.items())),
    }


def run_preflight(
    *,
    staging_db: Path,
    stage5_db: Path,
    stage6_release_path: Path,
    stage6_union_path: Path,
    artifacts_root: Path,
    year: int,
    symbol: str,
    validated_commit: str,
    report_path: Path,
) -> dict[str, Any]:
    if year != 2023:
        raise RuntimeError("Stage 7 V3 preflight is frozen to 2023; 2024 OOS remains forbidden")
    actual_head = _git_head(artifacts_root)
    if actual_head != validated_commit:
        raise RuntimeError(f"server Git HEAD mismatch: {actual_head} != {validated_commit}")

    release = json.loads(stage6_release_path.read_text())
    _verify_self_hash(release, "release_hash")
    union = json.loads(stage6_union_path.read_text())
    _verify_self_hash(union, "report_hash")
    if release.get("status") != "PASS" or int(release.get("stage", 0)) != 6:
        raise RuntimeError("Stage 6 release is not PASS")
    if union.get("status") != "PASS" or union.get("stage6_official_pass_eligible") is not True:
        raise RuntimeError("Stage 6 union is not official-PASS eligible")
    if union.get("stage6_release_hash") != release.get("release_hash"):
        raise RuntimeError("Stage 6 union/release hash lineage mismatch")
    stage5_sha = sha256_file(stage5_db)
    if stage5_sha != release.get("stage5_database_sha256") or stage5_sha != union.get("stage5_database_sha256"):
        raise RuntimeError("Stage 5 hash does not match official Stage 6 lineage")

    bindings = json.loads((artifacts_root / "UPSTREAM_VALUE_BINDINGS.json").read_text())
    allowed = list(bindings["bindings"]["group3"]["mss_or_bos_event_types"])
    q_allowed = ",".join("?" for _ in allowed)

    staging = _ro(staging_db)
    stage5 = _ro(stage5_db)
    try:
        ict_cp = int(stage5.execute(
            "SELECT COUNT(*) FROM processing_checkpoint WHERE stage='ict_core' AND status='PASS'"
        ).fetchone()[0])
        q_defs = ",".join("?" for _ in ICT_DEFINITIONS)
        physical_ict = int(stage5.execute(
            f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q_defs})",
            ICT_DEFINITIONS,
        ).fetchone()[0])

        input_counts = {}
        for table in (
            "group6__fvg_events",
            "group6__fvg_state_transitions",
            "group6__liquidity_voids",
            "group6__bpr_relations",
            "group6__inversion_fvg_relations",
            "group6__imbalance_variants",
            "group6__group6_evidence",
            "group7__definition_candidates",
            "group7__definition_matches",
            "group7__institutional_zones",
            "group7__zone_evidence",
            "group5__draw_states",
            "group3__structure_states",
        ):
            input_counts[table] = int(staging.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if _table_exists(staging, table) else None

        ict1 = int(staging.execute(
            """SELECT COUNT(*)
               FROM group6__group6_evidence e
               JOIN group5__liquidity_events q ON q.event_id=e.source_id
               JOIN (
                   SELECT DISTINCT l.leg_id
                   FROM group6__displacement_legs l
                   JOIN group6__displacement_validation_events v ON v.leg_id=l.leg_id
                   WHERE lower(COALESCE(v.result,'')) IN ('pass','validated','true','1','accepted','valid')
                      OR lower(COALESCE(v.validation_type,'')) LIKE '%valid%'
               ) vl ON vl.leg_id=e.subject_id
               WHERE lower(e.source_group) IN ('group5','5')"""
        ).fetchone()[0])

        ict2 = int(staging.execute(
            f"""SELECT COUNT(*)
                FROM group6__fvg_events f
                JOIN group3__break_events e ON e.event_id=f.associated_group3_event_id
                WHERE f.associated_group3_event_id IS NOT NULL
                  AND e.resolved_time IS NOT NULL
                  AND e.event_type IN ({q_allowed})""",
            tuple(allowed),
        ).fetchone()[0])

        premium = _premium_discount_cardinality(staging, stage5, symbol)

        ict4_fvg = int(staging.execute(
            """SELECT COUNT(*)
               FROM group6__fvg_state_transitions t
               JOIN group6__fvg_events f ON f.fvg_id=t.fvg_id
               WHERE t.transition_time>f.availability_time
                 AND (
                   lower(t.event_type) LIKE '%touch%' OR
                   lower(t.event_type) LIKE '%visit%' OR
                   lower(t.event_type) LIKE '%fill%' OR
                   lower(t.event_type) LIKE '%ce%' OR
                   lower(t.event_type) LIKE '%traverse%'
                 )"""
        ).fetchone()[0])

        inversion_retests = int(staging.execute(
            """SELECT COUNT(*)
               FROM group6__inversion_fvg_relations i
               JOIN group6__fvg_events f ON f.fvg_id=i.original_fvg_id
               WHERE i.first_retest_time IS NOT NULL
                 AND i.first_retest_time>i.availability_time"""
        ).fetchone()[0])

        ict5 = int(staging.execute(
            """SELECT COUNT(*)
               FROM group7__institutional_zones z
               JOIN group7__zone_evidence e ON e.zone_id=z.zone_id
               WHERE lower(e.source_group) IN ('group6','6')"""
        ).fetchone()[0])

        ict6 = int(staging.execute(
            """SELECT COUNT(*)
               FROM group5__draw_states d
               JOIN group5__liquidity_pools p ON p.pool_id=d.selected_pool_id
               WHERE d.selected_pool_id IS NOT NULL
                 AND EXISTS (
                   SELECT 1 FROM group3__structure_states s
                   WHERE s.timeframe=d.timeframe AND s.close_time<=d.close_time
                 )"""
        ).fetchone()[0])

        adapter = json.loads((artifacts_root / "UPSTREAM_ADAPTER_MAP.json").read_text())
        g6_adapter = set(adapter["adapters"]["group6"])
        lifecycle_coverage = {
            "fvg_or_ce": {
                "causal_lifecycle_adapter": "fvg_state_transitions",
                "available": "fvg_state_transitions" in g6_adapter,
                "enumerable_rows": ict4_fvg,
            },
            "inversion": {
                "causal_field": "inversion_fvg_relations.first_retest_time",
                "adapter_available": "inversion_fvg_relations" in g6_adapter,
                "potential_retest_rows": inversion_retests,
                "current_engine_emits": False,
                "requires_semantic_conformance_review": True,
            },
            "bpr": {
                "object_adapter_available": "bpr_relations" in g6_adapter,
                "causal_touch_visit_adapter_available": "bpr_state_transitions" in g6_adapter,
                "staging_transition_table_exists": _table_exists(staging, "group6__bpr_state_transitions"),
                "safe_policy": "do_not_infer_later_touch_from_aggregate_state_without_causal_event_time",
            },
            "liquidity_void": {
                "object_adapter_available": "liquidity_voids" in g6_adapter,
                "causal_touch_visit_adapter_available": "liquidity_void_state_transitions" in g6_adapter,
                "staging_transition_table_exists": _table_exists(staging, "group6__liquidity_void_state_transitions"),
                "safe_policy": "do_not_infer_later_touch_from_aggregate_state_without_causal_event_time",
            },
        }

        current_counts = {
            "ict_liquidity_sweep_displacement": ict1,
            "ict_mss_fvg_delivery": ict2,
            "ict_premium_discount_context": int(premium["interpretations"]),
            "ict_return_to_imbalance_fvg_ce_current_engine": ict4_fvg,
            "ict_block_delivery_context": ict5,
            "ict_draw_on_liquidity_context": ict6,
        }
        current_interpretations = sum(current_counts.values())
        current_evidence_rows = (
            3 * ict1
            + 2 * ict2
            + 2 * int(premium["interpretations"])
            + 2 * ict4_fvg
            + 2 * ict5
            + 3 * ict6
        )
        stage6_rows = int(union["table_row_counts"]["school_interpretation"]) + int(union["table_row_counts"]["evidence_chain"])
        stage6_bytes_per_row = float(release["total_output_bytes"]) / max(stage6_rows, 1)
        projected_logical_rows = current_interpretations + current_evidence_rows
        projected_bytes_stage6_density = int(projected_logical_rows * stage6_bytes_per_row * 1.5)

        blockers = []
        if ict_cp:
            blockers.append(f"unexpected ict_core PASS checkpoint in protected Stage5 boundary:{ict_cp}")
        if physical_ict:
            blockers.append(f"unexpected physical Stage7 ICT rows in protected Stage5 boundary:{physical_ict}")
        if premium["missing_source_bar"]:
            blockers.append(f"bounded ranges with missing source bar:{premium['missing_source_bar']}")

        report = {
            "format_version": 1,
            "scope": "GROUP8_V3_STAGE7_2023_PREFLIGHT",
            "status": "PASS" if not blockers else "BLOCKED",
            "year": year,
            "symbol": symbol,
            "validated_commit": validated_commit,
            "stage6_official_pass_prerequisite": True,
            "stage6_release_hash": release["release_hash"],
            "stage6_union_report_hash": union["report_hash"],
            "stage5_database_sha256": stage5_sha,
            "stage5_read_only": True,
            "groups_1_7_read_only": True,
            "stage7_auto_launch": False,
            "stage7_authorized": False,
            "full_annual_stage7_permitted_by_preflight": False,
            "authorization_reason": "requires optimized executor, parity proof, representative benchmark, storage/runtime gates, and union validation",
            "input_counts": input_counts,
            "physical_stage7_contamination_rows": physical_ict,
            "ict_core_pass_checkpoint_count": ict_cp,
            "definition_cardinality_current_engine": current_counts,
            "premium_discount": premium,
            "return_to_imbalance_lifecycle_coverage": lifecycle_coverage,
            "inversion_retest_rows_not_emitted_by_current_engine": inversion_retests,
            "projection_diagnostic": {
                "current_engine_interpretation_rows": current_interpretations,
                "current_engine_evidence_chain_rows": current_evidence_rows,
                "current_engine_total_logical_rows": projected_logical_rows,
                "stage6_observed_bytes_per_logical_row": stage6_bytes_per_row,
                "rough_storage_projection_bytes_at_1_5x_stage6_density": projected_bytes_stage6_density,
                "runtime_projection": "PENDING_OPTIMIZED_EXECUTOR_BENCHMARK",
                "storage_projection_is_authorization_grade": False,
            },
            "performance_diagnosis": {
                "group5_liquidity_event_lookup_per_group6_evidence": "N+1 in current process_ict; batch-map safe",
                "group3_break_event_lookup_per_fvg": "N+1 in current process_ict; batch-map safe",
                "bounded_range_invalidator_lookup": "up to four upstream queries per range in current helper; preload/bisect safe",
                "group7_zone_evidence_lookup_per_zone": "N+1 in current process_ict; batch-group safe",
                "latest_group3_structure_state_per_draw": "N+1 in current process_ict; sorted-time index/bisect safe",
                "premium_discount_is_primary_cardinality_risk": True,
            },
            "blockers": blockers,
        }
        report["report_hash"] = stable_hash(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    finally:
        stage5.close()
        staging.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--stage6-release", type=Path, required=True)
    p.add_argument("--stage6-union", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--validated-commit", required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    r = run_preflight(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        stage6_release_path=a.stage6_release.resolve(),
        stage6_union_path=a.stage6_union.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        year=a.year,
        symbol=a.symbol,
        validated_commit=a.validated_commit,
        report_path=a.report.resolve(),
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
