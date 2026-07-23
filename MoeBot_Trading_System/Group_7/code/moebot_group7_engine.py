#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import dataclasses
import hashlib
import json
import math
import os
import pickle
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ENGINE_VERSION = "0.7.5"
SCHEMA_VERSION = "7.5.0"
POINT_EPSILON = 1e-12

DEFINITIONS = {
    "strict_order_block": {
        "definition_version": "D1.0",
        "range_policy": "exact_last_opposing_candle_body",
        "invalidation_closes": 1,
        "derived": False,
    },
    "loose_order_block": {
        "definition_version": "D2.0",
        "range_policy": "neutral_origin_window_full_range",
        "invalidation_closes": 2,
        "derived": False,
    },
    "last_opposing_candle": {
        "definition_version": "D3.0",
        "range_policy": "exact_last_opposing_candle_full_range",
        "invalidation_closes": 1,
        "derived": False,
    },
    "breaker_block": {
        "definition_version": "D4.0",
        "range_policy": "inherited_parent_range",
        "invalidation_closes": 1,
        "derived": True,
    },
    "mitigation_block": {
        "definition_version": "D5.0",
        "range_policy": "parent_later_origin_intersection",
        "invalidation_closes": 1,
        "derived": True,
    },
    "rejection_block": {
        "definition_version": "D6.0",
        "range_policy": "dominant_rejection_wick_segment",
        "invalidation_closes": 1,
        "derived": False,
    },
    "propulsion_block": {
        "definition_version": "D7.0",
        "range_policy": "first_impulse_candle_body",
        "invalidation_closes": 1,
        "derived": False,
    },
    "supply_demand_origin": {
        "definition_version": "D8.0",
        "range_policy": "neutral_origin_window_full_range",
        "invalidation_closes": 2,
        "derived": False,
    },
}
BASE_DEFINITIONS = tuple(k for k, v in DEFINITIONS.items() if not v["derived"])
PARENT_DEFINITIONS = ("strict_order_block", "loose_order_block", "last_opposing_candle")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(value: Any) -> str:
    if isinstance(value, bytes):
        data = value
    else:
        data = str(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, payload: Any) -> str:
    return prefix + sha256_text(canonical_json(payload))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def roundf(value: Optional[float], digits: int = 8) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return lower if value < lower else upper if value > upper else value


@dataclass(frozen=True)
class Config:
    feature_round_digits: int = 8
    rejection_wick_ratio: float = 0.50
    rejection_close_half: float = 0.50
    supply_demand_min_base_bars: int = 2
    strict_requires_fvg: bool = True
    strict_requires_bos_or_mss: bool = True
    propulsion_requires_fvg: bool = True
    propulsion_requires_bos_or_mss: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Bar:
    id: int
    symbol: str
    timeframe: str
    open_time: int
    close_time: int
    available_at: int
    open: float
    high: float
    low: float
    close: float
    content_hash: str

    @property
    def body_lower(self) -> float:
        return min(self.open, self.close)

    @property
    def body_upper(self) -> float:
        return max(self.open, self.close)

    @property
    def direction(self) -> str:
        if self.close > self.open:
            return "bullish"
        if self.close < self.open:
            return "bearish"
        return "neutral"


@dataclass(frozen=True)
class Leg:
    leg_id: str
    timeframe: str
    leg_kind: str
    direction: str
    start_bar_id: int
    end_bar_id: int
    start_time: int
    end_time: int
    confirmation_time: int
    availability_time: int
    bar_count: int
    origin_bar_id: int
    origin_window_start: int
    origin_window_end: int
    body_lower: float
    body_upper: float
    wick_lower: float
    wick_upper: float
    full_lower: float
    full_upper: float
    base_duration_bars: int
    first_impulse_bar_id: int
    last_opposing_bar_id: Optional[int]
    origin_label: str
    initial_classification: str
    uncertain: int
    features_json: str
    feature_hash: str
    record_hash: str


@dataclass(frozen=True)
class FVG:
    fvg_id: str
    timeframe: str
    direction: str
    availability_time: int
    lower: float
    upper: float
    associated_leg_id: Optional[str]
    associated_group3_event_id: Optional[str]
    associated_group5_event_id: Optional[str]
    record_hash: str


@dataclass(frozen=True)
class ValidationEvent:
    validation_id: str
    leg_id: str
    fvg_id: Optional[str]
    confirmation_bar_id: Optional[int]
    confirmation_time: int
    availability_time: int
    validation_type: str
    result: str
    evidence_json: str
    record_hash: str

    @property
    def evidence(self) -> Dict[str, Any]:
        try:
            return json.loads(self.evidence_json or "{}")
        except json.JSONDecodeError:
            return {}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    subject_type: str
    subject_id: str
    source_group: str
    source_id: str
    relation_type: str
    source_timeframe: str
    availability_time: int
    details_json: str
    record_hash: str

    @property
    def details(self) -> Dict[str, Any]:
        try:
            return json.loads(self.details_json or "{}")
        except json.JSONDecodeError:
            return {}


@dataclass
class ZoneRuntime:
    zone_id: str
    definition_id: str
    direction: str
    lower: float
    upper: float
    availability_time: int
    invalidation_closes: int
    source_leg_id: Optional[str]
    parent_zone_id: Optional[str]
    status: str = "fresh_valid"
    freshness: str = "fresh"
    visit_count: int = 0
    mitigation_count: int = 0
    max_penetration: float = 0.0
    first_touch_time: Optional[int] = None
    invalidated_time: Optional[int] = None
    invalidation_streak: int = 0
    transition_ordinal: int = 0
    in_visit: bool = False
    visit_start_time: Optional[int] = None
    visit_start_bar_id: Optional[int] = None
    visit_bar_count: int = 0
    visit_max_penetration: float = 0.0
    visit_mitigated: bool = False


