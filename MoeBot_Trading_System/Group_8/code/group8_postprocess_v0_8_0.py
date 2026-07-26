#!/usr/bin/env python3
"""Frozen lifecycle, invalidation, checkpoint, and audit persistence for Group 8 v0.8.0.

The helpers in this module are deliberately post-processing only. They do not
change frozen definitions, thresholds, upstream objects, or creation rows.
They append causal state/invalidation evidence and deterministic checkpoints
required by the frozen Group 8 design contract.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

TERMINAL_HYPOTHESIS_STATES = {"invalidated", "completed_descriptive", "right_censored"}
ACTIVE_HYPOTHESIS_STATES = {"candidate", "active_supported", "active_ambiguous", "contradicted"}
WYCKOFF_COMPLETED_HYPOTHESES = {
    "wyckoff_accumulation_hypothesis",
    "wyckoff_distribution_hypothesis",
    "wyckoff_reaccumulation_hypothesis",
    "wyckoff_redistribution_hypothesis",
}
DOW_INVALIDATABLE = {"dow_bullish_transition", "dow_bearish_transition", "dow_protected_pullback"}
WYCKOFF_INVALIDATABLE = {
    "wyckoff_spring_candidate",
    "wyckoff_upthrust_candidate",
    "wyckoff_sign_of_strength",
    "wyckoff_sign_of_weakness",
    "wyckoff_last_point_of_support",
    "wyckoff_last_point_of_supply",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{stable_hash(value)}"


def normalize_direction(value: Any) -> str:
    if value is None:
        return "neutral"
    text = str(value).lower()
    if text in {"bullish", "up", "positive"}:
        return "bullish"
    if text in {"bearish", "down", "negative"}:
        return "bearish"
    return "neutral"


def opposite_direction(direction: str) -> str | None:
    d = normalize_direction(direction)
    if d == "bullish":
        return "bearish"
    if d == "bearish":
        return "bullish"
    return None


def _ensure_pattern_state(
    engine: Any,
    candidate_id: str,
    ordinal: int,
    state: str,
    *,
    source_bar_id: int | None,
    event_time: int,
    availability_time: int,
    ambiguous: bool,
    details: Mapping[str, Any],
) -> str:
    payload = {
        "candidate_id": candidate_id,
        "state_ordinal": int(ordinal),
        "source_bar_id": source_bar_id,
        "event_time": int(event_time),
        "availability_time": int(availability_time),
        "state": state,
        "ambiguous": bool(ambiguous),
        "details": dict(details),
    }
    state_id = deterministic_id("g8pstate", payload)
    state_hash = stable_hash(payload)
    row = {
        "state_event_id": state_id,
        "candidate_id": candidate_id,
        "state_ordinal": int(ordinal),
        "source_bar_id": source_bar_id,
        "event_time": int(event_time),
        "availability_time": int(availability_time),
        "state": state,
        "ambiguous": 1 if ambiguous else 0,
        "details_json": canonical_json(dict(details)),
        "state_hash": state_hash,
    }
    existing = engine.out.execute(
        "SELECT state_event_id,state_hash FROM price_action_pattern_state WHERE candidate_id=? AND state_ordinal=?",
        (candidate_id, int(ordinal)),
    ).fetchone()
    if existing is not None:
        if existing["state_hash"] != state_hash:
            raise engine.__class__.__mro__[0].__module__ and RuntimeError(
                f"conflicting deterministic pattern state: {candidate_id}:{ordinal}"
            )
        return str(existing["state_event_id"])
    engine._insert_immutable(
        "price_action_pattern_state",
        "state_event_id",
        state_id,
        row,
        hash_column="state_hash",
        expected_hash=state_hash,
    )
    return state_id


def ensure_pattern_creation_state(engine: Any, candidate_id: str) -> str:
    candidate = engine.out.execute(
        "SELECT candidate_id,source_bar_id,event_time,availability_time,ambiguous,definition_id FROM price_action_pattern_candidate WHERE candidate_id=?",
        (candidate_id,),
    ).fetchone()
    if candidate is None:
        raise RuntimeError(f"pattern candidate missing for creation state: {candidate_id}")
    return _ensure_pattern_state(
        engine,
        candidate_id,
        0,
        "created",
        source_bar_id=candidate["source_bar_id"],
        event_time=int(candidate["event_time"]),
        availability_time=int(candidate["availability_time"]),
        ambiguous=bool(candidate["ambiguous"]),
        details={"definition_id": candidate["definition_id"], "creation": True},
    )


def _ensure_hypothesis_lifecycle(
    engine: Any,
    hypothesis_id: str,
    ordinal: int,
    state: str,
    *,
    source_type: str | None,
    source_id: str | None,
    event_time: int,
    availability_time: int,
    details: Mapping[str, Any],
) -> str:
    base = engine.out.execute(
        "SELECT availability_time FROM narrative_hypothesis WHERE hypothesis_id=?",
        (hypothesis_id,),
    ).fetchone()
    if base is None:
        raise RuntimeError(f"hypothesis missing for lifecycle: {hypothesis_id}")
    if int(availability_time) < int(base["availability_time"]):
        raise RuntimeError(f"lifecycle before hypothesis availability: {hypothesis_id}")
    payload = {
        "hypothesis_id": hypothesis_id,
        "lifecycle_ordinal": int(ordinal),
        "source_type": source_type,
        "source_id": source_id,
        "event_time": int(event_time),
        "availability_time": int(availability_time),
        "lifecycle_state": state,
        "details": dict(details),
    }
    lifecycle_id = deterministic_id("g8life", payload)
    lifecycle_hash = stable_hash(payload)
    row = {
        "lifecycle_event_id": lifecycle_id,
        "hypothesis_id": hypothesis_id,
        "lifecycle_ordinal": int(ordinal),
        "source_type": source_type,
        "source_id": source_id,
        "event_time": int(event_time),
        "availability_time": int(availability_time),
        "lifecycle_state": state,
        "details_json": canonical_json(dict(details)),
        "lifecycle_hash": lifecycle_hash,
    }
    existing = engine.out.execute(
        "SELECT lifecycle_event_id,lifecycle_hash FROM hypothesis_lifecycle_event WHERE hypothesis_id=? AND lifecycle_ordinal=?",
        (hypothesis_id, int(ordinal)),
    ).fetchone()
    if existing is not None:
        if existing["lifecycle_hash"] != lifecycle_hash:
            raise RuntimeError(f"conflicting deterministic lifecycle ordinal: {hypothesis_id}:{ordinal}")
        return str(existing["lifecycle_event_id"])
    engine._insert_immutable(
        "hypothesis_lifecycle_event",
        "lifecycle_event_id",
        lifecycle_id,
        row,
        hash_column="lifecycle_hash",
        expected_hash=lifecycle_hash,
    )
    return lifecycle_id


def ensure_initial_hypothesis_lifecycle(
    engine: Any,
    hypothesis_id: str,
    state: str,
    *,
    event_time: int,
    availability_time: int,
) -> str:
    return _ensure_hypothesis_lifecycle(
        engine,
        hypothesis_id,
        0,
        state,
        source_type=None,
        source_id=None,
        event_time=int(event_time),
        availability_time=int(availability_time),
        details={"creation": True},
    )


def ensure_contradicted(
    engine: Any,
    hypothesis_id: str,
    *,
    source_type: str,
    source_id: str,
    event_time: int,
    availability_time: int,
    details: Mapping[str, Any],
) -> str:
    return _ensure_hypothesis_lifecycle(
        engine,
        hypothesis_id,
        1,
        "contradicted",
        source_type=source_type,
        source_id=source_id,
        event_time=event_time,
        availability_time=availability_time,
        details=details,
    )


def ensure_terminal_hypothesis_state(
    engine: Any,
    hypothesis_id: str,
    state: str,
    *,
    source_type: str | None,
    source_id: str | None,
    event_time: int,
    availability_time: int,
    details: Mapping[str, Any],
) -> str:
    if state not in TERMINAL_HYPOTHESIS_STATES:
        raise RuntimeError(f"invalid terminal hypothesis state: {state}")
    ordinal = 3 if state == "right_censored" else 2
    return _ensure_hypothesis_lifecycle(
        engine,
        hypothesis_id,
        ordinal,
        state,
        source_type=source_type,
        source_id=source_id,
        event_time=event_time,
        availability_time=availability_time,
        details=details,
    )


def write_invalidation(
    engine: Any,
    *,
    subject_type: str,
    subject_id: str,
    rule_id: str,
    source_type: str,
    source_id: str,
    event_time: int,
    confirmation_time: int,
    availability_time: int,
    reasons: Sequence[str],
    details: Mapping[str, Any],
) -> str:
    if int(availability_time) < int(confirmation_time) or int(confirmation_time) < int(event_time):
        raise RuntimeError(f"invalidation causal ordering violation: {subject_type}:{subject_id}")
    payload = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "rule_id": rule_id,
        "source_type": source_type,
        "source_id": str(source_id),
        "event_time": int(event_time),
        "confirmation_time": int(confirmation_time),
        "availability_time": int(availability_time),
        "reasons": list(reasons),
        "details": dict(details),
    }
    invalidation_id = deterministic_id("g8inv", payload)
    invalidation_hash = stable_hash(payload)
    row = {
        "invalidation_id": invalidation_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "rule_id": rule_id,
        "source_type": source_type,
        "source_id": str(source_id),
        "event_time": int(event_time),
        "confirmation_time": int(confirmation_time),
        "availability_time": int(availability_time),
        "reasons_json": canonical_json(list(reasons)),
        "details_json": canonical_json(dict(details)),
        "invalidation_hash": invalidation_hash,
    }
    engine._insert_immutable(
        "invalidation_record",
        "invalidation_id",
        invalidation_id,
        row,
        hash_column="invalidation_hash",
        expected_hash=invalidation_hash,
    )
    return invalidation_id


def checkpoint(engine: Any, stage: str, status: str = "PASS") -> None:
    count_tables = [
        "price_action_pattern_candidate",
        "price_action_pattern_state",
        "school_interpretation",
        "narrative_hypothesis",
        "hypothesis_lifecycle_event",
        "invalidation_record",
        "shared_evidence",
        "conflicting_evidence",
        "multi_timeframe_context_relation",
        "evidence_chain",
    ]
    counts = {table: int(engine.out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in count_tables}
    for (symbol, timeframe), bars in sorted(engine.bars_by_tf.items()):
        last = bars[-1] if bars else None
        last_bar_id = int(last.id) if last is not None else None
        last_time = int(last.available_at) if last is not None else int(engine.annual_end_time or 0)
        snapshot = {
            "stage": stage,
            "symbol": symbol,
            "timeframe": timeframe,
            "last_bar_id": last_bar_id,
            "last_time": last_time,
            "counts": counts,
            "engine_version": engine.config["engine_version"],
            "schema_version": engine.config["schema_version"],
            "config_id": engine.config["config_id"],
        }
        snapshot_hash = stable_hash(snapshot)
        engine.out.execute(
            """INSERT INTO processing_checkpoint(symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol,timeframe,stage) DO UPDATE SET
                   status=excluded.status,last_bar_id=excluded.last_bar_id,last_time=excluded.last_time,
                   snapshot_hash=excluded.snapshot_hash,updated_at=excluded.updated_at""",
            (symbol, timeframe, stage, status, last_bar_id, last_time, snapshot_hash, last_time),
        )
    engine.out.commit()


def _first_opposite_group3_event(engine: Any, *, symbol: str, timeframe: str, layer: str | None,
                                 direction: str, after_time: int, through_time: int | None = None) -> dict[str, Any] | None:
    opposite = opposite_direction(direction)
    if opposite is None:
        return None
    candidates: list[dict[str, Any]] = []
    state_sql = "SELECT * FROM group3__structure_states WHERE timeframe=? AND close_time>?"
    state_args: list[Any] = [timeframe, int(after_time)]
    if symbol and symbol != "UNKNOWN":
        state_sql += " AND symbol=?"
        state_args.append(symbol)
    if layer is not None:
        state_sql += " AND layer=?"
        state_args.append(layer)
    if through_time is not None:
        state_sql += " AND close_time<=?"
        state_args.append(int(through_time))
    state_sql += " ORDER BY close_time,state_id"
    for row in engine.input.execute(state_sql, state_args):
        raw = row["active_bias"] if row["active_bias"] not in (None, "unknown", "transition") else row["sequence_bias"]
        if normalize_direction(raw) == opposite:
            candidates.append({
                "source_type": "group3_structure_states",
                "source_id": row["state_id"],
                "event_time": int(row["close_time"]),
                "confirmation_time": int(row["close_time"]),
                "availability_time": int(row["close_time"]),
                "details": {"layer": row["layer"], "active_bias": row["active_bias"], "sequence_bias": row["sequence_bias"]},
            })
    break_sql = "SELECT * FROM group3__break_events WHERE timeframe=? AND resolved_time IS NOT NULL AND resolved_time>?"
    break_args: list[Any] = [timeframe, int(after_time)]
    if symbol and symbol != "UNKNOWN":
        break_sql += " AND symbol=?"
        break_args.append(symbol)
    if layer is not None:
        break_sql += " AND layer=?"
        break_args.append(layer)
    if through_time is not None:
        break_sql += " AND resolved_time<=?"
        break_args.append(int(through_time))
    break_sql += " ORDER BY resolved_time,event_id"
    for row in engine.input.execute(break_sql, break_args):
        if normalize_direction(row["direction"]) == opposite:
            candidates.append({
                "source_type": "group3_break_events",
                "source_id": row["event_id"],
                "event_time": int(row["candidate_time"]),
                "confirmation_time": int(row["resolved_time"]),
                "availability_time": int(row["resolved_time"]),
                "details": {"layer": row["layer"], "event_type": row["event_type"], "direction": row["direction"], "outcome": row["outcome"]},
            })
    if not candidates:
        return None
    return min(candidates, key=lambda x: (x["availability_time"], x["source_type"], str(x["source_id"])))


def continuation_structure_valid(engine: Any, structure_state: Mapping[str, Any], counter_leg: Mapping[str, Any],
                                 later_leg: Mapping[str, Any], direction: str) -> bool:
    event = _first_opposite_group3_event(
        engine,
        symbol=str(structure_state.get("symbol") or "UNKNOWN"),
        timeframe=str(structure_state["timeframe"]),
        layer=str(structure_state.get("layer")) if structure_state.get("layer") is not None else None,
        direction=direction,
        after_time=int(counter_leg["validation_availability"]),
        through_time=int(later_leg["validation_availability"]),
    )
    return event is None


def _candidate_from_ref(engine: Any, refs: Sequence[Mapping[str, Any]], source_type: str) -> Any | None:
    ref = next((r for r in refs if r.get("source_group") == "group8" and r.get("source_type") == source_type), None)
    if ref is None:
        return None
    return engine.out.execute("SELECT * FROM price_action_pattern_candidate WHERE candidate_id=?", (str(ref["source_id"]),)).fetchone()


def _interpretation_from_ref(engine: Any, refs: Sequence[Mapping[str, Any]], definition_id: str | None = None) -> Any | None:
    for ref in refs:
        if ref.get("source_group") != "group8" or ref.get("source_type") != "school_interpretation":
            continue
        row = engine.out.execute("SELECT * FROM school_interpretation WHERE interpretation_id=?", (str(ref["source_id"]),)).fetchone()
        if row is not None and (definition_id is None or row["definition_id"] == definition_id):
            return row
    return None


def _range_candidate_for_interpretation(engine: Any, interpretation: Any) -> Any | None:
    refs = json.loads(interpretation["upstream_refs_json"])
    direct = _candidate_from_ref(engine, refs, "price_action_pattern_candidate")
    if direct is not None and direct["definition_id"] == "pa_bounded_range_context":
        return direct
    nested = _interpretation_from_ref(engine, refs, "wyckoff_range_context")
    if nested is not None:
        return _range_candidate_for_interpretation(engine, nested)
    return None


def _first_breakout_at_level(engine: Any, *, symbol: str, timeframe: str, level: float, direction: str,
                             after_time: int, failed_only: bool = False) -> Any | None:
    definition = "pa_failed_breakout" if failed_only else "pa_breakout_exact"
    rows = engine.out.execute(
        "SELECT * FROM price_action_pattern_candidate WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time>? ORDER BY availability_time,candidate_id",
        (definition, symbol, timeframe, int(after_time)),
    ).fetchall()
    for row in rows:
        if normalize_direction(row["direction"]) != normalize_direction(direction):
            continue
        features = json.loads(row["features_json"])
        locked = features.get("locked_level")
        if locked is None:
            locked = row["lower"]
        if locked is not None and abs(float(locked) - float(level)) <= 1e-12:
            return row
    return None


def _write_pattern_terminal_state(engine: Any, candidate: Any, *, state: str, source_bar_id: int | None,
                                  event_time: int, availability_time: int, details: Mapping[str, Any]) -> str:
    return _ensure_pattern_state(
        engine,
        str(candidate["candidate_id"]),
        1,
        state,
        source_bar_id=source_bar_id,
        event_time=int(event_time),
        availability_time=int(availability_time),
        ambiguous=bool(candidate["ambiguous"]),
        details=details,
    )


def _finalize_bounded_ranges(engine: Any) -> None:
    candidates = engine.out.execute(
        "SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' ORDER BY availability_time,candidate_id"
    ).fetchall()
    for candidate in candidates:
        features = json.loads(candidate["features_json"])
        zone_ids = [features.get("lower_zone_id"), features.get("upper_zone_id")]
        invalidators: list[dict[str, Any]] = []
        for zone_id in [z for z in zone_ids if z]:
            for tr in engine.input.execute(
                "SELECT * FROM group4__zone_transitions WHERE zone_id=? AND transition_time>? ORDER BY transition_time,transition_id",
                (zone_id, int(candidate["availability_time"])),
            ):
                if not engine._status_active(str(tr["to_status"])):
                    invalidators.append({
                        "source_type": "group4_zone_transitions",
                        "source_id": tr["transition_id"],
                        "event_time": int(tr["transition_time"]),
                        "confirmation_time": int(tr["transition_time"]),
                        "availability_time": int(tr["transition_time"]),
                        "source_bar_id": tr["bar_id"],
                        "details": {"zone_id": zone_id, "from_status": tr["from_status"], "to_status": tr["to_status"], "reason": tr["reason"]},
                    })
                    break
            for ev in engine.input.execute(
                "SELECT * FROM group4__zone_interactions WHERE zone_id=? AND interaction_time>? ORDER BY interaction_time,interaction_id",
                (zone_id, int(candidate["availability_time"])),
            ):
                if not engine._status_active(str(ev["status_after"])):
                    invalidators.append({
                        "source_type": "group4_zone_interactions",
                        "source_id": ev["interaction_id"],
                        "event_time": int(ev["interaction_time"]),
                        "confirmation_time": int(ev["interaction_time"]),
                        "availability_time": int(ev["interaction_time"]),
                        "source_bar_id": ev["bar_id"],
                        "details": {"zone_id": zone_id, "event_type": ev["event_type"], "status_after": ev["status_after"]},
                    })
                    break
        if invalidators:
            inv = min(invalidators, key=lambda x: (x["availability_time"], x["source_type"], str(x["source_id"])))
            _write_pattern_terminal_state(
                engine, candidate, state="invalidated", source_bar_id=inv["source_bar_id"],
                event_time=inv["event_time"], availability_time=inv["availability_time"], details=inv["details"],
            )
            write_invalidation(
                engine,
                subject_type="price_action_pattern_candidate",
                subject_id=candidate["candidate_id"],
                rule_id="pa_bounded_range_context.invalidation_rule",
                source_type=inv["source_type"], source_id=inv["source_id"],
                event_time=inv["event_time"], confirmation_time=inv["confirmation_time"], availability_time=inv["availability_time"],
                reasons=["locked_group4_boundary_invalidated"], details=inv["details"],
            )
        else:
            annual_end = int(engine.annual_end_time or candidate["availability_time"])
            _write_pattern_terminal_state(
                engine, candidate, state="right_censored", source_bar_id=None,
                event_time=annual_end, availability_time=annual_end,
                details={"rule": "annual_end_no_locked_boundary_invalidation"},
            )


def _finalize_breakout_followups(engine: Any) -> None:
    for breakout in engine.out.execute(
        "SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer') ORDER BY availability_time,candidate_id"
    ).fetchall():
        features = json.loads(breakout["features_json"])
        linked_failed = engine.out.execute(
            "SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id='pa_failed_breakout' AND json_extract(features_json,'$.breakout_candidate_id')=? LIMIT 1",
            (breakout["candidate_id"],),
        ).fetchone()
        linked_retest = engine.out.execute(
            "SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id='pa_retest' AND json_extract(features_json,'$.breakout_candidate_id')=? LIMIT 1",
            (breakout["candidate_id"],),
        ).fetchone()
        annual_end = int(engine.annual_end_time or breakout["availability_time"])
        details = {
            "failed_breakout_resolution": "resolved" if linked_failed else "right_censored",
            "retest_resolution": "resolved" if linked_retest else "right_censored",
            "locked_level": features.get("locked_level"),
            "boundary_identity": features.get("boundary_identity"),
        }
        _write_pattern_terminal_state(
            engine, breakout, state="followup_resolution", source_bar_id=None,
            event_time=annual_end, availability_time=annual_end, details=details,
        )


def _terminal_event_for_hypothesis(engine: Any, hypothesis: Any) -> dict[str, Any] | None:
    definition = str(hypothesis["definition_id"])
    if definition == "pa_continuation_after_pullback" or definition in WYCKOFF_COMPLETED_HYPOTHESES:
        return {
            "state": "completed_descriptive",
            "source_type": "group8_creation_evidence",
            "source_id": hypothesis["hypothesis_id"],
            "event_time": int(hypothesis["confirmation_time"]),
            "confirmation_time": int(hypothesis["confirmation_time"]),
            "availability_time": int(hypothesis["availability_time"]),
            "details": {"rule": "mandatory_descriptive_sequence_complete_at_creation"},
        }
    if definition == "pa_structural_pullback":
        refs = json.loads(hypothesis["upstream_refs_json"])
        g3 = next((r for r in refs if r.get("source_group") == "group3" and r.get("source_type") == "structure_states"), None)
        layer = ((g3 or {}).get("details") or {}).get("layer")
        invalidator = _first_opposite_group3_event(
            engine,
            symbol=hypothesis["symbol"], timeframe=hypothesis["timeframe"], layer=layer,
            direction=hypothesis["direction"], after_time=int(hypothesis["availability_time"]), through_time=None,
        )
        continuation = None
        for row in engine.out.execute(
            "SELECT * FROM narrative_hypothesis WHERE definition_id='pa_continuation_after_pullback' AND symbol=? AND timeframe=? AND availability_time>=? ORDER BY availability_time,hypothesis_id",
            (hypothesis["symbol"], hypothesis["timeframe"], hypothesis["availability_time"]),
        ):
            child_refs = json.loads(row["upstream_refs_json"])
            if any(r.get("source_group") == "group8" and r.get("source_type") == "narrative_hypothesis" and r.get("source_id") == hypothesis["hypothesis_id"] for r in child_refs):
                continuation = row
                break
        if continuation is not None and (invalidator is None or int(continuation["availability_time"]) < invalidator["availability_time"]):
            return {
                "state": "completed_descriptive", "source_type": "narrative_hypothesis", "source_id": continuation["hypothesis_id"],
                "event_time": int(continuation["confirmation_time"]), "confirmation_time": int(continuation["confirmation_time"]),
                "availability_time": int(continuation["availability_time"]), "details": {"rule": "first_qualifying_continuation_completed_pullback"},
            }
        if invalidator is not None:
            return {"state": "invalidated", **invalidator, "details": {**invalidator["details"], "rule": "pa_structural_pullback.invalidation_rule"}}
    if definition == "pa_exhaustion_failed_breakout":
        refs = json.loads(hypothesis["upstream_refs_json"])
        failed = _candidate_from_ref(engine, refs, "price_action_pattern_candidate")
        if failed is not None:
            features = json.loads(failed["features_json"])
            level = features.get("locked_level")
            if level is not None:
                later = _first_breakout_at_level(
                    engine,
                    symbol=hypothesis["symbol"], timeframe=hypothesis["timeframe"], level=float(level),
                    direction=opposite_direction(hypothesis["direction"]) or "neutral",
                    after_time=int(hypothesis["availability_time"]), failed_only=False,
                )
                if later is not None:
                    return {
                        "state": "invalidated", "source_type": "price_action_pattern_candidate", "source_id": later["candidate_id"],
                        "event_time": int(later["event_time"]), "confirmation_time": int(later["confirmation_time"]),
                        "availability_time": int(later["availability_time"]),
                        "details": {"rule": "pa_exhaustion_failed_breakout.invalidation_rule", "locked_level": float(level)},
                    }
    return None


def _persist_hypothesis_lifecycle(engine: Any) -> None:
    hypotheses = engine.out.execute("SELECT * FROM narrative_hypothesis ORDER BY availability_time,hypothesis_id").fetchall()
    for hypothesis in hypotheses:
        ensure_initial_hypothesis_lifecycle(
            engine, hypothesis["hypothesis_id"], hypothesis["initial_state"],
            event_time=int(hypothesis["event_time"]), availability_time=int(hypothesis["availability_time"]),
        )
        terminal = _terminal_event_for_hypothesis(engine, hypothesis)
        conflicts = []
        for conflict in engine.out.execute(
            "SELECT * FROM conflicting_evidence WHERE (left_subject_type='narrative_hypothesis' AND left_subject_id=?) OR (right_subject_type='narrative_hypothesis' AND right_subject_id=?) ORDER BY availability_time,conflict_id",
            (hypothesis["hypothesis_id"], hypothesis["hypothesis_id"]),
        ):
            if int(conflict["availability_time"]) >= int(hypothesis["availability_time"]):
                conflicts.append(conflict)
        if conflicts:
            first = conflicts[0]
            terminal_time = terminal["availability_time"] if terminal is not None else None
            if terminal_time is None or int(first["availability_time"]) <= int(terminal_time):
                ensure_contradicted(
                    engine, hypothesis["hypothesis_id"], source_type="conflicting_evidence", source_id=first["conflict_id"],
                    event_time=int(first["event_time"]), availability_time=int(first["availability_time"]),
                    details={"conflict_type": first["conflict_type"]},
                )
        if terminal is not None:
            ensure_terminal_hypothesis_state(
                engine, hypothesis["hypothesis_id"], terminal["state"], source_type=terminal["source_type"],
                source_id=str(terminal["source_id"]), event_time=int(terminal["event_time"]),
                availability_time=int(terminal["availability_time"]), details=terminal["details"],
            )
            if terminal["state"] == "invalidated":
                write_invalidation(
                    engine, subject_type="narrative_hypothesis", subject_id=hypothesis["hypothesis_id"],
                    rule_id=f"{hypothesis['definition_id']}.invalidation_rule", source_type=terminal["source_type"],
                    source_id=str(terminal["source_id"]), event_time=int(terminal["event_time"]),
                    confirmation_time=int(terminal["confirmation_time"]), availability_time=int(terminal["availability_time"]),
                    reasons=["frozen_invalidation_rule_satisfied"], details=terminal["details"],
                )
        else:
            annual_end = int(engine.annual_end_time or hypothesis["availability_time"])
            ensure_terminal_hypothesis_state(
                engine, hypothesis["hypothesis_id"], "right_censored", source_type="annual_end", source_id=str(engine.year),
                event_time=annual_end, availability_time=annual_end,
                details={"rule": "no_terminal_frozen_event_available_before_annual_end"},
            )


def _interpretation_level_context(engine: Any, interpretation: Any) -> tuple[float | None, str | None]:
    definition = interpretation["definition_id"]
    refs = json.loads(interpretation["upstream_refs_json"])
    if definition in {"wyckoff_spring_candidate", "wyckoff_upthrust_candidate"}:
        range_candidate = _range_candidate_for_interpretation(engine, interpretation)
        if range_candidate is None:
            return None, None
        return (
            float(range_candidate["lower"] if definition == "wyckoff_spring_candidate" else range_candidate["upper"]),
            "bearish" if definition == "wyckoff_spring_candidate" else "bullish",
        )
    if definition in {"wyckoff_sign_of_strength", "wyckoff_sign_of_weakness"}:
        breakout = _candidate_from_ref(engine, refs, "price_action_pattern_candidate")
        if breakout is None:
            return None, None
        features = json.loads(breakout["features_json"])
        level = features.get("locked_level", breakout["lower"])
        return float(level), "bearish" if definition == "wyckoff_sign_of_strength" else "bullish"
    if definition in {"wyckoff_last_point_of_support", "wyckoff_last_point_of_supply"}:
        sign = _interpretation_from_ref(engine, refs)
        if sign is None:
            return None, None
        return _interpretation_level_context(engine, sign)
    return None, None


def _persist_interpretation_invalidations(engine: Any) -> None:
    rows = engine.out.execute("SELECT * FROM school_interpretation ORDER BY availability_time,interpretation_id").fetchall()
    for interpretation in rows:
        definition = str(interpretation["definition_id"])
        invalidator: dict[str, Any] | None = None
        if definition in DOW_INVALIDATABLE:
            layer = None
            refs = json.loads(interpretation["upstream_refs_json"])
            for ref in refs:
                details = ref.get("details") or {}
                if details.get("layer") is not None:
                    layer = str(details["layer"])
                    break
            invalidator = _first_opposite_group3_event(
                engine, symbol=interpretation["symbol"], timeframe=interpretation["timeframe"], layer=layer,
                direction=interpretation["direction"], after_time=int(interpretation["availability_time"]), through_time=None,
            )
        elif definition in WYCKOFF_INVALIDATABLE:
            level, invalidating_direction = _interpretation_level_context(engine, interpretation)
            if level is not None and invalidating_direction is not None:
                failed_only = definition in {
                    "wyckoff_sign_of_strength", "wyckoff_sign_of_weakness",
                    "wyckoff_last_point_of_support", "wyckoff_last_point_of_supply",
                }
                later = _first_breakout_at_level(
                    engine, symbol=interpretation["symbol"], timeframe=interpretation["timeframe"], level=level,
                    direction=invalidating_direction, after_time=int(interpretation["availability_time"]), failed_only=failed_only,
                )
                if later is not None:
                    invalidator = {
                        "source_type": "price_action_pattern_candidate",
                        "source_id": later["candidate_id"],
                        "event_time": int(later["event_time"]),
                        "confirmation_time": int(later["confirmation_time"]),
                        "availability_time": int(later["availability_time"]),
                        "details": {"locked_level": level, "invalidating_definition": later["definition_id"]},
                    }
        if invalidator is not None:
            write_invalidation(
                engine, subject_type="school_interpretation", subject_id=interpretation["interpretation_id"],
                rule_id=f"{definition}.invalidation_rule", source_type=invalidator["source_type"],
                source_id=str(invalidator["source_id"]), event_time=int(invalidator["event_time"]),
                confirmation_time=int(invalidator["confirmation_time"]), availability_time=int(invalidator["availability_time"]),
                reasons=["frozen_invalidation_rule_satisfied"], details=invalidator["details"],
            )


def _validate_persistence(engine: Any) -> dict[str, Any]:
    failures: list[str] = []
    pattern_count = int(engine.out.execute("SELECT COUNT(*) FROM price_action_pattern_candidate").fetchone()[0])
    creation_states = int(engine.out.execute("SELECT COUNT(*) FROM price_action_pattern_state WHERE state_ordinal=0").fetchone()[0])
    if creation_states != pattern_count:
        failures.append(f"pattern_creation_state_count:{creation_states}!={pattern_count}")
    hypothesis_count = int(engine.out.execute("SELECT COUNT(*) FROM narrative_hypothesis").fetchone()[0])
    initial_count = int(engine.out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event WHERE lifecycle_ordinal=0").fetchone()[0])
    if initial_count != hypothesis_count:
        failures.append(f"hypothesis_initial_lifecycle_count:{initial_count}!={hypothesis_count}")
    terminal_count = int(engine.out.execute(
        "SELECT COUNT(DISTINCT hypothesis_id) FROM hypothesis_lifecycle_event WHERE lifecycle_state IN ('invalidated','completed_descriptive','right_censored')"
    ).fetchone()[0])
    if terminal_count != hypothesis_count:
        failures.append(f"hypothesis_terminal_count:{terminal_count}!={hypothesis_count}")
    lifecycle_causal = int(engine.out.execute(
        "SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time"
    ).fetchone()[0])
    if lifecycle_causal:
        failures.append(f"lifecycle_before_creation:{lifecycle_causal}")
    invalidation_causal = int(engine.out.execute(
        "SELECT COUNT(*) FROM invalidation_record WHERE availability_time<confirmation_time OR confirmation_time<event_time"
    ).fetchone()[0])
    if invalidation_causal:
        failures.append(f"invalidation_causality:{invalidation_causal}")
    contradiction_order = int(engine.out.execute(
        """SELECT COUNT(*) FROM hypothesis_lifecycle_event c JOIN hypothesis_lifecycle_event t USING(hypothesis_id)
           WHERE c.lifecycle_state='contradicted' AND t.lifecycle_state='invalidated'
             AND (c.availability_time>t.availability_time OR c.lifecycle_ordinal>=t.lifecycle_ordinal)"""
    ).fetchone()[0])
    if contradiction_order:
        failures.append(f"contradiction_after_invalidation:{contradiction_order}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "pattern_count": pattern_count,
        "pattern_creation_states": creation_states,
        "hypothesis_count": hypothesis_count,
        "hypothesis_initial_states": initial_count,
        "hypothesis_terminal_states": terminal_count,
        "failures": failures,
    }


def finalize_postprocessing(engine: Any) -> dict[str, Any]:
    for candidate_id, in engine.out.execute("SELECT candidate_id FROM price_action_pattern_candidate ORDER BY candidate_id"):
        ensure_pattern_creation_state(engine, candidate_id)
    _finalize_bounded_ranges(engine)
    _finalize_breakout_followups(engine)
    _persist_hypothesis_lifecycle(engine)
    _persist_interpretation_invalidations(engine)
    report = _validate_persistence(engine)
    if report["status"] != "PASS":
        raise RuntimeError(f"Group 8 lifecycle persistence validation failed: {report['failures']}")
    engine.out.commit()
    return report


def persist_audit_evidence(engine: Any, engine_audit: Mapping[str, Any], persistence_report: Mapping[str, Any]) -> None:
    checked_at = int(engine.annual_end_time or 0)
    checks = [
        ("engine_core_audit", str(engine_audit.get("status", "UNKNOWN")), dict(engine_audit)),
        ("lifecycle_persistence", str(persistence_report.get("status", "UNKNOWN")), dict(persistence_report)),
        ("checkpoint_persistence", "PASS" if engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0] else "FAIL", {
            "checkpoint_count": int(engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0])
        }),
        ("prohibited_output_audit", "PASS" if not engine_audit.get("failures") else str(engine_audit.get("status", "FAIL")), {
            "engine_audit_hash": engine_audit.get("report_hash"), "failures": engine_audit.get("failures", [])
        }),
    ]
    for check_name, status, details in checks:
        payload = {"check_name": check_name, "status": status, "scope": f"group8-year-{engine.year}", "details": details, "checked_at": checked_at}
        audit_id = deterministic_id("g8audit", payload)
        audit_hash = stable_hash(payload)
        row = {
            "audit_id": audit_id, "check_name": check_name, "status": status, "scope": payload["scope"],
            "details_json": canonical_json(details), "checked_at": checked_at, "audit_hash": audit_hash,
        }
        engine._insert_immutable("group8_audit_evidence", "audit_id", audit_id, row, hash_column="audit_hash", expected_hash=audit_hash)
    engine.out.commit()
