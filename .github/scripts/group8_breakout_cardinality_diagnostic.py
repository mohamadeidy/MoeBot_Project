#!/usr/bin/env python3
"""Diagnose Group 8 annual-2023 breakout enumeration without changing frozen semantics.

The diagnostic runs only the already-proven load_bars and bounded_ranges stages,
then measures the exact cumulative Group6 and Group8 boundary enumeration implied
by the current frozen process_breakouts implementation. It also measures how many
pa_bounded_range_context/bar evaluations occur at or after the exact locked-range
invalidation rule already frozen and implemented by Group 8 postprocessing.

No Group 8 engine/config/schema/status file is modified by this script.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

EXPECTED_ENGINE_SHA256 = "61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
G6_TABLES = (
    ("group6__fvg_events", "availability_time"),
    ("group6__imbalance_variants", "availability_time"),
    ("group6__liquidity_voids", "availability_time"),
    ("group6__bpr_relations", "availability_time"),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def first_after(index: dict[str, tuple[list[int], list[tuple[int, str, str]]]], zone_id: str | None, after: int) -> tuple[int, str, str] | None:
    if not zone_id or zone_id not in index:
        return None
    times, records = index[zone_id]
    pos = bisect.bisect_right(times, int(after))
    return records[pos] if pos < len(records) else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()

    if args.year != 2023:
        raise SystemExit("diagnostic is intentionally restricted to authorized 2023")

    root = args.group8_root.resolve()
    engine_path = root / "code" / "moebot_group8_engine_v0_8_0.py"
    actual_engine_sha = sha256_file(engine_path)
    if actual_engine_sha != EXPECTED_ENGINE_SHA256:
        raise SystemExit(f"unexpected frozen engine identity:{actual_engine_sha}")

    import sys
    sys.path.insert(0, str(root / "code"))
    from moebot_group8_engine_v0_8_0 import Group8Engine

    engine = Group8Engine(
        staging_db=args.staging_db,
        output_db=args.output_db,
        artifacts_root=root,
        year=2023,
    )
    try:
        engine.load_bars()
        engine.process_bounded_ranges()

        bar_avails_by_key: dict[tuple[str, str], list[int]] = {}
        all_bar_avails: list[int] = []
        for key, bars in engine.bars_by_tf.items():
            vals = sorted(int(b.available_at) for b in bars)
            bar_avails_by_key[key] = vals
            all_bar_avails.extend(vals)
        all_bar_avails.sort()

        g6: dict[str, dict[str, int]] = {}
        g6_pair_total = 0
        for table, availability_col in G6_TABLES:
            vals = [int(r[0]) for r in engine.input.execute(
                f'SELECT "{availability_col}" FROM "{table}" ORDER BY "{availability_col}"'
            )]
            pair_count = sum(bisect.bisect_right(vals, t) for t in all_bar_avails)
            g6[table] = {"rows": len(vals), "cumulative_bar_boundary_evaluations": int(pair_count)}
            g6_pair_total += int(pair_count)

        invalidating: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        for r in engine.input.execute(
            "SELECT zone_id,transition_time,transition_id,to_status FROM group4__zone_transitions ORDER BY zone_id,transition_time,transition_id"
        ):
            if not engine._status_active(str(r[3])):
                invalidating[str(r[0])].append((int(r[1]), "group4_zone_transitions", str(r[2])))
        for r in engine.input.execute(
            "SELECT zone_id,interaction_time,interaction_id,status_after FROM group4__zone_interactions ORDER BY zone_id,interaction_time,interaction_id"
        ):
            if not engine._status_active(str(r[3])):
                invalidating[str(r[0])].append((int(r[1]), "group4_zone_interactions", str(r[2])))
        invalidation_index: dict[str, tuple[list[int], list[tuple[int, str, str]]]] = {}
        for zone_id, records in invalidating.items():
            records.sort(key=lambda x: (x[0], x[1], x[2]))
            invalidation_index[zone_id] = ([x[0] for x in records], records)

        ranges = engine.out.execute(
            "SELECT candidate_id,symbol,timeframe,availability_time,features_json "
            "FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' "
            "ORDER BY availability_time,candidate_id"
        ).fetchall()
        range_raw_pairs = 0
        range_valid_lifetime_pairs = 0
        invalidated_ranges = 0
        right_censored_ranges = 0
        invalidator_type_counts: dict[str, int] = defaultdict(int)
        stale_by_tf: dict[str, int] = defaultdict(int)
        raw_by_tf: dict[str, int] = defaultdict(int)

        for r in ranges:
            key = (str(r["symbol"]), str(r["timeframe"]))
            bars = bar_avails_by_key.get(key, [])
            created = int(r["availability_time"])
            start = bisect.bisect_left(bars, created)
            raw = len(bars) - start
            range_raw_pairs += raw
            raw_by_tf[key[1]] += raw

            features = json.loads(r["features_json"])
            candidates = [
                first_after(invalidation_index, features.get("lower_zone_id"), created),
                first_after(invalidation_index, features.get("upper_zone_id"), created),
            ]
            candidates = [x for x in candidates if x is not None]
            if not candidates:
                right_censored_ranges += 1
                valid = raw
            else:
                inv = min(candidates, key=lambda x: (x[0], x[1], x[2]))
                invalidated_ranges += 1
                invalidator_type_counts[inv[1]] += 1
                end = bisect.bisect_left(bars, inv[0])
                valid = max(0, end - start)
            range_valid_lifetime_pairs += valid
            stale_by_tf[key[1]] += raw - valid

        stale_pairs = int(range_raw_pairs - range_valid_lifetime_pairs)
        if stale_pairs < 0:
            raise SystemExit("internal diagnostic invariant failed: negative stale pair count")

        report: dict[str, Any] = {
            "format_version": 2,
            "status": "PASS",
            "scope": "DIAGNOSTIC_ONLY_NO_FROZEN_MUTATION",
            "year": 2023,
            "engine_sha256": actual_engine_sha,
            "bar_count": len(all_bar_avails),
            "series_count": len(bar_avails_by_key),
            "bounded_range_context_count": len(ranges),
            "exact_relevant_groups_measured": ["source", "group4", "group6"],
            "group7_not_measured_in_relevant_slice_diagnostic": True,
            "group6_current_breakout_enumeration": g6,
            "group6_cumulative_bar_boundary_evaluations": int(g6_pair_total),
            "bounded_range_current_bar_boundary_evaluations": int(range_raw_pairs),
            "bounded_range_valid_lifetime_bar_boundary_evaluations": int(range_valid_lifetime_pairs),
            "bounded_range_post_invalidation_bar_boundary_evaluations": stale_pairs,
            "bounded_range_post_invalidation_fraction": (stale_pairs / range_raw_pairs) if range_raw_pairs else 0.0,
            "bounded_range_invalidated_count": invalidated_ranges,
            "bounded_range_right_censored_count": right_censored_ranges,
            "bounded_range_invalidator_type_counts": dict(sorted(invalidator_type_counts.items())),
            "bounded_range_raw_evaluations_by_timeframe": dict(sorted(raw_by_tf.items())),
            "bounded_range_post_invalidation_evaluations_by_timeframe": dict(sorted(stale_by_tf.items())),
            "minimum_current_breakout_boundary_evaluations_from_group6_and_group8": int(g6_pair_total + range_raw_pairs),
            "observations": {
                "current_breakout_reads_group6_cumulatively_for_each_bar": True,
                "current_breakout_reads_all_prior_bounded_ranges_without_lifecycle_filter": True,
                "post_invalidation_bounded_range_evaluations_present": stale_pairs > 0,
                "definition_or_threshold_changed": False,
                "engine_changed": False,
                "schema_changed": False,
                "upstream_changed": False,
                "authorization_changed": False,
            },
            "method": {
                "group6": "exact count of frozen Group6 rows with availability_time <= each exact source bar.available_at, matching current _boundary_rows_for_bar Group6 predicates",
                "bounded_ranges_current": "exact pa_bounded_range_context output from frozen process_bounded_ranges over exact source+Group4, then exact count with same symbol/timeframe and availability_time <= each bar.available_at, matching current implementation",
                "bounded_ranges_valid_lifetime": "same pairs restricted to bars strictly before the first invalidation from the frozen pa_bounded_range_context invalidation rule; invalidation lookup matches first_bounded_range_invalidator ordering and strict-after creation semantics",
                "unused_groups": "Groups2/3/5/7 are deliberately not restored or measured because the selected diagnostic stages and the reported G6/G8 counts do not read them",
            },
        }
        report["report_hash"] = stable_hash(report)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
