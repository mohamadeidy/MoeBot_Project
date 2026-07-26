#!/usr/bin/env python3
"""Count PA7 transition events with only already-frozen causal boundary retirement.

Diagnostic scope: exact 2023 Source + Group4 + Group6 slices and exact Group8
bounded ranges. It applies no new boundary semantics. Retirement is used only
where the frozen contracts already provide causal evidence:
- Group4: expires_at / first causally inactive transition or interaction.
- Group6 FVG: first `traversed` transition with directional_validity=invalidated.
- Group8 bounded range: first invalidation of either locked Group4 zone.
Other Group6 objects remain right-censored because no causal retirement timestamp
is available in the frozen adapter. Group5/Group7 are empty in this diagnostic.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ENGINE_SHA = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class Fenwick:
    def __init__(self, n: int) -> None:
        self.bit = [0] * (n + 1)

    def add(self, i: int, delta: int) -> None:
        i += 1
        while i < len(self.bit):
            self.bit[i] += delta
            i += i & -i

    def prefix(self, n: int) -> int:
        out = 0
        i = n
        while i:
            out += self.bit[i]
            i -= i & -i
        return out

    def range(self, left: int, right: int) -> int:
        return self.prefix(right) - self.prefix(left)


@dataclass(frozen=True)
class Boundary:
    identity: str
    start: int
    lower: float
    upper: float
    inactive_at: int | None = None
    expires_at: int | None = None

    def active_at(self, t: int) -> bool:
        return self.start <= t and (self.inactive_at is None or t < self.inactive_at) and (self.expires_at is None or t <= self.expires_at)

    def removal_key(self) -> int | None:
        vals: list[int] = []
        if self.inactive_at is not None:
            vals.append(int(self.inactive_at))
        if self.expires_at is not None:
            vals.append(int(self.expires_at) + 1)
        return min(vals) if vals else None


def first_after(index: dict[str, tuple[list[int], list[int]]], object_id: str | None, after: int) -> int | None:
    if not object_id or object_id not in index:
        return None
    times, records = index[object_id]
    pos = bisect.bisect_right(times, int(after))
    return records[pos] if pos < len(records) else None


def build_group4_invalidation_index(engine: Any) -> dict[str, tuple[list[int], list[int]]]:
    invalidating: dict[str, list[int]] = defaultdict(list)
    for r in engine.input.execute("SELECT zone_id,transition_time,to_status FROM group4__zone_transitions ORDER BY zone_id,transition_time,transition_id"):
        if not engine._status_active(str(r[2])):
            invalidating[str(r[0])].append(int(r[1]))
    for r in engine.input.execute("SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions ORDER BY zone_id,interaction_time,interaction_id"):
        if not engine._status_active(str(r[2])):
            invalidating[str(r[0])].append(int(r[1]))
    out: dict[str, tuple[list[int], list[int]]] = {}
    for zone_id, vals in invalidating.items():
        vals.sort()
        out[zone_id] = (list(vals), list(vals))
    return out


def build_fvg_terminal_map(con: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for fvg_id, t in con.execute(
        "SELECT fvg_id,MIN(transition_time) FROM group6__fvg_state_transitions "
        "WHERE lower(event_type)='traversed' AND lower(directional_validity)='invalidated' GROUP BY fvg_id"
    ):
        out[str(fvg_id)] = int(t)
    return out


def count_initial(boundaries: Iterable[Boundary], close: float, *, variant: str, increment: float | None, atr: float | None, fraction: float) -> int:
    n = 0
    for b in boundaries:
        if variant == "exact":
            n += int(close > b.upper) + int(close < b.lower)
        elif variant == "point":
            if increment is None:
                continue
            n += int(close >= b.upper + increment) + int(close <= b.lower - increment)
        elif variant == "atr":
            if atr in (None, 0):
                continue
            buf = fraction * float(atr)
            n += int(close >= b.upper + buf) + int(close <= b.lower - buf)
        else:
            raise ValueError(variant)
    return n


def count_series(bars: list[Any], boundaries: list[Boundary], increment: float | None, atr_by_bar: dict[int, float | None], fraction: float) -> dict[str, int]:
    result = {"exact": 0, "point": 0, "atr": 0, "initialization": 0, "rearmed": 0, "total": 0}
    if not bars or not boundaries:
        return result

    starts = sorted(boundaries, key=lambda b: (b.start, b.identity))
    start_keys = [b.start for b in starts]
    removals = sorted((rk, b.identity) for b in boundaries if (rk := b.removal_key()) is not None)
    by_id = {b.identity: b for b in boundaries}
    upper_levels = sorted({b.upper for b in boundaries})
    lower_levels = sorted({b.lower for b in boundaries})
    upper_pos = {v: i for i, v in enumerate(upper_levels)}
    lower_pos = {v: i for i, v in enumerate(lower_levels)}
    up = Fenwick(len(upper_levels))
    lo = Fenwick(len(lower_levels))
    active_ids: set[str] = set()
    start_ptr = 0
    remove_ptr = 0

    def add_active(b: Boundary) -> None:
        if b.identity in active_ids:
            return
        active_ids.add(b.identity)
        up.add(upper_pos[b.upper], 1)
        lo.add(lower_pos[b.lower], 1)

    def remove_active(identity: str) -> None:
        if identity not in active_ids:
            return
        b = by_id[identity]
        active_ids.remove(identity)
        up.add(upper_pos[b.upper], -1)
        lo.add(lower_pos[b.lower], -1)

    first = bars[0]
    while remove_ptr < len(removals) and removals[remove_ptr][0] <= int(first.available_at):
        remove_ptr += 1
    initial: list[Boundary] = []
    while start_ptr < len(starts) and starts[start_ptr].start <= int(first.available_at):
        b = starts[start_ptr]
        if b.active_at(int(first.available_at)):
            initial.append(b)
            add_active(b)
        start_ptr += 1
    ca = atr_by_bar.get(int(first.id))
    for variant in ("exact", "point", "atr"):
        n = count_initial(initial, float(first.close), variant=variant, increment=increment, atr=ca, fraction=fraction)
        result[variant] += n
        result["initialization"] += n

    prev = first
    prev_atr = ca
    for bar in bars[1:]:
        t = int(bar.available_at)
        # A retirement available at the current bar must suppress a transition on that same bar.
        while remove_ptr < len(removals) and removals[remove_ptr][0] <= t:
            remove_active(removals[remove_ptr][1])
            remove_ptr += 1

        current_atr = atr_by_bar.get(int(bar.id))
        pclose = float(prev.close)
        cclose = float(bar.close)

        # Exact transition among identities eligible on both previous and current bars.
        if cclose > pclose:
            n = up.range(bisect.bisect_left(upper_levels, pclose), bisect.bisect_left(upper_levels, cclose))
            result["exact"] += n; result["rearmed"] += n
        elif cclose < pclose:
            n = lo.range(bisect.bisect_right(lower_levels, cclose), bisect.bisect_right(lower_levels, pclose))
            result["exact"] += n; result["rearmed"] += n

        if increment is not None:
            prev_adj = pclose - increment; cur_adj = cclose - increment
            if cur_adj > prev_adj:
                n = up.range(bisect.bisect_right(upper_levels, prev_adj), bisect.bisect_right(upper_levels, cur_adj)); result["point"] += n; result["rearmed"] += n
            prev_adj = pclose + increment; cur_adj = cclose + increment
            if cur_adj < prev_adj:
                n = lo.range(bisect.bisect_left(lower_levels, cur_adj), bisect.bisect_left(lower_levels, prev_adj)); result["point"] += n; result["rearmed"] += n

        if current_atr not in (None, 0):
            if prev_atr not in (None, 0):
                prev_adj = pclose - fraction * float(prev_atr); cur_adj = cclose - fraction * float(current_atr)
                if cur_adj > prev_adj:
                    n = up.range(bisect.bisect_right(upper_levels, prev_adj), bisect.bisect_right(upper_levels, cur_adj)); result["atr"] += n; result["rearmed"] += n
                prev_adj = pclose + fraction * float(prev_atr); cur_adj = cclose + fraction * float(current_atr)
                if cur_adj < prev_adj:
                    n = lo.range(bisect.bisect_left(lower_levels, cur_adj), bisect.bisect_left(lower_levels, prev_adj)); result["atr"] += n; result["rearmed"] += n
            else:
                # ATR variant becomes causally evaluable now: initialize all currently active older identities.
                buf = fraction * float(current_atr)
                bull = up.prefix(bisect.bisect_right(upper_levels, cclose - buf))
                bear = len(active_ids) - lo.prefix(bisect.bisect_left(lower_levels, cclose + buf))
                n = bull + bear
                result["atr"] += n; result["initialization"] += n

        # Boundaries becoming available after prev and by current bar initialize independently.
        new: list[Boundary] = []
        while start_ptr < len(starts) and starts[start_ptr].start <= t:
            b = starts[start_ptr]
            if b.start > int(prev.available_at) and b.active_at(t):
                new.append(b)
            start_ptr += 1
        for variant in ("exact", "point", "atr"):
            n = count_initial(new, cclose, variant=variant, increment=increment, atr=current_atr, fraction=fraction)
            result[variant] += n; result["initialization"] += n
        for b in new:
            add_active(b)

        prev = bar
        prev_atr = current_atr

    result["total"] = result["exact"] + result["point"] + result["atr"]
    return result


def sum_counts(records: Iterable[dict[str, int]]) -> dict[str, int]:
    keys = ("exact", "point", "atr", "initialization", "rearmed", "total")
    out = {k: 0 for k in keys}
    for r in records:
        for k in keys:
            out[k] += int(r.get(k, 0))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()
    if sha256_file(root / "code/moebot_group8_engine_v0_8_0.py") != ENGINE_SHA:
        raise SystemExit("unexpected amended engine identity")
    registry = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    status = json.loads((root / "STATUS.json").read_text())
    if registry.get("registry_hash") != REGISTRY_HASH or freeze.get("design_freeze_hash") != FREEZE_HASH:
        raise SystemExit("amended frozen identity mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("2023/2024 authorization boundary mismatch")

    import sys
    sys.path.insert(0, str(root / "code"))
    from moebot_group8_engine_v0_8_0 import Group8Engine

    a.output_db.unlink(missing_ok=True)
    engine = Group8Engine(staging_db=a.staging_db, output_db=a.output_db, artifacts_root=root, year=2023)
    try:
        engine.load_bars()
        engine.process_bounded_ranges()
        fraction = float(engine.config["pattern_thresholds"]["atr_buffer_breakout_fraction"])
        zone_invalidations = build_group4_invalidation_index(engine)
        fvg_terminal = build_fvg_terminal_map(engine.input)

        sources: dict[tuple[str, str], list[Boundary]] = defaultdict(list)
        # Group4 causal lifetime.
        for r in engine.input.execute("SELECT zone_id,symbol,timeframe,available_at,expires_at,lower,upper FROM group4__zones"):
            zid = str(r[0]); start = int(r[3]); inv = first_after(zone_invalidations, zid, start)
            sources[("group4_zones", str(r[2]))].append(Boundary(f"g4:{zid}", start, float(r[5]), float(r[6]), inv, int(r[4]) if r[4] is not None else None))

        # Group6 exact frozen adapter objects; only FVG has causal terminal transition evidence.
        for r in engine.input.execute("SELECT fvg_id,timeframe,availability_time,lower,upper FROM group6__fvg_events"):
            fid = str(r[0]); sources[("group6_fvg_events", str(r[1]))].append(Boundary(f"g6fvg:{fid}", int(r[2]), float(r[3]), float(r[4]), fvg_terminal.get(fid), None))
        for table, idc, label in [
            ("group6__imbalance_variants", "variant_id", "group6_imbalance_variants"),
            ("group6__liquidity_voids", "void_id", "group6_liquidity_voids"),
            ("group6__bpr_relations", "bpr_id", "group6_bpr_relations"),
        ]:
            for r in engine.input.execute(f"SELECT {idc},timeframe,availability_time,lower,upper FROM {table}"):
                sources[(label, str(r[1]))].append(Boundary(f"{label}:{r[0]}", int(r[2]), float(r[3]), float(r[4])))

        # Group8 bounded range causal lifetime from its already-frozen invalidation rule.
        for r in engine.out.execute("SELECT candidate_id,symbol,timeframe,availability_time,lower,upper,features_json FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'"):
            feats = json.loads(r[6]); start = int(r[3])
            invs = [first_after(zone_invalidations, feats.get("lower_zone_id"), start), first_after(zone_invalidations, feats.get("upper_zone_id"), start)]
            invs = [x for x in invs if x is not None]
            inv = min(invs) if invs else None
            sources[("group8_bounded_ranges", str(r[2]))].append(Boundary(f"g8range:{r[0]}", start, float(r[4]), float(r[5]), inv, None))

        by_source_tf: dict[str, dict[str, int]] = {}
        by_source: dict[str, list[dict[str, int]]] = defaultdict(list)
        all_counts: list[dict[str, int]] = []
        for (symbol, tf), bars in sorted(engine.bars_by_tf.items()):
            inc = engine.point_increment.get(symbol)
            for source in ("group4_zones", "group6_fvg_events", "group6_imbalance_variants", "group6_liquidity_voids", "group6_bpr_relations", "group8_bounded_ranges"):
                bnds = sources.get((source, tf), [])
                c = count_series(bars, bnds, inc, engine.atr_by_bar, fraction)
                by_source_tf[f"{source}::{tf}"] = {**c, "boundary_count": len(bnds)}
                by_source[source].append(c)
                all_counts.append(c)
        source_totals = {k: sum_counts(v) for k, v in sorted(by_source.items())}
        total = sum_counts(all_counts)

        old = json.loads((root / "reports/35_POSTFIX_BREAKOUT_CARDINALITY_DIAGNOSTIC.json").read_text())
        pre = int(old["minimum_group6_plus_group8_workload"]["candidate_total"])
        countonly_path = root / "reports/39A_PA7_TRANSITION_COUNTONLY_DIAGNOSTIC.json"
        current_countonly = json.loads(countonly_path.read_text()) if countonly_path.exists() else None
        current_total = int(current_countonly["transition_counts"]["total"]) if current_countonly else None

        report: dict[str, Any] = {
            "format_version": 1,
            "status": "PASS",
            "scope": "PA7_TRANSITION_LIFETIME_CARDINALITY_2023_SOURCE_GROUP4_GROUP6_GROUP8",
            "engine_sha256": ENGINE_SHA,
            "definition_registry_hash": REGISTRY_HASH,
            "design_freeze_hash": FREEZE_HASH,
            "bar_count": sum(len(v) for v in engine.bars_by_tf.values()),
            "fvg_terminal_transition_count": len(fvg_terminal),
            "bounded_range_count": sum(len(v) for (src, _tf), v in sources.items() if src == "group8_bounded_ranges"),
            "counts_by_source_timeframe": by_source_tf,
            "counts_by_source": source_totals,
            "lifecycle_aware_partial_total": total,
            "pre_amendment_group6_plus_group8_candidate_lower_bound": pre,
            "previous_transition_countonly_group6_plus_group8_total": current_total,
            "reduction_fraction_vs_pre_amendment_lower_bound": 1.0 - (total["total"] / pre) if pre else None,
            "causal_retirement_rules_applied": {
                "group4": "expires_at and first causally inactive transition/interaction already used by Group8 zone state logic",
                "group6_fvg_events": "first traversed transition with directional_validity=invalidated; transition_time is already consumed by Group8 ICT4 as event/confirmation/availability time",
                "group8_bounded_ranges": "first invalidation of either locked Group4 zone, matching frozen PA6G.1 invalidation rule",
                "group6_imbalance_variants": "right-censored; no causal retirement timestamp in frozen adapter",
                "group6_liquidity_voids": "right-censored; final state is not back-projected historically",
                "group6_bpr_relations": "right-censored; final state is not back-projected historically",
            },
            "observations": {
                "diagnostic_only": True,
                "no_new_lifecycle_semantics": True,
                "engine_changed": False,
                "definitions_changed": False,
                "thresholds_changed": False,
                "schema_changed": False,
                "upstream_changed": False,
                "authorization_changed": False,
                "oos_2024_accessed": False,
                "group5_group7_excluded_from_partial_scope": True,
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
