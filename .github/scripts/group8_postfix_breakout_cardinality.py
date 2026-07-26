#!/usr/bin/env python3
"""Measure residual PA7 workload after G8-PA7-CROSS-TIMEFRAME-006.

Uses exact authorized 2023 source/Group4/Group6 slices and corrected frozen engine.
It does not run the expensive breakout loop. Instead it reproduces its same-
timeframe Group6 and Group8 bounded-range availability/price predicates with an
offline Fenwick sweep, yielding exact boundary-enumeration and exact/point/ATR
candidate counts for those sources in O((bars+boundaries) log N).

This is diagnostic only: no design/config/schema/upstream/authorization mutation.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

EXPECTED_ENGINE_SHA256 = "f77252cc07c5d4e2fe6481a811441674983ec4d00c36c0c07f618950a4f4877d"
PRE_FIX_ENGINE_SHA256 = "61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
GROUP6_TABLES = (
    ("group6__fvg_events", "availability_time", "lower", "upper"),
    ("group6__imbalance_variants", "availability_time", "lower", "upper"),
    ("group6__liquidity_voids", "availability_time", "lower", "upper"),
    ("group6__bpr_relations", "availability_time", "lower", "upper"),
)


class Fenwick:
    def __init__(self, n: int) -> None:
        self.bit = [0] * (n + 1)

    def add(self, index: int, value: int = 1) -> None:
        i = index + 1
        while i < len(self.bit):
            self.bit[i] += value
            i += i & -i

    def prefix(self, count: int) -> int:
        """Sum first `count` compressed coordinates (exclusive end)."""
        out = 0
        i = count
        while i > 0:
            out += self.bit[i]
            i -= i & -i
        return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def count_stream(*, bars: list[Any], boundaries: list[tuple[int, float, float]], increment_by_symbol: dict[str, float | None], atr_by_bar: dict[int, float | None], atr_fraction: float) -> dict[str, int]:
    if not boundaries or not bars:
        return {"boundary_rows": len(boundaries), "enumerations": 0, "exact_candidates": 0, "point_buffer_candidates": 0, "atr_buffer_candidates": 0, "candidate_total": 0}

    boundaries = sorted(boundaries, key=lambda x: (x[0], x[1], x[2]))
    uppers = sorted({float(x[2]) for x in boundaries})
    lowers = sorted({float(x[1]) for x in boundaries})
    up_tree = Fenwick(len(uppers))
    lo_tree = Fenwick(len(lowers))
    pointer = 0
    active = 0
    enumerations = exact = point = atr_count = 0

    for bar in sorted(bars, key=lambda b: (int(b.available_at), int(b.id))):
        while pointer < len(boundaries) and int(boundaries[pointer][0]) <= int(bar.available_at):
            _, lo, hi = boundaries[pointer]
            up_tree.add(bisect.bisect_left(uppers, float(hi)))
            lo_tree.add(bisect.bisect_left(lowers, float(lo)))
            active += 1
            pointer += 1

        enumerations += active
        close = float(bar.close)
        bullish_exact = up_tree.prefix(bisect.bisect_left(uppers, close))
        bearish_exact = active - lo_tree.prefix(bisect.bisect_right(lowers, close))
        exact += bullish_exact + bearish_exact

        increment = increment_by_symbol.get(str(bar.symbol))
        if increment is not None and float(increment) >= 0.0:
            inc = float(increment)
            if inc > 0.0:
                bullish_point = up_tree.prefix(bisect.bisect_right(uppers, close - inc))
                bearish_point = active - lo_tree.prefix(bisect.bisect_left(lowers, close + inc))
            else:
                bullish_point = bullish_exact
                bearish_point = bearish_exact
            point += min(bullish_point, bullish_exact) + min(bearish_point, bearish_exact)

        atr = atr_by_bar.get(int(bar.id))
        if atr is not None and float(atr) > 0.0:
            buffer = atr_fraction * float(atr)
            bullish_atr = up_tree.prefix(bisect.bisect_right(uppers, close - buffer))
            bearish_atr = active - lo_tree.prefix(bisect.bisect_left(lowers, close + buffer))
            atr_count += min(bullish_atr, bullish_exact) + min(bearish_atr, bearish_exact)

    return {
        "boundary_rows": len(boundaries),
        "enumerations": int(enumerations),
        "exact_candidates": int(exact),
        "point_buffer_candidates": int(point),
        "atr_buffer_candidates": int(atr_count),
        "candidate_total": int(exact + point + atr_count),
    }


def sum_metrics(records: Iterable[dict[str, int]]) -> dict[str, int]:
    keys = ("boundary_rows", "enumerations", "exact_candidates", "point_buffer_candidates", "atr_buffer_candidates", "candidate_total")
    return {k: sum(int(r.get(k, 0)) for r in records) for k in keys}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    if a.year != 2023:
        raise SystemExit("post-fix workload diagnostic is intentionally 2023-only")

    root = a.group8_root.resolve()
    engine_path = root / "code" / "moebot_group8_engine_v0_8_0.py"
    if sha256_file(engine_path) != EXPECTED_ENGINE_SHA256:
        raise SystemExit("unexpected corrected engine identity")

    import sys
    sys.path.insert(0, str(root / "code"))
    from moebot_group8_engine_v0_8_0 import Group8Engine

    engine = Group8Engine(staging_db=a.staging_db, output_db=a.output_db, artifacts_root=root, year=2023)
    try:
        engine.load_bars()
        atr_fraction = float(engine.config["pattern_thresholds"]["atr_buffer_breakout_fraction"])
        all_bars_by_tf: dict[str, list[Any]] = defaultdict(list)
        for (_symbol, tf), bars in engine.bars_by_tf.items():
            all_bars_by_tf[str(tf)].extend(bars)

        group6_by_table: dict[str, dict[str, dict[str, int]]] = {}
        group6_totals: list[dict[str, int]] = []
        for table, av_col, lo_col, hi_col in GROUP6_TABLES:
            rows_by_tf: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
            for row in engine.input.execute(f'SELECT timeframe,"{av_col}","{lo_col}","{hi_col}" FROM "{table}" ORDER BY timeframe,"{av_col}"'):
                rows_by_tf[str(row[0])].append((int(row[1]), float(row[2]), float(row[3])))
            per_tf: dict[str, dict[str, int]] = {}
            for tf in sorted(set(rows_by_tf) | set(all_bars_by_tf)):
                result = count_stream(
                    bars=all_bars_by_tf.get(tf, []),
                    boundaries=rows_by_tf.get(tf, []),
                    increment_by_symbol=engine.point_increment,
                    atr_by_bar=engine.atr_by_bar,
                    atr_fraction=atr_fraction,
                )
                per_tf[tf] = result
                group6_totals.append(result)
            group6_by_table[table] = per_tf

        engine.process_bounded_ranges()
        range_rows_by_key: dict[tuple[str, str], list[tuple[int, float, float]]] = defaultdict(list)
        for row in engine.out.execute(
            "SELECT symbol,timeframe,availability_time,lower,upper FROM price_action_pattern_candidate "
            "WHERE definition_id='pa_bounded_range_context' ORDER BY symbol,timeframe,availability_time,candidate_id"
        ):
            range_rows_by_key[(str(row[0]), str(row[1]))].append((int(row[2]), float(row[3]), float(row[4])))
        range_by_series: dict[str, dict[str, int]] = {}
        range_totals: list[dict[str, int]] = []
        for key, bars in sorted(engine.bars_by_tf.items()):
            result = count_stream(
                bars=bars,
                boundaries=range_rows_by_key.get((str(key[0]), str(key[1])), []),
                increment_by_symbol=engine.point_increment,
                atr_by_bar=engine.atr_by_bar,
                atr_fraction=atr_fraction,
            )
            range_by_series[f"{key[0]}::{key[1]}"] = result
            range_totals.append(result)

        g6_total = sum_metrics(group6_totals)
        range_total = sum_metrics(range_totals)
        lower_bound = {k: g6_total[k] + range_total[k] for k in g6_total}
        pre = json.loads((root / "reports" / "31_BREAKOUT_CARDINALITY_DIAGNOSTIC.json").read_text())
        old_g6 = int(pre["group6_cumulative_bar_boundary_evaluations"])
        reduction = 1.0 - (g6_total["enumerations"] / old_g6) if old_g6 else 0.0

        report: dict[str, Any] = {
            "format_version": 1,
            "status": "PASS",
            "scope": "POST_G8_PA7_CROSS_TIMEFRAME_006_DIAGNOSTIC_ONLY",
            "year": 2023,
            "engine_sha256": EXPECTED_ENGINE_SHA256,
            "pre_fix_engine_sha256": PRE_FIX_ENGINE_SHA256,
            "bar_count": sum(len(v) for v in engine.bars_by_tf.values()),
            "series_count": len(engine.bars_by_tf),
            "atr_buffer_breakout_fraction": atr_fraction,
            "group6_by_table_and_timeframe": group6_by_table,
            "group6_same_timeframe_totals": g6_total,
            "group8_bounded_range_by_series": range_by_series,
            "group8_bounded_range_totals": range_total,
            "minimum_group6_plus_group8_workload": lower_bound,
            "pre_fix_group6_unfiltered_enumerations": old_g6,
            "post_fix_group6_same_timeframe_enumerations": g6_total["enumerations"],
            "group6_enumeration_reduction_fraction": reduction,
            "observations": {
                "same_timeframe_filter_measured": True,
                "candidate_counts_are_exact_for_group6_and_group8_sources": True,
                "group4_group5_group7_not_included_in_candidate_lower_bound": True,
                "engine_changed": False,
                "definitions_changed": False,
                "thresholds_changed": False,
                "schema_changed": False,
                "upstream_changed": False,
                "authorization_changed": False,
                "oos_2024_accessed": False,
            },
            "method": {
                "group6": "exact corrected same-timeframe availability predicates plus exact close-through/point-buffer/ATR-buffer predicates reproduced by offline Fenwick sweep",
                "group8_bounded_ranges": "exact frozen process_bounded_ranges output followed by exact current availability and breakout predicates reproduced by offline Fenwick sweep",
                "lower_bound": "Group4, Group5 and Group7 are intentionally excluded; therefore candidate and enumeration totals are a strict lower bound for complete PA7 workload",
            },
        }
        report["report_hash"] = stable_hash(report)
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
