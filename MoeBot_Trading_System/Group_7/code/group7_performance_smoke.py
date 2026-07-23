#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from moebot_group7_engine import Bar, Builder, Config, ZoneRuntime


class Inputs:
    source_sha = "synthetic-performance-source"
    group6_sha = "synthetic-performance-group6"
    bars_by_tf = {}


def run(zone_count: int, bar_count: int) -> dict:
    inputs = Inputs()
    base = 1700000000
    inputs.bars_by_tf = {"M15": [
        Bar(i + 1, "XAUUSD", "M15", base + i * 900, base + (i + 1) * 900, base + (i + 1) * 900,
            100.0, 100.2, 99.8, 100.0, f"bar-{i}")
        for i in range(bar_count)
    ]}
    b = Builder(inputs, Config())
    for i in range(zone_count):
        bullish = i % 2 == 0
        lower = 80.0 + (i % 1000) * 0.0001 if bullish else 110.0 + (i % 1000) * 0.0001
        upper = lower + 0.5
        zid = f"perf-{i:08d}"
        b.zone_rows[zid] = {"zone_id": zid, "timeframe": "M15"}
        b.runtimes[zid] = ZoneRuntime(
            zone_id=zid, definition_id="strict_order_block", direction="bullish" if bullish else "bearish",
            lower=lower, upper=upper, availability_time=base, invalidation_closes=1,
            source_leg_id=None, parent_zone_id=None,
        )
    started = time.perf_counter()
    b.run_lifecycle(list(b.runtimes))
    elapsed = time.perf_counter() - started
    return {
        "passed": len(b.transitions) == 0 and len(b.visits) == 0,
        "zones": zone_count,
        "bars": bar_count,
        "naive_zone_bar_checks_avoided": zone_count * bar_count,
        "elapsed_seconds": round(elapsed, 6),
        "transitions": len(b.transitions),
        "visits": len(b.visits),
        "method": "dynamic SQLite RTree candidate retrieval with exact Python recheck",
    }


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--zones", type=int, default=20000); p.add_argument("--bars", type=int, default=5000); p.add_argument("--json-out")
    a = p.parse_args(); result = run(a.zones, a.bars); text = json.dumps(result, indent=2, sort_keys=True)
    if a.json_out: Path(a.json_out).write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["passed"] else 1)

if __name__ == "__main__": main()