class ReadOnlyInputs:
    def __init__(self, source_db: Path, group6_db: Path):
        self.source_db = source_db
        self.group6_db = group6_db
        self.source_sha = file_sha256(source_db)
        self.group6_sha = file_sha256(group6_db)
        self.bars_by_id: Dict[int, Bar] = {}
        self.bars_by_tf: Dict[str, List[Bar]] = defaultdict(list)
        self.legs: List[Leg] = []
        self.legs_by_id: Dict[str, Leg] = {}
        self.fvgs_by_leg: Dict[str, List[FVG]] = defaultdict(list)
        self.validations_by_leg: Dict[str, List[ValidationEvent]] = defaultdict(list)
        self.evidence_by_leg: Dict[str, List[Evidence]] = defaultdict(list)
        self.g6_registry: Dict[str, Any] = {}
        self.g6_dependencies: List[Dict[str, Any]] = []
        self._load_source()
        self._load_group6()

    def _load_source(self) -> None:
        con = sqlite3.connect(f"file:{self.source_db}?mode=ro", uri=True)
        query = (
            "SELECT id,symbol,timeframe,open_time,close_time,available_at,open,high,low,close,"
            "lower(hex(content_hash)) FROM bars ORDER BY timeframe,open_time,id"
        )
        for row in con.execute(query):
            bar = Bar(*row)
            self.bars_by_id[bar.id] = bar
            self.bars_by_tf[bar.timeframe].append(bar)
        con.close()

    def _load_group6(self) -> None:
        con = sqlite3.connect(f"file:{self.group6_db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        required = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needed = {"displacement_legs", "fvg_events", "group6_evidence", "dataset_registry", "config_registry"}
        missing = sorted(needed - required)
        if missing:
            raise ValueError(f"Group 6 database missing required tables: {missing}")
        for row in con.execute("SELECT * FROM displacement_legs ORDER BY timeframe,availability_time,leg_id"):
            leg = Leg(**dict(row))
            if leg.origin_label != "origin_reference_only_not_order_block":
                raise ValueError(f"Non-neutral Group 6 origin label: {leg.leg_id}")
            self.legs.append(leg)
            self.legs_by_id[leg.leg_id] = leg
        qf = (
            "SELECT fvg_id,timeframe,direction,availability_time,lower,upper,associated_leg_id,"
            "associated_group3_event_id,associated_group5_event_id,record_hash FROM fvg_events "
            "WHERE associated_leg_id IS NOT NULL ORDER BY associated_leg_id,availability_time,fvg_id"
        )
        for row in con.execute(qf):
            fvg = FVG(*row)
            self.fvgs_by_leg[fvg.associated_leg_id].append(fvg)
        if "displacement_validation_events" in required:
            qv = (
                "SELECT validation_id,leg_id,fvg_id,confirmation_bar_id,confirmation_time,"
                "availability_time,validation_type,result,evidence_json,record_hash "
                "FROM displacement_validation_events ORDER BY leg_id,availability_time,validation_id"
            )
            for row in con.execute(qv):
                validation = ValidationEvent(*row)
                self.validations_by_leg[validation.leg_id].append(validation)
        qe = (
            "SELECT evidence_id,subject_type,subject_id,source_group,source_id,relation_type,"
            "source_timeframe,availability_time,details_json,record_hash FROM group6_evidence "
            "WHERE subject_type='displacement_leg' ORDER BY subject_id,availability_time,evidence_id"
        )
        for row in con.execute(qe):
            ev = Evidence(*row)
            self.evidence_by_leg[ev.subject_id].append(ev)
        self.g6_registry["datasets"] = [dict(r) for r in con.execute("SELECT * FROM dataset_registry")]
        self.g6_registry["configs"] = [dict(r) for r in con.execute("SELECT * FROM config_registry")]
        if "dependency_registry" in required:
            self.g6_dependencies = [dict(r) for r in con.execute("SELECT * FROM dependency_registry ORDER BY group_name,dependency_id")]
        con.close()

    def validation_events(self, leg: Leg) -> List[ValidationEvent]:
        events = [v for v in self.validations_by_leg.get(leg.leg_id, []) if str(v.result).lower() == "validated"]
        if events:
            return sorted(events, key=lambda v: (v.availability_time, v.validation_id))
        # Group 6 multi-candle legs are born validated at their causal confirmation.
        # This fallback is used only for old compatible fixtures lacking the additive table.
        if leg.initial_classification == "validated" and int(leg.uncertain) == 0:
            return [ValidationEvent(
                validation_id=stable_id("dv7compat_", {"leg": leg.leg_id, "time": leg.availability_time}),
                leg_id=leg.leg_id, fvg_id=None, confirmation_bar_id=leg.end_bar_id,
                confirmation_time=leg.confirmation_time, availability_time=leg.availability_time,
                validation_type="group6_initial_validated_compatibility", result="validated",
                evidence_json=canonical_json({"compatibility": True}), record_hash=leg.record_hash,
            )]
        return []

    def bos_mss_evidence(self, leg_id: str) -> List[Evidence]:
        out = []
        for ev in self.evidence_by_leg.get(leg_id, []):
            if ev.source_group != "group3":
                continue
            et = str(ev.details.get("event_type", "")).upper()
            if et in ("BOS", "MSS"):
                out.append(ev)
        return out

    def liquidity_evidence(self, leg_id: str) -> List[Evidence]:
        return [ev for ev in self.evidence_by_leg.get(leg_id, []) if ev.source_group == "group5"]


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config_registry(config_id TEXT PRIMARY KEY,engine_version TEXT NOT NULL,schema_version TEXT NOT NULL,config_json TEXT NOT NULL,config_hash TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dataset_registry(dataset_id TEXT PRIMARY KEY,source_db TEXT NOT NULL,source_sha256 TEXT NOT NULL,group6_db TEXT NOT NULL,group6_sha256 TEXT NOT NULL,symbol TEXT,created_at INTEGER NOT NULL,record_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dependency_registry(dependency_id TEXT PRIMARY KEY,group_name TEXT NOT NULL,version TEXT,sha256 TEXT NOT NULL,read_only INTEGER NOT NULL,transitive INTEGER NOT NULL,source_dependency_id TEXT,record_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS definition_registry(definition_id TEXT PRIMARY KEY,definition_version TEXT NOT NULL,derived INTEGER NOT NULL,range_policy TEXT NOT NULL,invalidation_closes INTEGER NOT NULL,definition_json TEXT NOT NULL,definition_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS definition_candidates(candidate_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,source_leg_id TEXT NOT NULL,candidate_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,lower REAL,upper REAL,source_bar_id INTEGER,intrinsic_pass INTEGER NOT NULL,reasons_json TEXT NOT NULL,features_json TEXT NOT NULL,feature_hash TEXT NOT NULL,candidate_hash TEXT NOT NULL,FOREIGN KEY(definition_id) REFERENCES definition_registry(definition_id));
CREATE TABLE IF NOT EXISTS definition_matches(match_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,definition_id TEXT NOT NULL,source_leg_id TEXT NOT NULL,match_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,evidence_availability_max INTEGER NOT NULL,evidence_json TEXT NOT NULL,evidence_ids_json TEXT NOT NULL,reasons_json TEXT NOT NULL,features_json TEXT NOT NULL,match_hash TEXT NOT NULL,FOREIGN KEY(candidate_id) REFERENCES definition_candidates(candidate_id),FOREIGN KEY(definition_id) REFERENCES definition_registry(definition_id));
CREATE TABLE IF NOT EXISTS block_evaluations(evaluation_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,source_leg_id TEXT,parent_zone_id TEXT,candidate_id TEXT,match_id TEXT,evaluation_time INTEGER NOT NULL,availability_time INTEGER,passed INTEGER NOT NULL,reasons_json TEXT NOT NULL,features_json TEXT NOT NULL,feature_hash TEXT NOT NULL,evaluation_hash TEXT NOT NULL,FOREIGN KEY(definition_id) REFERENCES definition_registry(definition_id),FOREIGN KEY(candidate_id) REFERENCES definition_candidates(candidate_id),FOREIGN KEY(match_id) REFERENCES definition_matches(match_id));
CREATE TABLE IF NOT EXISTS institutional_zones(zone_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,timeframe TEXT NOT NULL,direction TEXT NOT NULL,zone_label TEXT NOT NULL,lower REAL NOT NULL,upper REAL NOT NULL,event_time INTEGER NOT NULL,confirmation_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,source_leg_id TEXT,candidate_id TEXT,match_id TEXT,origin_bar_id INTEGER,origin_window_start INTEGER,origin_window_end INTEGER,source_bar_id INTEGER,parent_zone_id TEXT,creation_features_json TEXT NOT NULL,feature_hash TEXT NOT NULL,creation_hash TEXT NOT NULL,FOREIGN KEY(definition_id) REFERENCES definition_registry(definition_id),FOREIGN KEY(candidate_id) REFERENCES definition_candidates(candidate_id),FOREIGN KEY(match_id) REFERENCES definition_matches(match_id),FOREIGN KEY(parent_zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS zone_evidence(evidence_id TEXT PRIMARY KEY,zone_id TEXT NOT NULL,evidence_type TEXT NOT NULL,source_group TEXT NOT NULL,source_id TEXT NOT NULL,relation_type TEXT NOT NULL,availability_time INTEGER NOT NULL,details_json TEXT NOT NULL,evidence_hash TEXT NOT NULL,FOREIGN KEY(zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS zone_relations(relation_id TEXT PRIMARY KEY,subject_zone_id TEXT NOT NULL,object_zone_id TEXT NOT NULL,relation_type TEXT NOT NULL,availability_time INTEGER NOT NULL,overlap_ratio REAL,details_json TEXT NOT NULL,relation_hash TEXT NOT NULL,FOREIGN KEY(subject_zone_id) REFERENCES institutional_zones(zone_id),FOREIGN KEY(object_zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS zone_state_transitions(transition_id TEXT PRIMARY KEY,zone_id TEXT NOT NULL,transition_ordinal INTEGER NOT NULL,bar_id INTEGER,transition_time INTEGER NOT NULL,event_type TEXT NOT NULL,status TEXT NOT NULL,freshness TEXT NOT NULL,visit_count INTEGER NOT NULL,mitigation_count INTEGER NOT NULL,max_penetration REAL NOT NULL,details_json TEXT NOT NULL,transition_hash TEXT NOT NULL,UNIQUE(zone_id,transition_ordinal),FOREIGN KEY(zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS zone_visit_observations(visit_id TEXT PRIMARY KEY,zone_id TEXT NOT NULL,visit_ordinal INTEGER NOT NULL,start_bar_id INTEGER,start_time INTEGER NOT NULL,end_time INTEGER,duration_bars INTEGER,max_penetration REAL NOT NULL,mitigated INTEGER NOT NULL,right_censored INTEGER NOT NULL,visit_hash TEXT NOT NULL,UNIQUE(zone_id,visit_ordinal),FOREIGN KEY(zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS zone_lifecycle_summary(zone_id TEXT PRIMARY KEY,status TEXT NOT NULL,freshness TEXT NOT NULL,visit_count INTEGER NOT NULL,mitigation_count INTEGER NOT NULL,max_penetration REAL NOT NULL,first_touch_time INTEGER,invalidated_time INTEGER,summary_hash TEXT NOT NULL,FOREIGN KEY(zone_id) REFERENCES institutional_zones(zone_id));
CREATE TABLE IF NOT EXISTS group7_audit_evidence(audit_id TEXT PRIMARY KEY,check_name TEXT NOT NULL,status TEXT NOT NULL,scope TEXT NOT NULL,details_json TEXT NOT NULL,checked_at INTEGER NOT NULL,audit_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS processing_checkpoints(timeframe TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL,last_bar_id INTEGER,last_time INTEGER,snapshot_hash TEXT,updated_at INTEGER NOT NULL,PRIMARY KEY(timeframe,stage));
CREATE INDEX IF NOT EXISTS ix_candidate_leg_definition ON definition_candidates(source_leg_id,definition_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_match_leg_definition ON definition_matches(source_leg_id,definition_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_eval_leg_definition ON block_evaluations(source_leg_id,definition_id,passed);
CREATE INDEX IF NOT EXISTS ix_zone_tf_availability ON institutional_zones(timeframe,availability_time,zone_id);
CREATE INDEX IF NOT EXISTS ix_transition_zone_time ON zone_state_transitions(zone_id,transition_time,transition_ordinal);
CREATE INDEX IF NOT EXISTS ix_evidence_zone_time ON zone_evidence(zone_id,availability_time,evidence_id);
"""

TABLE_PK_HASH = {
    "config_registry": ("config_id", "config_hash"),
    "dataset_registry": ("dataset_id", "record_hash"),
    "dependency_registry": ("dependency_id", "record_hash"),
    "definition_registry": ("definition_id", "definition_hash"),
    "definition_candidates": ("candidate_id", "candidate_hash"),
    "definition_matches": ("match_id", "match_hash"),
    "block_evaluations": ("evaluation_id", "evaluation_hash"),
    "institutional_zones": ("zone_id", "creation_hash"),
    "zone_evidence": ("evidence_id", "evidence_hash"),
    "zone_relations": ("relation_id", "relation_hash"),
    "zone_state_transitions": ("transition_id", "transition_hash"),
    "zone_visit_observations": ("visit_id", "visit_hash"),
    "zone_lifecycle_summary": ("zone_id", "summary_hash"),
    "group7_audit_evidence": ("audit_id", "audit_hash"),
}


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")


def insert_checked(con: sqlite3.Connection, table: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    pk, hash_col = TABLE_PK_HASH[table]
    columns = list(rows[0].keys())
    sql = f"INSERT OR IGNORE INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})"
    before = con.total_changes
    con.executemany(sql, [[row[c] for c in columns] for row in rows])
    inserted = con.total_changes - before
    for row in rows:
        found = con.execute(f"SELECT {hash_col} FROM {table} WHERE {pk}=?", (row[pk],)).fetchone()
        if found is None:
            raise RuntimeError(f"Missing row after insert: {table}/{row[pk]}")
        if found[0] != row[hash_col]:
            raise ValueError(f"Conflicting deterministic identity: {table}/{row[pk]}")
    return inserted


class Builder:
    def __init__(self, inputs: ReadOnlyInputs, cfg: Config = Config()):
        self.inputs = inputs
        self.cfg = cfg
        cfg_json = canonical_json(cfg.to_dict())
        self.config_id = stable_id("cfg7_", {"engine": ENGINE_VERSION, "config": json.loads(cfg_json), "definitions": DEFINITIONS})
        self.dataset_id = stable_id("ds7_", {"source_sha256": inputs.source_sha, "group6_sha256": inputs.group6_sha})
        self.candidates: List[Dict[str, Any]] = []
        self.matches: List[Dict[str, Any]] = []
        self.evaluations: List[Dict[str, Any]] = []
        self.zones: List[Dict[str, Any]] = []
        self.zone_evidence: List[Dict[str, Any]] = []
        self.zone_relations: List[Dict[str, Any]] = []
        self.transitions: List[Dict[str, Any]] = []
        self.visits: List[Dict[str, Any]] = []
        self.summaries: List[Dict[str, Any]] = []
        self.runtimes: Dict[str, ZoneRuntime] = {}
        self.zone_rows: Dict[str, Dict[str, Any]] = {}
        self.leg_zones: Dict[str, List[str]] = defaultdict(list)

    def _candidate(self, definition_id: str, leg: Leg, lower: Optional[float], upper: Optional[float], source_bar_id: Optional[int], intrinsic_pass: bool, reasons: List[str], features: Dict[str, Any]) -> Dict[str, Any]:
        candidate_time = int(leg.availability_time)
        payload = {
            "config_id": self.config_id, "definition_id": definition_id, "source_leg_id": leg.leg_id,
            "candidate_time": candidate_time, "availability_time": candidate_time,
            "lower": roundf(lower), "upper": roundf(upper), "source_bar_id": source_bar_id,
            "intrinsic_pass": bool(intrinsic_pass), "reasons": reasons, "features": features,
            "upstream_leg_record_hash": leg.record_hash,
        }
        feature_json = canonical_json(features)
        row = {
            "candidate_id": stable_id("cand7_", payload), "definition_id": definition_id,
            "source_leg_id": leg.leg_id, "candidate_time": candidate_time, "availability_time": candidate_time,
            "lower": roundf(lower), "upper": roundf(upper), "source_bar_id": source_bar_id,
            "intrinsic_pass": int(intrinsic_pass), "reasons_json": canonical_json(reasons),
            "features_json": feature_json, "feature_hash": sha256_text(feature_json),
            "candidate_hash": sha256_text(canonical_json(payload)),
        }
        self.candidates.append(row)
        return row

    def _match(self, candidate: Dict[str, Any], leg: Leg, evidence: List[Tuple[str, int]], reasons: List[str], features: Dict[str, Any]) -> Dict[str, Any]:
        evidence = sorted((str(i), int(t)) for i, t in evidence)
        evidence_max = max([int(candidate["availability_time"])] + [t for _, t in evidence])
        payload = {
            "candidate_id": candidate["candidate_id"], "definition_id": candidate["definition_id"],
            "source_leg_id": leg.leg_id, "match_time": evidence_max, "availability_time": evidence_max,
            "evidence": evidence, "reasons": reasons, "features": features,
        }
        row = {
            "match_id": stable_id("match7_", payload), "candidate_id": candidate["candidate_id"],
            "definition_id": candidate["definition_id"], "source_leg_id": leg.leg_id,
            "match_time": evidence_max, "availability_time": evidence_max,
            "evidence_availability_max": evidence_max,
            "evidence_json": canonical_json(evidence),
            "evidence_ids_json": canonical_json([i for i, _ in evidence]),
            "reasons_json": canonical_json(reasons), "features_json": canonical_json(features),
            "match_hash": sha256_text(canonical_json(payload)),
        }
        self.matches.append(row)
        return row

    def _evaluation(self, definition_id: str, leg: Optional[Leg], passed: bool, reasons: List[str], features: Dict[str, Any], availability: Optional[int], parent_zone_id: Optional[str] = None, evaluation_time: Optional[int] = None, candidate_id: Optional[str] = None, match_id: Optional[str] = None) -> Dict[str, Any]:
        source_leg_id = leg.leg_id if leg else None
        evaluation_time = int(evaluation_time if evaluation_time is not None else (leg.availability_time if leg else availability or 0))
        payload = {
            "config_id": self.config_id,
            "definition_id": definition_id,
            "source_leg_id": source_leg_id,
            "parent_zone_id": parent_zone_id,
            "candidate_id": candidate_id,
            "match_id": match_id,
            "evaluation_time": evaluation_time,
            "availability_time": availability,
            "passed": bool(passed),
            "reasons": reasons,
            "features": features,
        }
        feature_json = canonical_json(features)
        row = {
            "evaluation_id": stable_id("eval7_", payload),
            "definition_id": definition_id,
            "source_leg_id": source_leg_id,
            "parent_zone_id": parent_zone_id,
            "candidate_id": candidate_id,
            "match_id": match_id,
            "evaluation_time": evaluation_time,
            "availability_time": availability,
            "passed": int(passed),
            "reasons_json": canonical_json(reasons),
            "features_json": feature_json,
            "feature_hash": sha256_text(feature_json),
            "evaluation_hash": sha256_text(canonical_json(payload)),
        }
        self.evaluations.append(row)
        return row

    def _zone(self, definition_id: str, leg: Leg, lower: float, upper: float, availability: int, source_bar_id: Optional[int], label: str, features: Dict[str, Any], parent_zone_id: Optional[str] = None, event_time: Optional[int] = None, confirmation_time: Optional[int] = None, candidate_id: Optional[str] = None, match_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not math.isfinite(lower) or not math.isfinite(upper) or upper - lower <= POINT_EPSILON:
            return None
        event_time = int(event_time if event_time is not None else leg.end_time)
        confirmation_time = int(confirmation_time if confirmation_time is not None else leg.confirmation_time)
        creation = {
            "config_id": self.config_id,
            "definition_id": definition_id,
            "definition_version": DEFINITIONS[definition_id]["definition_version"],
            "timeframe": leg.timeframe,
            "direction": leg.direction,
            "lower": roundf(lower),
            "upper": roundf(upper),
            "event_time": event_time,
            "confirmation_time": confirmation_time,
            "availability_time": int(availability),
            "source_leg_id": leg.leg_id,
            "candidate_id": candidate_id,
            "match_id": match_id,
            "source_bar_id": source_bar_id,
            "parent_zone_id": parent_zone_id,
            "features": features,
            "upstream_leg_record_hash": leg.record_hash,
        }
        zone_id = stable_id("zone7_", creation)
        feature_json = canonical_json(features)
        row = {
            "zone_id": zone_id,
            "definition_id": definition_id,
            "timeframe": leg.timeframe,
            "direction": leg.direction,
            "zone_label": label,
            "lower": roundf(lower),
            "upper": roundf(upper),
            "event_time": event_time,
            "confirmation_time": confirmation_time,
            "availability_time": int(availability),
            "source_leg_id": leg.leg_id,
            "candidate_id": candidate_id,
            "match_id": match_id,
            "origin_bar_id": leg.origin_bar_id,
            "origin_window_start": leg.origin_window_start,
            "origin_window_end": leg.origin_window_end,
            "source_bar_id": source_bar_id,
            "parent_zone_id": parent_zone_id,
            "creation_features_json": feature_json,
            "feature_hash": sha256_text(feature_json),
            "creation_hash": sha256_text(canonical_json(creation)),
        }
        if zone_id in self.zone_rows:
            return self.zone_rows[zone_id]
        self.zones.append(row)
        self.zone_rows[zone_id] = row
        self.leg_zones[leg.leg_id].append(zone_id)
        rt = ZoneRuntime(
            zone_id=zone_id,
            definition_id=definition_id,
            direction=leg.direction,
            lower=float(lower),
            upper=float(upper),
            availability_time=int(availability),
            invalidation_closes=int(DEFINITIONS[definition_id]["invalidation_closes"]),
            source_leg_id=leg.leg_id,
            parent_zone_id=parent_zone_id,
        )
        self.runtimes[zone_id] = rt
        self._transition(rt, None, int(availability), "created", {"creation": True})
        self._evidence(zone_id, "source_leg", "group6", leg.leg_id, "classified_from_frozen_displacement_leg", leg.availability_time, {"leg_record_hash": leg.record_hash, "origin_label": leg.origin_label})
        return row

    def _evidence(self, zone_id: str, evidence_type: str, source_group: str, source_id: str, relation: str, availability: int, details: Dict[str, Any]) -> None:
        availability = max(int(availability), int(self.zone_rows[zone_id]["availability_time"]))
        payload = {
            "zone_id": zone_id,
            "evidence_type": evidence_type,
            "source_group": source_group,
            "source_id": str(source_id),
            "relation_type": relation,
            "availability_time": int(availability),
            "details": details,
        }
        row = {
            "evidence_id": stable_id("zev7_", payload),
            "zone_id": zone_id,
            "evidence_type": evidence_type,
            "source_group": source_group,
            "source_id": str(source_id),
            "relation_type": relation,
            "availability_time": int(availability),
            "details_json": canonical_json(details),
            "evidence_hash": sha256_text(canonical_json(payload)),
        }
        self.zone_evidence.append(row)

    def _relation(self, subject: str, obj: str, relation_type: str, availability: int, overlap_ratio: Optional[float], details: Dict[str, Any]) -> None:
        if subject == obj:
            return
        payload = {"subject": subject, "object": obj, "relation_type": relation_type, "availability_time": int(availability), "overlap_ratio": roundf(overlap_ratio), "details": details}
        self.zone_relations.append({
            "relation_id": stable_id("zrel7_", payload),
            "subject_zone_id": subject,
            "object_zone_id": obj,
            "relation_type": relation_type,
            "availability_time": int(availability),
            "overlap_ratio": roundf(overlap_ratio),
            "details_json": canonical_json(details),
            "relation_hash": sha256_text(canonical_json(payload)),
        })

    def _transition(self, rt: ZoneRuntime, bar: Optional[Bar], transition_time: int, event_type: str, details: Dict[str, Any]) -> None:
        rt.transition_ordinal += 1
        payload = {
            "zone_id": rt.zone_id,
            "ordinal": rt.transition_ordinal,
            "bar_id": bar.id if bar else None,
            "transition_time": int(transition_time),
            "event_type": event_type,
            "status": rt.status,
            "freshness": rt.freshness,
            "visit_count": rt.visit_count,
            "mitigation_count": rt.mitigation_count,
            "max_penetration": roundf(rt.max_penetration),
            "details": details,
        }
        self.transitions.append({
            "transition_id": stable_id("ztr7_", payload),
            "zone_id": rt.zone_id,
            "transition_ordinal": rt.transition_ordinal,
            "bar_id": bar.id if bar else None,
            "transition_time": int(transition_time),
            "event_type": event_type,
            "status": rt.status,
            "freshness": rt.freshness,
            "visit_count": rt.visit_count,
            "mitigation_count": rt.mitigation_count,
            "max_penetration": roundf(rt.max_penetration),
            "details_json": canonical_json(details),
            "transition_hash": sha256_text(canonical_json(payload)),
        })

    def _qualifying_bos(self, leg: Leg) -> List[Evidence]:
        return self.inputs.bos_mss_evidence(leg.leg_id)

    def _qualifying_fvgs(self, leg: Leg) -> List[FVG]:
        return [f for f in self.inputs.fvgs_by_leg.get(leg.leg_id, []) if f.direction == leg.direction]

    def evaluate_base_definitions(self) -> None:
        for leg in self.inputs.legs:
            last = self.inputs.bars_by_id.get(leg.last_opposing_bar_id) if leg.last_opposing_bar_id is not None else None
            impulse = self.inputs.bars_by_id.get(leg.first_impulse_bar_id)
            fvgs = sorted(self._qualifying_fvgs(leg), key=lambda f: (f.availability_time, f.fvg_id))
            bos = sorted(self._qualifying_bos(leg), key=lambda e: (e.availability_time, e.evidence_id))
            validations = self.inputs.validation_events(leg)
            validation = validations[0] if validations else None
            fvg = fvgs[0] if fvgs else None
            structure = bos[0] if bos else None
            origin_width = leg.full_upper - leg.full_lower
            last_is_opposite = bool(last and ((leg.direction == "bullish" and last.direction == "bearish") or (leg.direction == "bearish" and last.direction == "bullish")))

            # D1 strict: origin candidate is immutable; the definition matches only
            # after validation, one directional FVG, and one BOS/MSS are all available.
            intrinsic = last_is_opposite and bool(last)
            cfeat = {"last_opposing": last_is_opposite, "last_opposing_bar_id": leg.last_opposing_bar_id}
            candidate = self._candidate("strict_order_block", leg, last.body_lower if last else None, last.body_upper if last else None, last.id if last else None, intrinsic, [] if intrinsic else ["missing_or_non_opposing_last_candle"], cfeat)
            reasons = []
            if not intrinsic: reasons.append("intrinsic_origin_failed")
            if validation is None: reasons.append("validation_not_yet_available")
            if fvg is None: reasons.append("fvg_not_yet_available")
            if structure is None: reasons.append("bos_or_mss_not_yet_available")
            passed = not reasons
            match = None
            feat = {**cfeat, "validation_id": validation.validation_id if validation else None, "fvg_id": fvg.fvg_id if fvg else None, "bos_mss_id": structure.source_id if structure else None}
            if passed:
                evidence = [(validation.validation_id, validation.availability_time), (fvg.fvg_id, fvg.availability_time), (structure.evidence_id, structure.availability_time)]
                match = self._match(candidate, leg, evidence, ["all_locked_conditions_pass"], feat)
            self._evaluation("strict_order_block", leg, passed, reasons or ["all_locked_conditions_pass"], feat, match["availability_time"] if match else None, evaluation_time=match["availability_time"] if match else leg.availability_time, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if passed and last and match:
                row = self._zone("strict_order_block", leg, last.body_lower, last.body_upper, match["availability_time"], last.id, "strict_order_block", feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, last, validations)

            # D2 loose: neutral origin is an immediate descriptive reference; no
            # final Group 6 classification is read back into the candidate.
            intrinsic = leg.initial_classification in ("candidate", "validated") and origin_width > POINT_EPSILON
            reasons = []
            if leg.initial_classification not in ("candidate", "validated"): reasons.append("unsupported_leg_classification")
            if origin_width <= POINT_EPSILON: reasons.append("zero_width_origin")
            feat = {"leg_classification_at_creation": leg.initial_classification, "origin_full_width": roundf(origin_width), "base_duration_bars": leg.base_duration_bars}
            candidate = self._candidate("loose_order_block", leg, leg.full_lower, leg.full_upper, leg.origin_bar_id, intrinsic, reasons, feat)
            match = self._match(candidate, leg, [(leg.leg_id, leg.availability_time)], ["neutral_origin_range_available"], feat) if intrinsic else None
            self._evaluation("loose_order_block", leg, intrinsic, reasons or ["neutral_origin_range_available"], feat, match["availability_time"] if match else None, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if intrinsic and match:
                row = self._zone("loose_order_block", leg, leg.full_lower, leg.full_upper, match["availability_time"], leg.origin_bar_id, "loose_order_block", feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, self.inputs.bars_by_id.get(leg.origin_bar_id), validations)

            # D3 exact last opposing candle: immediate reference definition.
            feat = {"last_opposing_bar_id": leg.last_opposing_bar_id, "last_direction": last.direction if last else None, "leg_direction": leg.direction}
            candidate = self._candidate("last_opposing_candle", leg, last.low if last else None, last.high if last else None, last.id if last else None, last_is_opposite, [] if last_is_opposite else ["missing_or_non_opposing_last_candle"], feat)
            match = self._match(candidate, leg, [(leg.leg_id, leg.availability_time)], ["exact_opposing_candle_confirmed_by_leg"], feat) if last_is_opposite else None
            self._evaluation("last_opposing_candle", leg, last_is_opposite, [] if last_is_opposite else ["missing_or_non_opposing_last_candle"], feat, match["availability_time"] if match else None, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if last_is_opposite and last and match:
                row = self._zone("last_opposing_candle", leg, last.low, last.high, match["availability_time"], last.id, "last_opposing_candle", feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, last, validations)

            # D6 rejection: wick geometry is intrinsic, but activation waits for
            # a causal Group 6 validation event.
            rejection_shape = False
            rejection_lower = rejection_upper = None
            rejection_feat: Dict[str, Any] = {"last_opposing_bar_id": leg.last_opposing_bar_id}
            if last_is_opposite and last:
                rng = max(last.high - last.low, POINT_EPSILON)
                lower_wick = (min(last.open, last.close) - last.low) / rng
                upper_wick = (last.high - max(last.open, last.close)) / rng
                close_loc = (last.close - last.low) / rng
                rejection_feat.update({"lower_wick_ratio": roundf(lower_wick), "upper_wick_ratio": roundf(upper_wick), "close_location": roundf(close_loc)})
                if leg.direction == "bullish":
                    rejection_shape = lower_wick >= self.cfg.rejection_wick_ratio and close_loc >= self.cfg.rejection_close_half
                    rejection_lower, rejection_upper = last.low, min(last.open, last.close)
                else:
                    rejection_shape = upper_wick >= self.cfg.rejection_wick_ratio and close_loc <= self.cfg.rejection_close_half
                    rejection_lower, rejection_upper = max(last.open, last.close), last.high
            candidate_reasons = [] if rejection_shape else (["missing_or_non_opposing_last_candle"] if not last_is_opposite else ["locked_rejection_shape_failed"])
            candidate = self._candidate("rejection_block", leg, rejection_lower, rejection_upper, last.id if last else None, rejection_shape, candidate_reasons, rejection_feat)
            reasons = list(candidate_reasons)
            if validation is None: reasons.append("validation_not_yet_available")
            passed = rejection_shape and validation is not None
            match = self._match(candidate, leg, [(validation.validation_id, validation.availability_time)], ["locked_rejection_shape_and_validation_pass"], {**rejection_feat, "validation_id": validation.validation_id}) if passed else None
            self._evaluation("rejection_block", leg, passed, reasons or ["locked_rejection_shape_and_validation_pass"], {**rejection_feat, "validation_id": validation.validation_id if validation else None}, match["availability_time"] if match else None, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if passed and rejection_lower is not None and rejection_upper is not None and match:
                feat = {**rejection_feat, "validation_id": validation.validation_id}
                row = self._zone("rejection_block", leg, rejection_lower, rejection_upper, match["availability_time"], last.id if last else None, "rejection_block", feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, last, validations)

            # D7 propulsion: first impulse geometry is intrinsic; activation waits
            # for validation + FVG + BOS/MSS, using one earliest deterministic item.
            impulse_aligned = bool(impulse and impulse.direction == leg.direction)
            candidate = self._candidate("propulsion_block", leg, impulse.body_lower if impulse else None, impulse.body_upper if impulse else None, impulse.id if impulse else None, impulse_aligned, [] if impulse_aligned else ["first_impulse_not_directionally_aligned"], {"first_impulse_bar_id": leg.first_impulse_bar_id, "impulse_aligned": impulse_aligned})
            reasons = []
            if not impulse_aligned: reasons.append("first_impulse_not_directionally_aligned")
            if validation is None: reasons.append("validation_not_yet_available")
            if fvg is None: reasons.append("fvg_not_yet_available")
            if structure is None: reasons.append("bos_or_mss_not_yet_available")
            passed = not reasons
            feat = {"first_impulse_bar_id": leg.first_impulse_bar_id, "impulse_aligned": impulse_aligned, "validation_id": validation.validation_id if validation else None, "fvg_id": fvg.fvg_id if fvg else None, "bos_mss_id": structure.source_id if structure else None}
            match = None
            if passed:
                match = self._match(candidate, leg, [(validation.validation_id, validation.availability_time), (fvg.fvg_id, fvg.availability_time), (structure.evidence_id, structure.availability_time)], ["all_locked_conditions_pass"], feat)
            self._evaluation("propulsion_block", leg, passed, reasons or ["all_locked_conditions_pass"], feat, match["availability_time"] if match else None, evaluation_time=match["availability_time"] if match else leg.availability_time, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if passed and impulse and match:
                row = self._zone("propulsion_block", leg, impulse.body_lower, impulse.body_upper, match["availability_time"], impulse.id, "propulsion_block", feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, impulse, validations)

            # D8 supply/demand origin: origin geometry is immutable; activation
            # waits for causal validation and never uses the final leg label early.
            intrinsic = leg.base_duration_bars >= self.cfg.supply_demand_min_base_bars and origin_width > POINT_EPSILON
            candidate_reasons = []
            if leg.base_duration_bars < self.cfg.supply_demand_min_base_bars: candidate_reasons.append("base_duration_below_minimum")
            if origin_width <= POINT_EPSILON: candidate_reasons.append("zero_width_origin")
            label = "demand_origin" if leg.direction == "bullish" else "supply_origin"
            cfeat = {"base_duration_bars": leg.base_duration_bars, "origin_full_width": roundf(origin_width), "label": label}
            candidate = self._candidate("supply_demand_origin", leg, leg.full_lower, leg.full_upper, leg.origin_bar_id, intrinsic, candidate_reasons, cfeat)
            reasons = list(candidate_reasons)
            if validation is None: reasons.append("validation_not_yet_available")
            passed = intrinsic and validation is not None
            feat = {**cfeat, "validation_id": validation.validation_id if validation else None}
            match = self._match(candidate, leg, [(validation.validation_id, validation.availability_time)], ["validated_multi_bar_origin"], feat) if passed else None
            self._evaluation("supply_demand_origin", leg, passed, reasons or ["validated_multi_bar_origin"], feat, match["availability_time"] if match else None, evaluation_time=match["availability_time"] if match else leg.availability_time, candidate_id=candidate["candidate_id"], match_id=match["match_id"] if match else None)
            if passed and match:
                row = self._zone("supply_demand_origin", leg, leg.full_lower, leg.full_upper, match["availability_time"], leg.origin_bar_id, label, feat, candidate_id=candidate["candidate_id"], match_id=match["match_id"])
                if row: self._attach_standard_evidence(row, leg, fvgs, bos, self.inputs.bars_by_id.get(leg.origin_bar_id), validations)

        self._make_sibling_relations()

    def _attach_standard_evidence(self, zone: Dict[str, Any], leg: Leg, fvgs: List[FVG], bos: List[Evidence], source_bar: Optional[Bar], validations: Optional[List[ValidationEvent]] = None) -> None:
        zid = zone["zone_id"]
        if source_bar:
            self._evidence(zid, "source_bar", "group1", str(source_bar.id), "exact_referenced_bar", max(source_bar.available_at, leg.availability_time), {"bar_hash": source_bar.content_hash, "ohlc": [source_bar.open, source_bar.high, source_bar.low, source_bar.close]})
        for validation in validations or []:
            self._evidence(zid, "validation", "group6", validation.validation_id, validation.validation_type, validation.availability_time, {"result": validation.result, "fvg_id": validation.fvg_id, "record_hash": validation.record_hash})
        for fvg in fvgs:
            overlap = max(0.0, min(zone["upper"], fvg.upper) - max(zone["lower"], fvg.lower))
            ratio = overlap / max(zone["upper"] - zone["lower"], POINT_EPSILON)
            self._evidence(zid, "fvg", "group6", fvg.fvg_id, "associated_fvg", max(zone["availability_time"], fvg.availability_time), {"overlap_ratio": roundf(ratio), "fvg_record_hash": fvg.record_hash})
        for ev in bos:
            self._evidence(zid, "structure", "group3", ev.source_id, "causal_bos_or_mss", max(zone["availability_time"], ev.availability_time), {"event_type": ev.details.get("event_type"), "group6_evidence_id": ev.evidence_id, "group6_evidence_hash": ev.record_hash})
        for ev in self.inputs.liquidity_evidence(leg.leg_id):
            self._evidence(zid, "liquidity", "group5", ev.source_id, ev.relation_type, max(zone["availability_time"], ev.availability_time), {"group6_evidence_id": ev.evidence_id, "details": ev.details})

    def _make_sibling_relations(self) -> None:
        for leg_id, zone_ids in self.leg_zones.items():
            ordered = sorted(zone_ids)
            for i, a in enumerate(ordered):
                za = self.zone_rows[a]
                for b in ordered[i + 1:]:
                    zb = self.zone_rows[b]
                    overlap = max(0.0, min(za["upper"], zb["upper"]) - max(za["lower"], zb["lower"]))
                    if overlap <= 0:
                        continue
                    denom = min(za["upper"] - za["lower"], zb["upper"] - zb["lower"])
                    ratio = overlap / max(denom, POINT_EPSILON)
                    availability = max(za["availability_time"], zb["availability_time"])
                    details = {"source_leg_id": leg_id, "no_voting_or_ranking": True}
                    self._relation(a, b, "independent_definition_overlap", availability, ratio, details)
                    self._relation(b, a, "independent_definition_overlap", availability, ratio, details)

    @staticmethod
    def _overlap(bar: Bar, rt: ZoneRuntime) -> bool:
        return bar.high >= rt.lower and bar.low <= rt.upper

    @staticmethod
    def _close_through(bar: Bar, rt: ZoneRuntime) -> bool:
        return bar.close < rt.lower if rt.direction == "bullish" else bar.close > rt.upper

    @staticmethod
    def _penetration(bar: Bar, rt: ZoneRuntime) -> float:
        width = max(rt.upper - rt.lower, POINT_EPSILON)
        if rt.direction == "bullish":
            return clip((rt.upper - max(bar.low, rt.lower)) / width)
        return clip((min(bar.high, rt.upper) - rt.lower) / width)

    def _close_visit(self, rt: ZoneRuntime, end_time: Optional[int], right_censored: bool) -> None:
        if not rt.in_visit or rt.visit_start_time is None:
            return
        duration = None if right_censored and end_time is None else max(1, rt.visit_bar_count)
        payload = {
            "zone_id": rt.zone_id,
            "visit_ordinal": rt.visit_count,
            "start_bar_id": rt.visit_start_bar_id,
            "start_time": rt.visit_start_time,
            "end_time": end_time,
            "duration_bars": duration,
            "max_penetration": roundf(rt.visit_max_penetration),
            "mitigated": int(rt.visit_mitigated),
            "right_censored": int(right_censored),
        }
        self.visits.append({
            "visit_id": stable_id("visit7_", payload),
            "zone_id": rt.zone_id,
            "visit_ordinal": rt.visit_count,
            "start_bar_id": rt.visit_start_bar_id,
            "start_time": rt.visit_start_time,
            "end_time": end_time,
            "duration_bars": duration,
            "max_penetration": roundf(rt.visit_max_penetration),
            "mitigated": int(rt.visit_mitigated),
            "right_censored": int(right_censored),
            "visit_hash": sha256_text(canonical_json(payload)),
        })
        rt.in_visit = False
        rt.visit_start_time = None
        rt.visit_start_bar_id = None
        rt.visit_bar_count = 0
        rt.visit_max_penetration = 0.0
        rt.visit_mitigated = False

    def run_lifecycle(self, zone_ids: Optional[List[str]] = None) -> None:
        """Run causal lifecycle with dynamic interval indexes.

        The original exhaustive implementation scanned every active zone on every
        closed bar. That path is semantically simple but annual-scale quadratic.
        This implementation keeps exact runtime values in Python and uses SQLite
        RTree indexes only to retrieve conservative candidate supersets. Every
        candidate is rechecked with exact double-precision comparisons before a
        transition is emitted, so RTree outward float rounding cannot change the
        classification.
        """
        selected = set(zone_ids) if zone_ids is not None else set(self.runtimes)
        by_tf: Dict[str, List[ZoneRuntime]] = defaultdict(list)
        for zid in selected:
            row = self.zone_rows[zid]
            by_tf[row["timeframe"]].append(self.runtimes[zid])

        for tf, runtimes in by_tf.items():
            runtimes.sort(key=lambda r: (r.availability_time, r.zone_id))
            rid_to_rt = {idx + 1: rt for idx, rt in enumerate(runtimes)}
            rt_to_rid = {rt.zone_id: rid for rid, rt in rid_to_rt.items()}
            index = sqlite3.connect(":memory:")
            index.execute("CREATE VIRTUAL TABLE active_bull USING rtree(rid,lo_min,lo_max,hi_min,hi_max)")
            index.execute("CREATE VIRTUAL TABLE active_bear USING rtree(rid,lo_min,lo_max,hi_min,hi_max)")

            def add_runtime(rt: ZoneRuntime) -> None:
                rid = rt_to_rid[rt.zone_id]
                table = "active_bull" if rt.direction == "bullish" else "active_bear"
                index.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?)", (rid, rt.lower, rt.lower, rt.upper, rt.upper))

            def remove_runtime(rt: ZoneRuntime) -> None:
                rid = rt_to_rid[rt.zone_id]
                table = "active_bull" if rt.direction == "bullish" else "active_bear"
                index.execute(f"DELETE FROM {table} WHERE rid=?", (rid,))

            def exact_overlaps(bar: Bar) -> List[ZoneRuntime]:
                ids = set()
                for table in ("active_bull", "active_bear"):
                    ids.update(r[0] for r in index.execute(
                        f"SELECT rid FROM {table} WHERE lo_min<=? AND hi_max>=?",
                        (bar.high, bar.low),
                    ))
                return [rid_to_rt[rid] for rid in sorted(ids) if self._overlap(bar, rid_to_rt[rid])]

            def exact_close_through(bar: Bar) -> List[ZoneRuntime]:
                # lo_max / hi_min create a conservative candidate superset despite
                # RTree's outward single-precision rounding. Exact logic is below.
                ids = set(r[0] for r in index.execute("SELECT rid FROM active_bull WHERE lo_max>?", (bar.close,)))
                ids.update(r[0] for r in index.execute("SELECT rid FROM active_bear WHERE hi_min<?", (bar.close,)))
                return [rid_to_rt[rid] for rid in sorted(ids) if self._close_through(bar, rid_to_rt[rid])]

            cursor = 0
            in_visit: set[str] = set()
            pending_invalidation: set[str] = set()
            bars = self.inputs.bars_by_tf.get(tf, [])
            last_bar: Optional[Bar] = None
            for bar in bars:
                last_bar = bar
                while cursor < len(runtimes) and runtimes[cursor].availability_time < bar.close_time:
                    add_runtime(runtimes[cursor])
                    cursor += 1

                overlapping = exact_overlaps(bar)
                overlap_ids = {rt.zone_id for rt in overlapping}

                # End visits first, matching the exhaustive state-machine order.
                for zid in sorted(in_visit - overlap_ids):
                    rt = self.runtimes[zid]
                    self._close_visit(rt, bar.close_time, False)
                    self._transition(rt, bar, bar.close_time, "visit_ended", {})
                    in_visit.discard(zid)

                for rt in overlapping:
                    if not rt.in_visit:
                        rt.in_visit = True
                        in_visit.add(rt.zone_id)
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
                            self._transition(rt, bar, bar.close_time, "first_touch", {"edge_equality_is_touch": True})
                        else:
                            self._transition(rt, bar, bar.close_time, "revisit", {})
                    else:
                        rt.visit_bar_count += 1
                    pen = self._penetration(bar, rt)
                    if pen > rt.visit_max_penetration + POINT_EPSILON:
                        rt.visit_max_penetration = pen
                    if pen > rt.max_penetration + POINT_EPSILON:
                        rt.max_penetration = pen
                        self._transition(rt, bar, bar.close_time, "penetration_advanced", {"penetration": roundf(pen)})
                    if pen > POINT_EPSILON and not rt.visit_mitigated:
                        rt.visit_mitigated = True
                        rt.mitigation_count += 1
                        self._transition(rt, bar, bar.close_time, "mitigation_count_incremented", {"visit_ordinal": rt.visit_count})

                through = exact_close_through(bar)
                through_ids = {rt.zone_id for rt in through}
                for zid in sorted(pending_invalidation - through_ids):
                    rt = self.runtimes[zid]
                    if rt.status != "invalidated" and rt.invalidation_streak > 0 and rt.invalidation_closes == 2:
                        self._transition(rt, bar, bar.close_time, "invalidation_candidate_reset", {})
                    rt.invalidation_streak = 0
                    pending_invalidation.discard(zid)

                for rt in through:
                    rt.invalidation_streak += 1
                    if rt.invalidation_closes == 2 and rt.invalidation_streak == 1:
                        pending_invalidation.add(rt.zone_id)
                        self._transition(rt, bar, bar.close_time, "invalidation_candidate", {"required_closes": 2})
                    if rt.invalidation_streak >= rt.invalidation_closes:
                        if rt.in_visit:
                            self._close_visit(rt, bar.close_time, False)
                            in_visit.discard(rt.zone_id)
                        rt.status = "invalidated"
                        rt.freshness = "invalidated"
                        rt.invalidated_time = bar.close_time
                        self._transition(rt, bar, bar.close_time, "invalidated", {"required_closes": rt.invalidation_closes, "wick_breach_alone_invalidates": False})
                        pending_invalidation.discard(rt.zone_id)
                        remove_runtime(rt)

            for zid in sorted(in_visit):
                rt = self.runtimes[zid]
                self._close_visit(rt, last_bar.close_time if last_bar else None, True)
                self._transition(rt, last_bar, last_bar.close_time if last_bar else rt.availability_time, "visit_right_censored", {})
            index.close()

    def derive_breakers_and_mitigation(self) -> List[str]:
        """Derive D4/D5 without quadratic parent×leg scans.

        Breakers use bisected lists of BOS/MSS-qualified opposite legs. Mitigation
        blocks use a static RTree over validated origin ranges and availability
        time, followed by exact price/time filtering and deterministic earliest
        selection. The indexes select candidates only; all semantic checks remain
        exact and causal in Python.
        """
        new_zone_ids: List[str] = []

        # Earliest breaker confirmation can be selected in O(log n) per canonical
        # parent because each entry already includes all mandatory evidence time.
        breaker_lists: Dict[Tuple[str, str], List[Tuple[int, str, Leg, List[Evidence]]]] = defaultdict(list)
        for leg in self.inputs.legs:
            bos = self._qualifying_bos(leg)
            if not bos:
                continue
            availability = max([leg.availability_time] + [e.availability_time for e in bos])
            breaker_lists[(leg.timeframe, leg.direction)].append((availability, leg.leg_id, leg, bos))
        breaker_keys: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
        for key, rows in breaker_lists.items():
            rows.sort(key=lambda x: (x[0], x[1]))
            breaker_keys[key] = [(x[0], x[1]) for x in rows]

        # Validated candidate origins for mitigation are indexed by price range and
        # availability. RTree coordinates are conservative only; exact doubles are
        # rechecked after retrieval.
        mitigation_index: Dict[Tuple[str, str], Tuple[sqlite3.Connection, Dict[int, Leg]]] = {}
        grouped_validated: Dict[Tuple[str, str], List[Leg]] = defaultdict(list)
        for leg in self.inputs.legs:
            if leg.initial_classification == "validated" and int(leg.uncertain) == 0 and leg.full_upper - leg.full_lower > POINT_EPSILON:
                grouped_validated[(leg.timeframe, leg.direction)].append(leg)
        for key, legs in grouped_validated.items():
            legs.sort(key=lambda l: (l.availability_time, l.leg_id))
            con = sqlite3.connect(":memory:")
            con.execute("CREATE VIRTUAL TABLE origins USING rtree(rid,lo_min,lo_max,hi_min,hi_max,t_min,t_max)")
            mapping: Dict[int, Leg] = {}
            con.executemany(
                "INSERT INTO origins VALUES(?,?,?,?,?,?,?)",
                [
                    (idx, leg.full_lower, leg.full_lower, leg.full_upper, leg.full_upper, leg.availability_time, leg.availability_time)
                    for idx, leg in enumerate(legs, 1)
                ],
            )
            mapping.update({idx: leg for idx, leg in enumerate(legs, 1)})
            mitigation_index[key] = (con, mapping)

        parent_rows = [z for z in list(self.zones) if z["definition_id"] in PARENT_DEFINITIONS]
        breaker_priority = {"strict_order_block": 0, "last_opposing_candle": 1, "loose_order_block": 2}
        canonical_breaker_parent: Dict[str, str] = {}
        for candidate in sorted(parent_rows, key=lambda z: (z["source_leg_id"], breaker_priority[z["definition_id"]], z["zone_id"])):
            canonical_breaker_parent.setdefault(candidate["source_leg_id"], candidate["zone_id"])

        for parent in parent_rows:
            prt = self.runtimes[parent["zone_id"]]

            # D4 breaker: earliest causally available opposite BOS/MSS leg after
            # parent invalidation; only the semantic-priority parent creates it.
            breaker_leg = None
            breaker_bos: List[Evidence] = []
            breaker_availability = None
            is_canonical_parent = canonical_breaker_parent.get(parent["source_leg_id"]) == parent["zone_id"]
            if is_canonical_parent and prt.invalidated_time is not None:
                opposite = "bearish" if parent["direction"] == "bullish" else "bullish"
                key = (parent["timeframe"], opposite)
                rows = breaker_lists.get(key, [])
                keys = breaker_keys.get(key, [])
                pos = bisect.bisect_right(keys, (prt.invalidated_time, "\uffff"))
                if pos < len(rows):
                    breaker_availability, _, breaker_leg, breaker_bos = rows[pos]
            passed = breaker_leg is not None
            if not is_canonical_parent:
                reasons = ["non_canonical_parent_definition_priority"]
            else:
                reasons = ["parent_invalidated_and_later_opposite_bos_or_mss"] if passed else ["no_causal_later_opposite_bos_or_mss_after_parent_invalidation"]
            features = {
                "parent_zone_id": parent["zone_id"],
                "parent_invalidated_time": prt.invalidated_time,
                "confirming_leg_id": breaker_leg.leg_id if breaker_leg else None,
                "bos_mss_ids": [e.source_id for e in breaker_bos],
            }
            self._evaluation("breaker_block", breaker_leg, passed, reasons, features, breaker_availability, parent["zone_id"], prt.invalidated_time or parent["availability_time"])
            if breaker_leg and breaker_availability is not None:
                row = self._zone("breaker_block", breaker_leg, parent["lower"], parent["upper"], breaker_availability, parent["source_bar_id"], "breaker_block", features, parent["zone_id"], prt.invalidated_time, breaker_availability)
                if row:
                    zid = row["zone_id"]
                    new_zone_ids.append(zid)
                    self._evidence(zid, "parent_zone", "group7", parent["zone_id"], "derived_after_parent_invalidation", prt.invalidated_time, {"parent_definition": parent["definition_id"]})
                    for ev in breaker_bos:
                        self._evidence(zid, "structure", "group3", ev.source_id, "opposite_bos_or_mss_after_parent_invalidation", ev.availability_time, {"event_type": ev.details.get("event_type")})
                    self._relation(zid, parent["zone_id"], "breaker_of", breaker_availability, 1.0, {"parent_invalidated_time": prt.invalidated_time})

            # D5 mitigation: earliest exact overlapping same-direction validated
            # origin after first touch and strictly before parent invalidation.
            mitigation_leg = None
            if prt.first_touch_time is not None:
                indexed = mitigation_index.get((parent["timeframe"], parent["direction"]))
                if indexed:
                    con, mapping = indexed
                    params: List[Any] = [parent["upper"], parent["lower"], prt.first_touch_time]
                    sql = "SELECT rid FROM origins WHERE lo_min<=? AND hi_max>=? AND t_max>?"
                    if prt.invalidated_time is not None:
                        sql += " AND t_min<?"
                        params.append(prt.invalidated_time)
                    exact: List[Leg] = []
                    for (rid,) in con.execute(sql, params):
                        leg = mapping[rid]
                        if leg.availability_time <= prt.first_touch_time:
                            continue
                        if prt.invalidated_time is not None and leg.availability_time >= prt.invalidated_time:
                            continue
                        overlap = min(parent["upper"], leg.full_upper) - max(parent["lower"], leg.full_lower)
                        if overlap > POINT_EPSILON:
                            exact.append(leg)
                    if exact:
                        mitigation_leg = min(exact, key=lambda l: (l.availability_time, l.leg_id))
            passed = mitigation_leg is not None
            reasons = ["first_visit_then_same_direction_validated_departure"] if passed else ["no_same_direction_validated_departure_after_first_visit"]
            if mitigation_leg:
                lower = max(parent["lower"], mitigation_leg.full_lower)
                upper = min(parent["upper"], mitigation_leg.full_upper)
                availability = mitigation_leg.availability_time
            else:
                lower = upper = availability = None
            features = {
                "parent_zone_id": parent["zone_id"],
                "parent_first_touch_time": prt.first_touch_time,
                "confirming_leg_id": mitigation_leg.leg_id if mitigation_leg else None,
                "intersection": [roundf(lower), roundf(upper)] if mitigation_leg else None,
            }
            self._evaluation("mitigation_block", mitigation_leg, passed, reasons, features, availability, parent["zone_id"], prt.first_touch_time or parent["availability_time"])
            if mitigation_leg and lower is not None and upper is not None:
                row = self._zone("mitigation_block", mitigation_leg, lower, upper, availability, mitigation_leg.origin_bar_id, "mitigation_block", features, parent["zone_id"], prt.first_touch_time, mitigation_leg.confirmation_time)
                if row:
                    zid = row["zone_id"]
                    new_zone_ids.append(zid)
                    self._evidence(zid, "parent_zone", "group7", parent["zone_id"], "derived_after_parent_first_visit", prt.first_touch_time, {"parent_definition": parent["definition_id"]})
                    self._evidence(zid, "confirming_leg", "group6", mitigation_leg.leg_id, "same_direction_validated_departure", mitigation_leg.availability_time, {"leg_record_hash": mitigation_leg.record_hash})
                    self._relation(zid, parent["zone_id"], "mitigation_of", availability, (upper - lower) / max(parent["upper"] - parent["lower"], POINT_EPSILON), {})

        for con, _ in mitigation_index.values():
            con.close()
        return sorted(set(new_zone_ids))

    def finalize_summaries(self) -> None:
        self.summaries = []
        for zid, rt in sorted(self.runtimes.items()):
            payload = {
                "zone_id": zid,
                "status": rt.status,
                "freshness": rt.freshness,
                "visit_count": rt.visit_count,
                "mitigation_count": rt.mitigation_count,
                "max_penetration": roundf(rt.max_penetration),
                "first_touch_time": rt.first_touch_time,
                "invalidated_time": rt.invalidated_time,
            }
            self.summaries.append({**payload, "summary_hash": sha256_text(canonical_json(payload))})

    def build_records(self) -> None:
        self.evaluate_base_definitions()
        base_ids = [z["zone_id"] for z in self.zones]
        self.run_lifecycle(base_ids)
        derived = self.derive_breakers_and_mitigation()
        if derived:
            self.run_lifecycle(derived)
        self.finalize_summaries()

    def persist(self, out_db: Path, recreate: bool = True) -> Dict[str, Any]:
        if recreate and out_db.exists():
            out_db.unlink()
        con = sqlite3.connect(out_db)
        init_db(con)
        now = int(time.time())
        cfg_json = canonical_json({"config": self.cfg.to_dict(), "definitions": DEFINITIONS, "scope_exclusions": ["BUY/SELL/WAIT", "entries/SL/TP", "PnL/MFE/MAE", "future-return selection", "upstream redefinition"]})
        registry_rows = {
            "config_registry": [{"config_id": self.config_id, "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_json": cfg_json, "config_hash": sha256_text(cfg_json), "created_at": now}],
            "dataset_registry": [],
            "dependency_registry": [],
            "definition_registry": [],
        }
        ds_payload = {"dataset_id": self.dataset_id, "source_sha256": self.inputs.source_sha, "group6_sha256": self.inputs.group6_sha}
        registry_rows["dataset_registry"].append({"dataset_id": self.dataset_id, "source_db": self.inputs.source_db.name, "source_sha256": self.inputs.source_sha, "group6_db": self.inputs.group6_db.name, "group6_sha256": self.inputs.group6_sha, "symbol": next(iter(self.inputs.bars_by_id.values())).symbol if self.inputs.bars_by_id else None, "created_at": now, "record_hash": sha256_text(canonical_json(ds_payload))})
        direct_payload = {"group_name": "group6", "sha256": self.inputs.group6_sha, "read_only": 1, "transitive": 0}
        registry_rows["dependency_registry"].append({"dependency_id": stable_id("dep7_", direct_payload), "group_name": "group6", "version": "0.6.4", "sha256": self.inputs.group6_sha, "read_only": 1, "transitive": 0, "source_dependency_id": None, "record_hash": sha256_text(canonical_json(direct_payload))})
        for dep in self.inputs.g6_dependencies:
            payload = {"group_name": dep.get("group_name"), "sha256": dep.get("sha256"), "read_only": 1, "transitive": 1, "source_dependency_id": dep.get("dependency_id")}
            registry_rows["dependency_registry"].append({"dependency_id": stable_id("dep7_", payload), "group_name": dep.get("group_name"), "version": dep.get("version"), "sha256": dep.get("sha256"), "read_only": 1, "transitive": 1, "source_dependency_id": dep.get("dependency_id"), "record_hash": sha256_text(canonical_json(payload))})
        for definition_id, spec in DEFINITIONS.items():
            spec_json = canonical_json(spec)
            registry_rows["definition_registry"].append({"definition_id": definition_id, "definition_version": spec["definition_version"], "derived": int(spec["derived"]), "range_policy": spec["range_policy"], "invalidation_closes": spec["invalidation_closes"], "definition_json": spec_json, "definition_hash": sha256_text(spec_json)})

        counts: Dict[str, int] = {}
        for table, rows in registry_rows.items():
            counts[table] = insert_checked(con, table, rows)
        for table, rows in (
            ("definition_candidates", self.candidates),
            ("definition_matches", self.matches),
            ("block_evaluations", self.evaluations),
            ("institutional_zones", self.zones),
            ("zone_evidence", self.zone_evidence),
            ("zone_relations", self.zone_relations),
            ("zone_state_transitions", self.transitions),
            ("zone_visit_observations", self.visits),
            ("zone_lifecycle_summary", self.summaries),
        ):
            counts[table] = insert_checked(con, table, rows)
        for tf, bars in self.inputs.bars_by_tf.items():
            last = bars[-1] if bars else None
            snap = sha256_text(canonical_json({"tf": tf, "zones": sorted(z for z, row in self.zone_rows.items() if row["timeframe"] == tf), "summaries": sorted((s["zone_id"], s["summary_hash"]) for s in self.summaries if self.zone_rows[s["zone_id"]]["timeframe"] == tf)}))
            con.execute("INSERT OR REPLACE INTO processing_checkpoints VALUES(?,?,?,?,?,?,?)", (tf, "complete", "completed", last.id if last else None, last.close_time if last else None, snap, now))
        con.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("status", "completed"))
        con.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("engine_version", ENGINE_VERSION))
        con.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("schema_version", SCHEMA_VERSION))
        con.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("config_id", self.config_id))
        con.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("dataset_id", self.dataset_id))
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = len(con.execute("PRAGMA foreign_key_check").fetchall())
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
        con.close()
        return {"inserted": counts, "integrity": integrity, "foreign_key_errors": fk_errors, "config_id": self.config_id, "dataset_id": self.dataset_id, "zones": len(self.zones), "evaluations": len(self.evaluations)}


def reconstruct_audit(db: Path) -> Dict[str, Any]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    result: Dict[str, Any] = {"integrity": con.execute("PRAGMA integrity_check").fetchone()[0], "foreign_key_errors": len(con.execute("PRAGMA foreign_key_check").fetchall())}
    result["counts"] = {}
    for table in TABLE_PK_HASH:
        result["counts"][table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    checks: Dict[str, int] = {}
    checks["zone_invalid_bounds"] = con.execute("SELECT COUNT(*) FROM institutional_zones WHERE upper<=lower").fetchone()[0]
    checks["zone_before_confirmation"] = con.execute("SELECT COUNT(*) FROM institutional_zones WHERE availability_time<confirmation_time").fetchone()[0]
    checks["candidate_count_mismatch"] = con.execute("SELECT ABS((SELECT COUNT(*) FROM definition_candidates) - (SELECT COUNT(*) FROM (SELECT DISTINCT source_leg_id FROM definition_candidates))*?)", (len(BASE_DEFINITIONS),)).fetchone()[0]
    checks["match_before_candidate"] = con.execute("SELECT COUNT(*) FROM definition_matches m JOIN definition_candidates c USING(candidate_id) WHERE m.availability_time<c.availability_time").fetchone()[0]
    checks["match_before_evidence"] = con.execute("SELECT COUNT(*) FROM definition_matches WHERE availability_time<evidence_availability_max").fetchone()[0]
    checks["zone_before_match"] = con.execute("SELECT COUNT(*) FROM institutional_zones z JOIN definition_matches m USING(match_id) WHERE z.availability_time<m.availability_time").fetchone()[0]
    checks["base_zone_without_match"] = con.execute("SELECT COUNT(*) FROM institutional_zones WHERE definition_id IN (%s) AND match_id IS NULL" % ",".join("?" for _ in BASE_DEFINITIONS), BASE_DEFINITIONS).fetchone()[0]
    checks["evidence_before_zone"] = con.execute("SELECT COUNT(*) FROM zone_evidence e JOIN institutional_zones z USING(zone_id) WHERE e.availability_time<z.availability_time").fetchone()[0]
    checks["transition_before_availability"] = con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE t.transition_time<z.availability_time").fetchone()[0]
    checks["missing_summary"] = con.execute("SELECT COUNT(*) FROM institutional_zones z LEFT JOIN zone_lifecycle_summary s USING(zone_id) WHERE s.zone_id IS NULL").fetchone()[0]
    checks["non_read_only_dependency"] = con.execute("SELECT COUNT(*) FROM dependency_registry WHERE read_only!=1").fetchone()[0]
    checks["definitions_missing"] = len(DEFINITIONS) - con.execute("SELECT COUNT(*) FROM definition_registry").fetchone()[0]
    checks["signals_present"] = sum(con.execute("SELECT COUNT(*) FROM sqlite_master WHERE lower(sql) LIKE ?", (f"%{word.lower()}%",)).fetchone()[0] for word in ("profit", "mfe", "mae"))

    hash_errors = 0
    # Reconstruct all rows whose hash is canonical over visible payloads.
    for row in con.execute("SELECT * FROM zone_lifecycle_summary"):
        payload = {k: row[k] for k in ("zone_id", "status", "freshness", "visit_count", "mitigation_count", "max_penetration", "first_touch_time", "invalidated_time")}
        if sha256_text(canonical_json(payload)) != row["summary_hash"]:
            hash_errors += 1
    for row in con.execute("SELECT * FROM zone_visit_observations"):
        payload = {k: row[k] for k in ("zone_id", "visit_ordinal", "start_bar_id", "start_time", "end_time", "duration_bars", "max_penetration", "mitigated", "right_censored")}
        if sha256_text(canonical_json(payload)) != row["visit_hash"]:
            hash_errors += 1
    for row in con.execute("SELECT * FROM zone_state_transitions"):
        payload = {"zone_id": row["zone_id"], "ordinal": row["transition_ordinal"], "bar_id": row["bar_id"], "transition_time": row["transition_time"], "event_type": row["event_type"], "status": row["status"], "freshness": row["freshness"], "visit_count": row["visit_count"], "mitigation_count": row["mitigation_count"], "max_penetration": row["max_penetration"], "details": json.loads(row["details_json"])}
        if sha256_text(canonical_json(payload)) != row["transition_hash"]:
            hash_errors += 1
    checks["reconstruction_hash_errors"] = hash_errors
    result["checks"] = checks
    result["passed"] = result["integrity"] == "ok" and result["foreign_key_errors"] == 0 and all(v == 0 for v in checks.values())
    con.close()
    return result


def build(source_db: Path, group6_db: Path, out_db: Path, recreate: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    inputs = ReadOnlyInputs(source_db, group6_db)
    builder = Builder(inputs)
    builder.build_records()
    persisted = builder.persist(out_db, recreate=recreate)
    audit = reconstruct_audit(out_db)
    return {**persisted, "audit": audit, "elapsed_seconds": round(time.time() - t0, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description="MoeBot Group 7 — Blocks and Institutional Zones")
    sub = parser.add_subparsers(dest="command", required=True)
    pbuild = sub.add_parser("build")
    pbuild.add_argument("--source", required=True)
    pbuild.add_argument("--group6", required=True)
    pbuild.add_argument("--out", required=True)
    preimport = sub.add_parser("reimport")
    preimport.add_argument("--source", required=True)
    preimport.add_argument("--group6", required=True)
    preimport.add_argument("--out", required=True)
    paudit = sub.add_parser("audit")
    paudit.add_argument("--db", required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build(Path(args.source), Path(args.group6), Path(args.out), recreate=True)
    elif args.command == "reimport":
        result = build(Path(args.source), Path(args.group6), Path(args.out), recreate=False)
    else:
        result = reconstruct_audit(Path(args.db))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
