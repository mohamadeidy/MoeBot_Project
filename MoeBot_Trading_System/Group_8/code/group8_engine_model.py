#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from group8_engine_core import canonical_hash, canonical_json, deterministic_id

ENGINE_VERSION = "0.8.0"
SCHEMA_VERSION = "8.0.0"
SCHOOLS = {
    "classical_price_action": ("1.0.0", "Classical Price Action"),
    "dow_theory": ("1.0.0", "Dow / Structural Interpretation"),
    "wyckoff": ("1.0.0", "Wyckoff Hypothesis Layer"),
    "ict_smc": ("1.0.0", "ICT / SMC Interpretation Layer"),
}
PATTERN_KINDS = {
    "base_pattern", "bar_relation", "candle_shape", "context_pattern", "derived_context",
    "boundary_event", "derived_boundary_event", "visit_event",
}
TERMINAL_G4_STATUSES = {"broken", "expired", "superseded"}
ACCEPTED_G3_OUTCOME = "accepted"


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def rowdict(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def attach_ro(con: sqlite3.Connection, alias: str, path: Path) -> None:
    uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
    con.execute(f"ATTACH DATABASE ? AS {q(alias)}", (uri,))


def insert_ignore(con: sqlite3.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    cols = ",".join(q(c) for c in columns)
    sql = f"INSERT OR IGNORE INTO {q(table)} ({cols}) VALUES ({','.join('?' for _ in columns)})"
    buf: list[Sequence[Any]] = []
    before = con.total_changes
    for row in rows:
        buf.append(row)
        if len(buf) >= 5000:
            con.executemany(sql, buf); buf.clear()
    if buf: con.executemany(sql, buf)
    return con.total_changes - before


def ensure_existing_hash(con: sqlite3.Connection, table: str, id_col: str, id_value: str, hash_col: str, expected_hash: str) -> None:
    row = con.execute(f"SELECT {q(hash_col)} FROM {q(table)} WHERE {q(id_col)}=?", (id_value,)).fetchone()
    if row is not None and row[0] != expected_hash:
        raise RuntimeError(f"conflicting duplicate {table}.{id_col}={id_value}: {row[0]} != {expected_hash}")


def pattern_candidate_row(
    definition_id: str,
    symbol: str,
    timeframe: str,
    direction: str,
    source_bar_id: int | None,
    related_source_bar_id: int | None,
    event_time: int,
    confirmation_time: int,
    availability_time: int,
    lower: float | None,
    upper: float | None,
    intrinsic_pass: bool,
    ambiguous: bool,
    reasons: Mapping[str, Any],
    features: Mapping[str, Any],
    upstream_refs: Mapping[str, Any],
) -> tuple[Any, ...]:
    feature_json = canonical_json(features)
    feature_hash = hashlib.sha256(feature_json.encode()).hexdigest()
    creation = {
        "definition_id": definition_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": direction,
        "source_bar_id": source_bar_id,
        "related_source_bar_id": related_source_bar_id,
        "event_time": event_time,
        "confirmation_time": confirmation_time,
        "availability_time": availability_time,
        "lower": lower,
        "upper": upper,
        "intrinsic_pass": int(bool(intrinsic_pass)),
        "ambiguous": int(bool(ambiguous)),
        "features": features,
        "upstream_refs": upstream_refs,
    }
    candidate_id = deterministic_id("g8pc", creation)
    candidate_hash = canonical_hash({**creation, "reasons": reasons, "feature_hash": feature_hash})
    return (
        candidate_id, definition_id, symbol, timeframe, direction,
        source_bar_id, related_source_bar_id, event_time, confirmation_time, availability_time,
        lower, upper, int(bool(intrinsic_pass)), int(bool(ambiguous)), canonical_json(reasons), feature_json,
        canonical_json(upstream_refs), feature_hash, candidate_hash,
    )

def school_interpretation_row(
    definition_id: str,
    school_id: str,
    symbol: str,
    timeframe: str,
    direction: str,
    event_time: int,
    confirmation_time: int,
    availability_time: int,
    lifecycle_state: str,
    mandatory_complete: bool,
    ambiguous: bool,
    supporting_count: int,
    conflicting_count: int,
    evidence_strength: Mapping[str, Any],
    upstream_refs: Mapping[str, Any],
    reasons: Mapping[str, Any],
) -> tuple[Any, ...]:
    creation = {
        "definition_id": definition_id, "school_id": school_id, "symbol": symbol, "timeframe": timeframe,
        "direction": direction, "event_time": event_time, "confirmation_time": confirmation_time,
        "availability_time": availability_time, "upstream_refs": upstream_refs,
    }
    iid = deterministic_id("g8si", creation)
    ihash = canonical_hash({**creation, "lifecycle_state": lifecycle_state, "mandatory_complete": int(mandatory_complete),
                            "ambiguous": int(ambiguous), "supporting_count": supporting_count,
                            "conflicting_count": conflicting_count, "evidence_strength": evidence_strength, "reasons": reasons})
    return (iid, definition_id, school_id, symbol, timeframe, direction, event_time, confirmation_time, availability_time,
            lifecycle_state, int(mandatory_complete), int(ambiguous), supporting_count, conflicting_count,
            canonical_json(evidence_strength), canonical_json(upstream_refs), canonical_json(reasons), ihash)

def hypothesis_row(
    definition_id: str,
    school_id: str,
    symbol: str,
    timeframe: str,
    direction: str,
    event_time: int,
    confirmation_time: int,
    availability_time: int,
    initial_state: str,
    mandatory_complete: bool,
    ambiguous: bool,
    supporting_count: int,
    conflicting_count: int,
    evidence_strength: Mapping[str, Any],
    upstream_refs: Mapping[str, Any],
    reasons: Mapping[str, Any],
) -> tuple[Any, ...]:
    creation = {
        "definition_id": definition_id, "school_id": school_id, "symbol": symbol, "timeframe": timeframe,
        "direction": direction, "event_time": event_time, "confirmation_time": confirmation_time,
        "availability_time": availability_time, "upstream_refs": upstream_refs,
    }
    hid = deterministic_id("g8nh", creation)
    hhash = canonical_hash({**creation, "initial_state": initial_state, "mandatory_complete": int(mandatory_complete),
                            "ambiguous": int(ambiguous), "supporting_count": supporting_count,
                            "conflicting_count": conflicting_count, "evidence_strength": evidence_strength, "reasons": reasons})
    return (hid, definition_id, school_id, symbol, timeframe, direction, event_time, confirmation_time, availability_time,
            initial_state, int(mandatory_complete), int(ambiguous), supporting_count, conflicting_count,
            canonical_json(evidence_strength), canonical_json(upstream_refs), canonical_json(reasons), hhash)

@dataclass
class Boundary:
    boundary_id: str
    source_group: str
    source_type: str
    source_id: str
    timeframe: str
    side: str
    price: float
    lower: float
    upper: float
    availability_time: int
    end_time: int | None
    source_hash: str
    layer: str | None = None
