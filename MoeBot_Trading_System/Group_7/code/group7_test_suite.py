#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from moebot_group7_engine import (
    BASE_DEFINITIONS,
    DEFINITIONS,
    Bar,
    Builder,
    Config,
    ReadOnlyInputs,
    ZoneRuntime,
    build,
    canonical_json,
    file_sha256,
    reconstruct_audit,
    sha256_text,
)

BASE = 1700000000
TF = 900


def make_source(path: Path, scale: float = 1.0, truncate_at: int | None = None) -> Dict[int, Tuple[float, float, float, float]]:
    rows = {
        1: (100.0, 100.5, 99.5, 100.2),
        2: (100.0, 100.6, 97.8, 99.4),       # bearish, dominant lower rejection wick
        3: (99.5, 102.2, 99.3, 101.8),       # bullish first impulse
        4: (101.8, 103.0, 101.2, 102.8),
        5: (102.8, 104.0, 102.5, 103.8),
        6: (103.5, 104.0, 99.8, 102.0),       # first touch of strict/body zone
        7: (99.0, 103.2, 98.8, 102.8),        # later bullish validated departure available here
        8: (102.5, 103.0, 97.4, 97.7),        # one-close invalidation, first close for broad zones
        9: (97.7, 98.0, 97.0, 97.2),          # second close invalidates broad zones
        10: (97.2, 99.2, 97.0, 99.0),         # bullish opposing candle before bearish leg
        11: (99.0, 99.2, 94.5, 95.0),         # bearish impulse
        12: (95.0, 95.5, 93.8, 94.2),         # bearish BOS leg available
        13: (94.2, 99.0, 94.0, 98.8),         # touches breaker range, not necessarily invalidates
        14: (98.8, 101.0, 98.0, 100.5),
        15: (100.5, 101.2, 99.8, 100.0),
        16: (100.0, 100.4, 99.0, 99.4),
        17: (99.4, 101.4, 99.2, 101.0),
        18: (101.0, 101.8, 100.6, 101.4),
        19: (101.4, 102.0, 100.8, 101.1),
        20: (101.1, 102.5, 100.9, 102.2),
        21: (102.2, 103.0, 101.5, 102.8),
        22: (102.8, 103.4, 102.0, 102.2),
        23: (102.2, 102.8, 101.0, 101.5),
        24: (101.5, 102.1, 100.5, 101.0),
        25: (101.0, 101.5, 99.5, 100.0),
        26: (100.0, 100.5, 99.0, 99.4),
        27: (99.4, 100.0, 98.8, 99.0),
        28: (99.0, 99.6, 98.4, 98.9),
        29: (98.9, 99.5, 98.0, 98.4),
        30: (98.4, 99.0, 97.5, 98.0),
    }
    if truncate_at is not None:
        rows = {k: v for k, v in rows.items() if k <= truncate_at}
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE bars(id INTEGER PRIMARY KEY,symbol TEXT,timeframe TEXT,open_time INTEGER,close_time INTEGER,available_at INTEGER,open REAL,high REAL,low REAL,close REAL,tick_volume INTEGER,spread_points INTEGER,broker_offset_seconds INTEGER,time_confidence TEXT,source_run_id TEXT,content_hash BLOB)")
    for i, values in rows.items():
        o, h, l, c = [x * scale for x in values]
        opent = BASE + (i - 1) * TF
        closet = opent + TF
        content = bytes.fromhex(sha256_text(canonical_json([i, o, h, l, c])))
        con.execute("INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, "XAUUSD_", "M15", opent, closet, closet, o, h, l, c, 100 + i, 10, 0, "synthetic", "g7_fixture", content))
    con.commit(); con.close()
    return rows


def leg_tuple(leg_id: str, direction: str, start_bar: int, end_bar: int, availability_bar: int,
              origin_bar: int, origin_start_bar: int, origin_end_bar: int,
              body_lower: float, body_upper: float, full_lower: float, full_upper: float,
              base_bars: int, impulse_bar: int, last_opposing: int | None,
              classification: str = "validated", uncertain: int = 0, scale: float = 1.0) -> Tuple[Any, ...]:
    features = {"fixture": True, "leg": leg_id}
    payload = {"leg_id": leg_id, "direction": direction, "availability_bar": availability_bar, "features": features}
    return (
        leg_id, "M15", "multi_candle", direction, start_bar, end_bar,
        BASE + (start_bar - 1) * TF, BASE + end_bar * TF,
        BASE + availability_bar * TF, BASE + availability_bar * TF,
        end_bar - start_bar + 1, origin_bar,
        BASE + (origin_start_bar - 1) * TF, BASE + origin_end_bar * TF,
        body_lower * scale, body_upper * scale, full_lower * scale, full_upper * scale,
        full_lower * scale, full_upper * scale, base_bars, impulse_bar, last_opposing,
        "origin_reference_only_not_order_block", classification, uncertain,
        canonical_json(features), sha256_text(canonical_json(features)), sha256_text(canonical_json(payload)),
    )


def make_group6(path: Path, scale: float = 1.0, include_late: bool = True) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE config_registry(config_id TEXT PRIMARY KEY,engine_version TEXT,schema_version TEXT,config_json TEXT,created_at INTEGER);
    CREATE TABLE dataset_registry(dataset_id TEXT PRIMARY KEY,year INTEGER,source_db TEXT,source_sha256 TEXT,symbol TEXT,created_at INTEGER);
    CREATE TABLE dependency_registry(dependency_id TEXT PRIMARY KEY,group_name TEXT,version TEXT,db_path TEXT,sha256 TEXT,read_only INTEGER,created_at INTEGER);
    CREATE TABLE displacement_legs(leg_id TEXT PRIMARY KEY,timeframe TEXT,leg_kind TEXT,direction TEXT,start_bar_id INTEGER,end_bar_id INTEGER,start_time INTEGER,end_time INTEGER,confirmation_time INTEGER,availability_time INTEGER,bar_count INTEGER,origin_bar_id INTEGER,origin_window_start INTEGER,origin_window_end INTEGER,body_lower REAL,body_upper REAL,wick_lower REAL,wick_upper REAL,full_lower REAL,full_upper REAL,base_duration_bars INTEGER,first_impulse_bar_id INTEGER,last_opposing_bar_id INTEGER,origin_label TEXT,initial_classification TEXT,uncertain INTEGER,features_json TEXT,feature_hash TEXT,record_hash TEXT);
    CREATE TABLE displacement_validation_events(validation_id TEXT PRIMARY KEY,leg_id TEXT NOT NULL,fvg_id TEXT,confirmation_bar_id INTEGER,confirmation_time INTEGER,availability_time INTEGER,validation_type TEXT,result TEXT,evidence_json TEXT,record_hash TEXT);
    CREATE TABLE fvg_events(fvg_id TEXT PRIMARY KEY,timeframe TEXT,direction TEXT,candle1_bar_id INTEGER,candle2_bar_id INTEGER,candle3_bar_id INTEGER,creation_time INTEGER,confirmation_time INTEGER,availability_time INTEGER,lower REAL,upper REAL,ce REAL,absolute_size REAL,size_points REAL,size_atr REAL,associated_leg_id TEXT,associated_group3_event_id TEXT,associated_group5_event_id TEXT,group2_state_id TEXT,group3_state_id TEXT,parent_zone_ids_json TEXT,clean_displacement INTEGER,formation_quality TEXT,features_json TEXT,feature_hash TEXT,record_hash TEXT);
    CREATE TABLE group6_evidence(evidence_id TEXT PRIMARY KEY,subject_type TEXT,subject_id TEXT,source_group TEXT,source_id TEXT,relation_type TEXT,source_timeframe TEXT,availability_time INTEGER,details_json TEXT,record_hash TEXT);
    """)
    con.execute("INSERT INTO config_registry VALUES(?,?,?,?,?)", ("cfg6_fixture", "0.6.4", "6.35.0", "{}", BASE))
    con.execute("INSERT INTO dataset_registry VALUES(?,?,?,?,?,?)", ("ds6_fixture", 2023, "fixture", sha256_text("source"), "XAUUSD_", BASE))
    for group, h in (("group2", "2" * 64), ("group3", "3" * 64), ("group4", "4" * 64), ("group5", "5" * 64)):
        con.execute("INSERT INTO dependency_registry VALUES(?,?,?,?,?,?,?)", (f"dep6_{group}", group, "frozen", f"/{group}.sqlite", h, 1, BASE))

    legs = [
        leg_tuple("legA", "bullish", 3, 5, 5, 2, 1, 2, 99.4, 100.2, 97.8, 100.6, 2, 3, 2, scale=scale),
        leg_tuple("legB", "bullish", 7, 7, 7, 6, 6, 6, 102.0, 103.5, 98.8, 103.5, 1, 7, 6, scale=scale),
        leg_tuple("legCandidate", "bullish", 17, 18, 18, 16, 15, 16, 99.4, 100.5, 99.0, 101.2, 2, 17, 16, classification="candidate", uncertain=1, scale=scale),
        leg_tuple("legNoOpp", "bearish", 20, 21, 21, 19, 19, 19, 101.0, 101.4, 100.8, 102.0, 1, 20, None, scale=scale),
    ]
    if include_late:
        legs.append(leg_tuple("legC", "bearish", 11, 12, 12, 10, 10, 10, 97.2, 99.0, 97.0, 99.2, 1, 11, 10, scale=scale))
        # Candidate is available at bar 18; definition evidence arrives later.
        legs.append(leg_tuple("legFuture", "bullish", 17, 18, 18, 2, 1, 2, 99.4, 100.2, 97.8, 100.6, 2, 17, 2, classification="candidate", uncertain=1, scale=scale))
        # Pending candidate never receives validation/FVG/BOS.
        legs.append(leg_tuple("legPending", "bullish", 18, 19, 19, 2, 1, 2, 99.4, 100.2, 97.8, 100.6, 2, 18, 2, classification="candidate", uncertain=1, scale=scale))
        # Zero-width origin proves a loose candidate may remain unmatched.
        legs.append(leg_tuple("legZero", "bullish", 19, 20, 20, 2, 2, 2, 100.0, 100.0, 100.0, 100.0, 2, 19, 2, classification="candidate", uncertain=1, scale=scale))
    con.executemany("INSERT INTO displacement_legs VALUES(" + ",".join("?" * 29) + ")", legs)

    def add_validation(vid: str, leg: str, bar: int, vtype: str = "multi_leg_confirmation", fvg_id: str | None = None):
        payload = {"validation": vid, "leg": leg, "bar": bar, "type": vtype}
        con.execute("INSERT INTO displacement_validation_events VALUES(?,?,?,?,?,?,?,?,?,?)", (
            vid, leg, fvg_id, bar, BASE + bar * TF, BASE + bar * TF, vtype, "validated",
            canonical_json({"fixture": True}), sha256_text(canonical_json(payload))
        ))
    add_validation("valA", "legA", 5)
    add_validation("valB", "legB", 7)
    if include_late:
        add_validation("valC", "legC", 12)
        add_validation("valFuture", "legFuture", 20, "classic_fvg_confirmation", "fvgFuture")

    def add_fvg(fid: str, leg: str, direction: str, bar: int, lo: float, hi: float):
        features = canonical_json({"fixture": True})
        payload = {"fvg": fid, "leg": leg}
        con.execute("INSERT INTO fvg_events VALUES(" + ",".join("?" * 26) + ")", (
            fid, "M15", direction, max(1, bar-2), max(1, bar-1), bar,
            BASE + bar * TF, BASE + bar * TF, BASE + bar * TF,
            lo * scale, hi * scale, ((lo+hi)/2) * scale, (hi-lo) * scale, (hi-lo)*100, 1.0,
            leg, f"g3_{leg}", f"g5_{leg}", None, None, "[]", 1, "clean", features,
            sha256_text(features), sha256_text(canonical_json(payload))
        ))
    add_fvg("fvgA", "legA", "bullish", 5, 100.6, 101.2)
    if include_late:
        add_fvg("fvgC", "legC", "bearish", 12, 95.5, 97.0)
        add_fvg("fvgFuture", "legFuture", "bullish", 21, 100.6, 101.2)

    def add_ev(eid: str, leg: str, group: str, source_id: str, relation: str, bar: int, details: Dict[str, Any]):
        payload = {"eid": eid, "leg": leg, "source": source_id, "availability": bar}
        con.execute("INSERT INTO group6_evidence VALUES(?,?,?,?,?,?,?,?,?,?)", (
            eid, "displacement_leg", leg, group, source_id, relation, "M15", BASE + bar * TF,
            canonical_json(details), sha256_text(canonical_json(payload))
        ))
    add_ev("evA_bos", "legA", "group3", "bosA", "associated_bos_mss_choch", 5, {"event_type": "BOS", "direction": "up"})
    add_ev("evA_liq", "legA", "group5", "sweepA", "preceding_liquidity_event", 4, {"event_type": "liquidity_grab", "side": "sell_side"})
    if include_late:
        add_ev("evC_mss", "legC", "group3", "mssC", "associated_bos_mss_choch", 12, {"event_type": "MSS", "direction": "down"})
        add_ev("evC_liq", "legC", "group5", "sweepC", "preceding_liquidity_event", 11, {"event_type": "stop_run", "side": "buy_side"})
        add_ev("evFuture_bos", "legFuture", "group3", "bosFuture", "associated_bos_mss_choch", 22, {"event_type": "BOS", "direction": "up"})
        add_ev("evFuture_liq", "legFuture", "group5", "sweepFuture", "preceding_liquidity_event", 23, {"event_type": "liquidity_grab", "side": "sell_side"})
    con.commit(); con.close()


def logical_snapshot(db: Path) -> Dict[str, List[Tuple[Any, ...]]]:
    con = sqlite3.connect(db)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    out = {}
    for table in tables:
        if table in ("metadata", "processing_checkpoints"):
            continue
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        ignore = {"created_at", "source_db", "group6_db"}
        use = [c for c in cols if c not in ignore]
        out[table] = con.execute(f"SELECT {','.join(use)} FROM {table} ORDER BY {','.join(use[:1])}").fetchall()
    con.close()
    return out



def run_lifecycle_exhaustive_reference(builder: Builder, zone_ids: List[str]) -> None:
    """Small-fixture oracle for the annual RTree lifecycle path."""
    selected = set(zone_ids)
    by_tf: Dict[str, List[ZoneRuntime]] = {}
    for zid in selected:
        tf = builder.zone_rows[zid]["timeframe"]
        by_tf.setdefault(tf, []).append(builder.runtimes[zid])
    for tf, runtimes in by_tf.items():
        runtimes.sort(key=lambda r: (r.availability_time, r.zone_id))
        active: List[ZoneRuntime] = []
        cursor = 0
        last_bar = None
        for bar in builder.inputs.bars_by_tf.get(tf, []):
            last_bar = bar
            while cursor < len(runtimes) and runtimes[cursor].availability_time < bar.close_time:
                active.append(runtimes[cursor]); cursor += 1
            for rt in list(active):
                if rt.status == "invalidated":
                    continue
                overlap = builder._overlap(bar, rt)
                if overlap:
                    if not rt.in_visit:
                        rt.in_visit = True
                        rt.visit_count += 1
                        rt.visit_start_time = bar.close_time
                        rt.visit_start_bar_id = bar.id
                        rt.visit_bar_count = 1
                        rt.visit_max_penetration = 0.0
                        rt.visit_mitigated = False
                        if rt.first_touch_time is None:
                            rt.first_touch_time = bar.close_time
                            rt.freshness = "tested"
                            rt.status = "tested_valid"
                            builder._transition(rt, bar, bar.close_time, "first_touch", {"edge_equality_is_touch": True})
                        else:
                            builder._transition(rt, bar, bar.close_time, "revisit", {})
                    else:
                        rt.visit_bar_count += 1
                    pen = builder._penetration(bar, rt)
                    if pen > rt.visit_max_penetration + 1e-12:
                        rt.visit_max_penetration = pen
                    if pen > rt.max_penetration + 1e-12:
                        rt.max_penetration = pen
                        builder._transition(rt, bar, bar.close_time, "penetration_advanced", {"penetration": round(pen, 8)})
                    if pen > 1e-12 and not rt.visit_mitigated:
                        rt.visit_mitigated = True
                        rt.mitigation_count += 1
                        builder._transition(rt, bar, bar.close_time, "mitigation_count_incremented", {"visit_ordinal": rt.visit_count})
                elif rt.in_visit:
                    builder._close_visit(rt, bar.close_time, False)
                    builder._transition(rt, bar, bar.close_time, "visit_ended", {})

                through = builder._close_through(bar, rt)
                if through:
                    rt.invalidation_streak += 1
                    if rt.invalidation_closes == 2 and rt.invalidation_streak == 1:
                        builder._transition(rt, bar, bar.close_time, "invalidation_candidate", {"required_closes": 2})
                    if rt.invalidation_streak >= rt.invalidation_closes:
                        if rt.in_visit:
                            builder._close_visit(rt, bar.close_time, False)
                        rt.status = "invalidated"
                        rt.freshness = "invalidated"
                        rt.invalidated_time = bar.close_time
                        builder._transition(rt, bar, bar.close_time, "invalidated", {"required_closes": rt.invalidation_closes, "wick_breach_alone_invalidates": False})
                else:
                    if rt.invalidation_streak > 0 and rt.invalidation_closes == 2:
                        builder._transition(rt, bar, bar.close_time, "invalidation_candidate_reset", {})
                    rt.invalidation_streak = 0
        for rt in runtimes:
            if rt.in_visit:
                builder._close_visit(rt, last_bar.close_time if last_bar else None, True)
                builder._transition(rt, last_bar, last_bar.close_time if last_bar else rt.availability_time, "visit_right_censored", {})

def run_suite(workdir: Path) -> Dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "source.sqlite"
    g6 = workdir / "group6.sqlite"
    out = workdir / "group7.sqlite"
    make_source(source)
    make_group6(g6)
    result = build(source, g6, out, recreate=True)
    tests: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    tests["build_integrity"] = result["integrity"] == "ok" and result["foreign_key_errors"] == 0
    tests["all_definitions_registered"] = con.execute("SELECT COUNT(*) FROM definition_registry").fetchone()[0] == len(DEFINITIONS)
    tests["all_base_definitions_evaluated_per_leg"] = con.execute("SELECT COUNT(*) FROM block_evaluations WHERE definition_id IN (%s)" % ",".join("?" * len(BASE_DEFINITIONS)), BASE_DEFINITIONS).fetchone()[0] == len(BASE_DEFINITIONS) * con.execute("SELECT COUNT(DISTINCT source_leg_id) FROM definition_candidates").fetchone()[0]
    passed_defs = {r[0] for r in con.execute("SELECT DISTINCT definition_id FROM block_evaluations WHERE passed=1")}
    tests["all_eight_definitions_have_passing_case"] = set(DEFINITIONS).issubset(passed_defs)
    tests["failed_cases_preserved"] = con.execute("SELECT COUNT(*) FROM block_evaluations WHERE passed=0").fetchone()[0] > 0

    # Exact definition ranges for legA.
    def zone(definition: str, leg: str = "legA"):
        return con.execute("SELECT * FROM institutional_zones WHERE definition_id=? AND source_leg_id=? ORDER BY availability_time LIMIT 1", (definition, leg)).fetchone()
    strict = zone("strict_order_block")
    loose = zone("loose_order_block")
    loc = zone("last_opposing_candle")
    rej = zone("rejection_block")
    prop = zone("propulsion_block")
    sd = zone("supply_demand_origin")
    tests["strict_exact_body_range"] = strict is not None and abs(strict["lower"] - 99.4) < 1e-9 and abs(strict["upper"] - 100.0) < 1e-9
    tests["loose_exact_origin_full_range"] = loose is not None and abs(loose["lower"] - 97.8) < 1e-9 and abs(loose["upper"] - 100.6) < 1e-9
    tests["last_opposing_exact_full_range"] = loc is not None and abs(loc["lower"] - 97.8) < 1e-9 and abs(loc["upper"] - 100.6) < 1e-9
    tests["rejection_wick_segment"] = rej is not None and abs(rej["lower"] - 97.8) < 1e-9 and abs(rej["upper"] - 99.4) < 1e-9
    tests["propulsion_first_impulse_body"] = prop is not None and abs(prop["lower"] - 99.5) < 1e-9 and abs(prop["upper"] - 101.8) < 1e-9
    tests["supply_demand_origin_range"] = sd is not None and sd["zone_label"] == "demand_origin" and abs(sd["lower"] - 97.8) < 1e-9

    breaker = con.execute("SELECT * FROM institutional_zones WHERE definition_id='breaker_block' ORDER BY availability_time LIMIT 1").fetchone()
    mitigation = con.execute("SELECT * FROM institutional_zones WHERE definition_id='mitigation_block' ORDER BY availability_time LIMIT 1").fetchone()
    tests["breaker_is_causal_derived_object"] = breaker is not None and breaker["parent_zone_id"] and breaker["direction"] == "bearish" and breaker["availability_time"] >= BASE + 12 * TF
    tests["mitigation_is_causal_derived_object"] = mitigation is not None and mitigation["parent_zone_id"] and mitigation["direction"] == "bullish" and mitigation["availability_time"] == BASE + 7 * TF

    tests["event_confirmation_availability_order"] = con.execute("SELECT COUNT(*) FROM institutional_zones WHERE event_time>confirmation_time OR confirmation_time>availability_time").fetchone()[0] == 0
    tests["no_transition_before_availability"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE t.transition_time<z.availability_time").fetchone()[0] == 0
    tests["one_close_invalidation"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE z.definition_id='strict_order_block' AND t.event_type='invalidated' AND t.transition_time=?", (BASE + 8 * TF,)).fetchone()[0] >= 1
    tests["two_close_invalidation_candidate"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE z.definition_id='loose_order_block' AND t.event_type='invalidation_candidate' AND t.transition_time=?", (BASE + 8 * TF,)).fetchone()[0] >= 1
    tests["two_close_final_invalidation"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE z.definition_id='loose_order_block' AND t.event_type='invalidated' AND t.transition_time=?", (BASE + 9 * TF,)).fetchone()[0] >= 1
    tests["wick_or_touch_not_automatic_invalidation"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions WHERE event_type='first_touch'").fetchone()[0] > 0 and con.execute("SELECT COUNT(*) FROM zone_state_transitions WHERE event_type='invalidated' AND transition_time=?", (BASE + 6 * TF,)).fetchone()[0] == 0
    eq_rt = ZoneRuntime(zone_id="eq", definition_id="strict_order_block", direction="bullish", lower=99.4, upper=100.0, availability_time=0, invalidation_closes=1, source_leg_id=None, parent_zone_id=None)
    eq_bar = Bar(id=999999, symbol="XAUUSD", timeframe="M15", open_time=BASE, close_time=BASE+TF, available_at=BASE+TF, open=100.0, high=100.2, low=99.0, close=99.4, content_hash="eq")
    tests["exact_equality_not_close_through"] = not Builder._close_through(eq_bar, eq_rt)
    tests["multi_bar_visit_duration_counted"] = (con.execute("SELECT COALESCE(MAX(duration_bars),0) FROM zone_visit_observations WHERE right_censored=0").fetchone()[0] or 0) >= 2
    tests["lifecycle_append_only_ordinals"] = con.execute("SELECT COUNT(*) FROM (SELECT zone_id,transition_ordinal,COUNT(*) n FROM zone_state_transitions GROUP BY 1,2 HAVING n!=1)").fetchone()[0] == 0
    tests["freshness_and_mitigation_counts"] = con.execute("SELECT COUNT(*) FROM zone_lifecycle_summary WHERE first_touch_time IS NOT NULL AND freshness IN ('tested','invalidated') AND mitigation_count>=1").fetchone()[0] > 0
    tests["features_payload_is_persisted"] = con.execute("SELECT COUNT(*) FROM block_evaluations WHERE features_json IS NULL OR length(features_json)<2 OR feature_hash IS NULL").fetchone()[0] == 0
    tests["fvg_bos_liquidity_evidence_separate"] = all(con.execute("SELECT COUNT(*) FROM zone_evidence WHERE evidence_type=?", (kind,)).fetchone()[0] > 0 for kind in ("fvg", "structure", "liquidity"))
    tests["definition_overlap_not_voting"] = con.execute("SELECT COUNT(*) FROM zone_relations WHERE relation_type='independent_definition_overlap' AND details_json LIKE '%no_voting_or_ranking%'").fetchone()[0] > 0

    # v0.7.5 causal candidate -> match lifecycle gates.
    tests["six_candidates"] = con.execute("SELECT COUNT(*) FROM (SELECT source_leg_id,COUNT(*) n FROM definition_candidates GROUP BY source_leg_id HAVING n!=6)").fetchone()[0] == 0
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tests["candidate_match_tables_separate"] = {"definition_candidates", "definition_matches"}.issubset(tables)
    candidate_cols = {r[1] for r in con.execute("PRAGMA table_info(definition_candidates)")}
    tests["immutable_origin_no_lifecycle"] = not ({"status", "freshness", "visit_count", "invalidated_time"} & candidate_cols)
    strict_future = con.execute("SELECT availability_time FROM definition_matches WHERE source_leg_id='legFuture' AND definition_id='strict_order_block'").fetchone()
    tests["strict_future_available_at_max"] = strict_future is not None and strict_future[0] == BASE + 22 * TF
    loose_future = con.execute("SELECT availability_time FROM definition_matches WHERE source_leg_id='legFuture' AND definition_id='loose_order_block'").fetchone()
    tests["loose_future_available_at_earliest"] = loose_future is not None and loose_future[0] == BASE + 18 * TF
    rejection_future = con.execute("SELECT availability_time FROM definition_matches WHERE source_leg_id='legFuture' AND definition_id='rejection_block'").fetchone()
    tests["rejection_future_validation"] = rejection_future is not None and rejection_future[0] == BASE + 20 * TF
    supply_future = con.execute("SELECT availability_time FROM definition_matches WHERE source_leg_id='legFuture' AND definition_id='supply_demand_origin'").fetchone()
    tests["supply_demand_future_max"] = supply_future is not None and supply_future[0] == BASE + 20 * TF
    tests["evidence_never_backdated"] = con.execute("SELECT COUNT(*) FROM zone_evidence e JOIN institutional_zones z USING(zone_id) WHERE e.availability_time<z.availability_time").fetchone()[0] == 0
    tests["zone_never_before_match"] = con.execute("SELECT COUNT(*) FROM institutional_zones z JOIN definition_matches m USING(match_id) WHERE z.availability_time<m.availability_time").fetchone()[0] == 0
    tests["strict_pending_no_match"] = con.execute("SELECT COUNT(*) FROM definition_matches WHERE source_leg_id='legPending' AND definition_id='strict_order_block'").fetchone()[0] == 0
    tests["loose_pending_no_match"] = con.execute("SELECT COUNT(*) FROM definition_matches WHERE source_leg_id='legZero' AND definition_id='loose_order_block'").fetchone()[0] == 0
    tests["supply_pending_no_match"] = con.execute("SELECT COUNT(*) FROM definition_matches WHERE source_leg_id='legPending' AND definition_id='supply_demand_origin'").fetchone()[0] == 0
    tests["immediate_reference_defs_still_match"] = con.execute("SELECT COUNT(*) FROM definition_matches WHERE source_leg_id='legPending' AND definition_id IN ('loose_order_block','last_opposing_candle') AND availability_time=?", (BASE + 19 * TF,)).fetchone()[0] == 2
    con.close()

    audit = reconstruct_audit(out)
    tests["independent_reconstruction_audit"] = audit["passed"]

    # Idempotent full reimport.
    reimport = build(source, g6, out, recreate=False)
    changed_tables = {k: v for k, v in reimport["inserted"].items() if v != 0}
    tests["idempotent_reimport_zero_records"] = not changed_tables
    details["reimport_nonzero"] = changed_tables

    # Deterministic complete rebuild.
    out2 = workdir / "group7_rebuild.sqlite"
    build(source, g6, out2, recreate=True)
    tests["deterministic_rebuild"] = logical_snapshot(out) == logical_snapshot(out2)

    # Restart at immutable stage boundary: serialize Builder after base evaluation and continue.
    inputs = ReadOnlyInputs(source, g6)
    b1 = Builder(inputs); b1.evaluate_base_definitions()
    import pickle
    b2 = pickle.loads(pickle.dumps(b1, protocol=5))
    base_ids = [z["zone_id"] for z in b2.zones]
    b2.run_lifecycle(base_ids); derived = b2.derive_breakers_and_mitigation(); b2.run_lifecycle(derived); b2.finalize_summaries()
    tests["restart_checkpoint_equivalence"] = sorted((z["zone_id"], z["creation_hash"]) for z in b2.zones) == sorted((r[0], r[1]) for r in sqlite3.connect(out).execute("SELECT zone_id,creation_hash FROM institutional_zones"))

    # Exact semantic oracle: indexed annual path must match exhaustive lifecycle.
    bref = Builder(ReadOnlyInputs(source, g6)); bref.evaluate_base_definitions()
    ref_base = [z["zone_id"] for z in bref.zones]
    run_lifecycle_exhaustive_reference(bref, ref_base)
    ref_derived = bref.derive_breakers_and_mitigation()
    run_lifecycle_exhaustive_reference(bref, ref_derived)
    bref.finalize_summaries()
    con_prod = sqlite3.connect(out); con_prod.row_factory = sqlite3.Row
    prod_transitions = [dict(r) for r in con_prod.execute("SELECT * FROM zone_state_transitions ORDER BY transition_id")]
    prod_visits = [dict(r) for r in con_prod.execute("SELECT * FROM zone_visit_observations ORDER BY visit_id")]
    prod_summaries = [dict(r) for r in con_prod.execute("SELECT * FROM zone_lifecycle_summary ORDER BY zone_id")]
    con_prod.close()
    tests["indexed_lifecycle_matches_exhaustive_reference"] = (
        sorted(bref.transitions, key=lambda r:r["transition_id"]) == prod_transitions and
        sorted(bref.visits, key=lambda r:r["visit_id"]) == prod_visits and
        sorted(bref.summaries, key=lambda r:r["zone_id"]) == prod_summaries
    )

    # Prefix/future append: base creation records available in prefix cannot change after late evidence is appended.
    src_prefix = workdir / "source_prefix.sqlite"; g6_prefix = workdir / "g6_prefix.sqlite"; out_prefix = workdir / "g7_prefix.sqlite"
    make_source(src_prefix, truncate_at=10); make_group6(g6_prefix, include_late=False); build(src_prefix, g6_prefix, out_prefix, recreate=True)
    cp = sqlite3.connect(out_prefix); cf = sqlite3.connect(out)
    prefix_rows = cp.execute("SELECT zone_id,creation_hash FROM institutional_zones WHERE definition_id NOT IN ('breaker_block','mitigation_block') AND source_leg_id IN ('legA','legB') ORDER BY zone_id").fetchall()
    full_subset = cf.execute("SELECT zone_id,creation_hash FROM institutional_zones WHERE definition_id NOT IN ('breaker_block','mitigation_block') AND source_leg_id IN ('legA','legB') ORDER BY zone_id").fetchall()
    cp.close(); cf.close()
    tests["future_append_does_not_repaint_base_objects"] = prefix_rows == full_subset

    # Price-scale invariance of categorical outputs and lifecycle sequence.
    src_scaled = workdir / "source_scaled.sqlite"; g6_scaled = workdir / "g6_scaled.sqlite"; out_scaled = workdir / "g7_scaled.sqlite"
    make_source(src_scaled, scale=10.0); make_group6(g6_scaled, scale=10.0); build(src_scaled, g6_scaled, out_scaled, recreate=True)
    c1 = sqlite3.connect(out); c2 = sqlite3.connect(out_scaled)
    d1 = c1.execute("SELECT definition_id,passed,COUNT(*) FROM block_evaluations GROUP BY 1,2 ORDER BY 1,2").fetchall()
    d2 = c2.execute("SELECT definition_id,passed,COUNT(*) FROM block_evaluations GROUP BY 1,2 ORDER BY 1,2").fetchall()
    l1 = c1.execute("SELECT z.definition_id,t.event_type,COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) GROUP BY 1,2 ORDER BY 1,2").fetchall()
    l2 = c2.execute("SELECT z.definition_id,t.event_type,COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) GROUP BY 1,2 ORDER BY 1,2").fetchall()
    c1.close(); c2.close()
    tests["price_scale_invariance"] = d1 == d2 and l1 == l2

    # Conflicting duplicate identity must be explicit.
    conflict_db = workdir / "conflict.sqlite"; shutil.copy2(out, conflict_db)
    cc = sqlite3.connect(conflict_db); cc.execute("UPDATE block_evaluations SET evaluation_hash='conflict' WHERE evaluation_id=(SELECT evaluation_id FROM block_evaluations LIMIT 1)"); cc.commit(); cc.close()
    conflict_raised = False
    try:
        build(source, g6, conflict_db, recreate=False)
    except ValueError:
        conflict_raised = True
    tests["conflicting_duplicate_rejected"] = conflict_raised

    details["result"] = result
    details["audit"] = audit
    details["passed_definitions"] = sorted(passed_defs)
    details["counts"] = logical_snapshot(out).keys()
    passed_count = sum(bool(v) for v in tests.values())
    return {"passed": all(tests.values()), "passed_count": passed_count, "total": len(tests), "tests": tests, "details": details, "paths": {"source": str(source), "group6": str(g6), "group7": str(out)}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir")
    parser.add_argument("--json-out")
    args = parser.parse_args()
    if args.workdir:
        workdir = Path(args.workdir)
        if workdir.exists(): shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        result = run_suite(workdir)
    else:
        with tempfile.TemporaryDirectory(prefix="g7tests_") as td:
            result = run_suite(Path(td))
    text = json.dumps(result, indent=2, sort_keys=True, default=list)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
