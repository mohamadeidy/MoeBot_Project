#!/usr/bin/env python3
"""MoeBot Group 8 v0.8.0 — Price Action & Trading Schools Intelligence.

This engine is an interpretation/research layer. It never emits trading or PnL
outputs. Upstream Groups 1-7 are consumed read-only through a verified staging
SQLite produced by group8_materialize_inputs.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

ENGINE_VERSION = "0.8.0"
SCHEMA_VERSION = "8.0.0"
CONFIG_ID = "cfg8_0e5a4dc3394efff2d2d54c20b0a93fba66b6ddd3d8e8a28a70292e6bb5755ded"
EXPECTED_DEFINITION_COUNT = 45
EXPECTED_DEFINITION_REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
EXPECTED_SCHEMA_SHA256 = "69382b60266857c0d5aa8662ee6d98d47ae20288bac4d76149aba438eec2d6c1"
EXPECTED_DESIGN_FREEZE_HASH = "42364211a43b26df07dfc1dd6a841930ca985959af61dfeffa1691b65bef42d7"
EXPECTED_LOGICAL_LINEAGE = "moebot-group8-upstream-corrected-v3-g7-v075-v1"

FORBIDDEN_OUTPUT_TOKENS = {
    "buy", "sell", "wait", "exit", "entry", "stop_loss", "take_profit",
    "position_size", "lot_size", "leverage", "pnl", "mfe", "mae",
    "future_return", "profit_factor", "expectancy", "sharpe", "hit_rate",
    "preferred_school", "preferred_setup", "setup_grade", "trade_score",
}

SCHOOL_IDS = {
    "classical_price_action": "school_classical_price_action_v1",
    "dow_theory": "school_dow_theory_v1",
    "wyckoff": "school_wyckoff_v1",
    "ict_smc": "school_ict_smc_v1",
}

PATTERN_KINDS = {
    "base_pattern", "bar_relation", "candle_shape", "context_pattern",
    "derived_context", "boundary_event", "derived_boundary_event", "visit_event",
}

LIFECYCLE_STATES = {
    "candidate", "active_supported", "active_ambiguous", "contradicted",
    "invalidated", "completed_descriptive", "right_censored",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(payload: Any) -> str:
    return sha256_text(canonical_json(payload))


def deterministic_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{stable_hash(payload)}"


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def max_time(*values: Any) -> int:
    clean = [int(v) for v in values if v is not None]
    if not clean:
        raise ValueError("at least one causal time is required")
    return max(clean)


def direction_from_bar(open_: float, close: float) -> str:
    if close > open_:
        return "bullish"
    if close < open_:
        return "bearish"
    return "neutral"


def opposite_direction(direction: str) -> str | None:
    d = str(direction).lower()
    if d in {"bullish", "up", "buy_side", "long"}:
        return "bearish"
    if d in {"bearish", "down", "sell_side", "short"}:
        return "bullish"
    return None


def normalize_direction(value: Any) -> str:
    if value is None:
        return "neutral"
    s = str(value).lower()
    if s in {"bullish", "up", "buy", "buy_side", "positive"}:
        return "bullish"
    if s in {"bearish", "down", "sell", "sell_side", "negative"}:
        return "bearish"
    return "neutral"


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


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
    tick_volume: int | None = None


class Group8InvariantError(RuntimeError):
    pass


class Group8Engine:
    def __init__(self, *, staging_db: Path, output_db: Path, artifacts_root: Path, year: int,
                 symbol: str | None = None, annual_end_time: int | None = None) -> None:
        self.staging_db = staging_db.resolve(); self.output_db = output_db.resolve(); self.root = artifacts_root.resolve()
        self.year = int(year); self.symbol_filter = symbol; self.annual_end_time = annual_end_time
        self.config = json.loads((self.root / "FROZEN_CONFIG.json").read_text())
        self.def_registry = json.loads((self.root / "01_DEFINITION_REGISTRY.json").read_text())
        self.freeze = json.loads((self.root / "DESIGN_FREEZE_MANIFEST.json").read_text())
        self.adapter = json.loads((self.root / "UPSTREAM_ADAPTER_MAP.json").read_text())
        self.bindings = json.loads((self.root / "UPSTREAM_VALUE_BINDINGS.json").read_text())
        self.contract = json.loads((self.root / "contracts/UPSTREAM_INPUT_CONTRACT.json").read_text())
        self.schema_path = self.root / "02_SCHEMA.sql"; self.schema_sql = self.schema_path.read_text()
        self._verify_frozen_design()
        self.input = sqlite3.connect(f"file:{self.staging_db}?mode=ro&immutable=1", uri=True); self.input.row_factory = sqlite3.Row
        self.output_db.parent.mkdir(parents=True, exist_ok=True); self.out = sqlite3.connect(self.output_db); self.out.row_factory = sqlite3.Row
        self.out.execute("PRAGMA foreign_keys=ON"); self.out.executescript(self.schema_sql); self._verify_staging_contract(); self._seed_registries()
        self.bars_by_tf: dict[tuple[str, str], list[Bar]] = {}; self.atr_by_bar: dict[int, float | None] = {}; self.bar_pos: dict[int, tuple[tuple[str, str], int]] = {}; self.point_increment: dict[str, float | None] = {}
        self.definition_coverage: dict[str, int] = {k: 0 for k in self.def_registry["definitions"]}

    def close(self) -> None:
        self.out.commit(); self.out.close(); self.input.close()

    def _verify_frozen_design(self) -> None:
        if self.config.get("config_status") != "FROZEN": raise Group8InvariantError("config is not FROZEN")
        if self.config.get("engine_version") != ENGINE_VERSION or self.config.get("schema_version") != SCHEMA_VERSION: raise Group8InvariantError("engine/schema identity mismatch")
        if self.config.get("config_id") != CONFIG_ID: raise Group8InvariantError("config ID mismatch")
        if self.def_registry.get("status") != "FROZEN" or len(self.def_registry.get("definitions", {})) != EXPECTED_DEFINITION_COUNT: raise Group8InvariantError("definition registry not frozen or definition count drift")
        if self.def_registry.get("registry_hash") != EXPECTED_DEFINITION_REGISTRY_HASH: raise Group8InvariantError("definition registry hash mismatch")
        if self.freeze.get("status") != "FROZEN" or self.freeze.get("design_freeze_hash") != EXPECTED_DESIGN_FREEZE_HASH: raise Group8InvariantError("design freeze identity mismatch")
        if self.freeze.get("logical_dependency_lineage_id") != EXPECTED_LOGICAL_LINEAGE: raise Group8InvariantError("logical dependency lineage mismatch")
        if sha256_file(self.schema_path) != EXPECTED_SCHEMA_SHA256: raise Group8InvariantError("schema SHA-256 mismatch")
        if self.contract.get("status") != "FROZEN" or self.contract.get("read_only") is not True: raise Group8InvariantError("upstream input contract is not frozen read-only")
        for key in ("adapter_map_hash", "value_binding_hash", "source_semantics_evidence_hash"):
            expected = self.freeze.get(key)
            source = {"adapter_map_hash": self.adapter.get("adapter_map_hash"), "value_binding_hash": self.bindings.get("binding_hash"), "source_semantics_evidence_hash": self.config.get("source_semantics_evidence_hash")}[key]
            if expected != source: raise Group8InvariantError(f"frozen {key} mismatch")

    def _tables(self, con: sqlite3.Connection) -> set[str]:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def _verify_staging_contract(self) -> None:
        tables = self._tables(self.input); required = {"stage_manifest"}
        for group, group_adapters in self.adapter["adapters"].items():
            for logical_name in group_adapters: required.add(f"{group}__{logical_name}")
        missing = sorted(required - tables)
        if missing: raise Group8InvariantError(f"staging tables missing: {missing}")
        manifest_rows = {r["key"]: r["value"] for r in self.input.execute("SELECT key,value FROM stage_manifest")}
        checks = {"year": str(self.year), "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_id": CONFIG_ID, "logical_dependency_lineage_id": EXPECTED_LOGICAL_LINEAGE, "adapter_map_hash": self.adapter["adapter_map_hash"]}
        for k, expected in checks.items():
            if manifest_rows.get(k) != expected: raise Group8InvariantError(f"staging manifest {k} mismatch: {manifest_rows.get(k)!r} != {expected!r}")
        if manifest_rows.get("status") != "PASS": raise Group8InvariantError("staging materialization is not PASS")
        for group, group_adapters in self.adapter["adapters"].items():
            for name, rec in group_adapters.items():
                table = f"{group}__{name}"; actual = {r[1] for r in self.input.execute(f"PRAGMA table_info({_quoted(table)})")}; missing_cols = sorted(set(rec["required_columns"]) - actual)
                if missing_cols: raise Group8InvariantError(f"{table} missing columns: {missing_cols}")

    def _seed_registries(self) -> None:
        now = 0; config_json = canonical_json(self.config); config_hash = stable_hash(self.config)
        self._insert_immutable("config_registry", "config_id", CONFIG_ID, {"config_id": CONFIG_ID, "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_json": config_json, "config_hash": config_hash, "created_at": now}, hash_column="config_hash", expected_hash=config_hash)
        school_scopes = {"classical_price_action": "mechanical price-action patterns and contextual narratives", "dow_theory": "read-only structural interpretation over Group 3", "wyckoff": "explicit non-intent range/event hypotheses", "ict_smc": "read-only contextual relations over Groups 3-7"}
        for school, sid in SCHOOL_IDS.items():
            scope = {"school": school, "scope": school_scopes[school]}; prohibitions = {"trading_outputs": True, "profitability_calibration": True, "preferred_school": True, "upstream_rediscovery": True}; sh = stable_hash({"scope": scope, "prohibitions": prohibitions})
            self._insert_immutable("school_registry", "school_id", sid, {"school_id": sid, "school_version": "1.0.0", "school_name": school, "scope_json": canonical_json(scope), "prohibitions_json": canonical_json(prohibitions), "school_hash": sh}, hash_column="school_hash", expected_hash=sh)
        for definition_id, definition in sorted(self.def_registry["definitions"].items()):
            school_id = SCHOOL_IDS[definition["school"]]; payload = json_safe(definition); h = stable_hash(payload); table = "pattern_definition_registry" if definition["kind"] in PATTERN_KINDS else "interpretation_definition_registry"; kind_col = "definition_kind" if table == "pattern_definition_registry" else "interpretation_kind"
            self._insert_immutable(table, "definition_id", definition_id, {"definition_id": definition_id, "definition_version": definition["version"], "school_id": school_id, kind_col: definition["kind"], "definition_json": canonical_json(payload), "definition_hash": h}, hash_column="definition_hash", expected_hash=h)
        for k,v in (("engine_version",ENGINE_VERSION),("schema_version",SCHEMA_VERSION),("config_id",CONFIG_ID),("design_freeze_hash",EXPECTED_DESIGN_FREEZE_HASH),("year",str(self.year))): self.out.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", (k,v))
        stage = {r["key"]: r["value"] for r in self.input.execute("SELECT key,value FROM stage_manifest")}; identities = json.loads(stage.get("database_identities_json", "{}")); source_ident = identities.get("source", {}); group7_ident = identities.get("group7", {})
        dataset_payload = {"symbol": self.symbol_filter or stage.get("symbol", "ALL"), "year": self.year, "lineage": self.freeze["lineage"], "logical_dependency_lineage_id": EXPECTED_LOGICAL_LINEAGE, "dependency_release_anchor_tag": self.freeze["dependency_release_anchor_tag"], "source": source_ident, "group7": group7_ident, "coherent_lineage_amendment_hash": self.freeze["coherent_lineage_amendment_hash"], "annual_dependency_registry_hash": self.freeze["annual_dependency_registry_hash"], "adapter_map_hash": self.freeze["adapter_map_hash"], "categorical_dictionary_hash": self.freeze["categorical_dictionary_hash"], "value_bindings_hash": self.freeze["value_binding_hash"], "definition_registry_hash": self.freeze["definition_registry_hash"]}
        dataset_id = deterministic_id("g8dataset", dataset_payload); dataset_hash = stable_hash(dataset_payload)
        self._insert_immutable("dataset_registry", "dataset_id", dataset_id, {"dataset_id": dataset_id, "symbol": dataset_payload["symbol"], "year": self.year, "lineage": dataset_payload["lineage"], "logical_dependency_lineage_id": EXPECTED_LOGICAL_LINEAGE, "dependency_release_anchor_tag": dataset_payload["dependency_release_anchor_tag"], "source_db_filename": source_ident.get("filename", "UNKNOWN"), "source_db_size_bytes": int(source_ident.get("size_bytes", 0)), "source_db_sha256": source_ident.get("sha256", "UNKNOWN"), "group7_db_filename": group7_ident.get("filename", "UNKNOWN"), "group7_db_size_bytes": int(group7_ident.get("size_bytes", 0)), "group7_db_sha256": group7_ident.get("sha256", "UNKNOWN"), "group7_logic_source_closure_tag": self.freeze["group7_logic_source"]["closure_tag"], "group7_logic_source_closure_commit_sha": self.freeze["group7_logic_source"]["closure_commit_sha"], "coherent_lineage_amendment_hash": self.freeze["coherent_lineage_amendment_hash"], "annual_dependency_registry_hash": self.freeze["annual_dependency_registry_hash"], "adapter_map_hash": self.freeze["adapter_map_hash"], "categorical_dictionary_hash": self.freeze["categorical_dictionary_hash"], "value_bindings_hash": self.freeze["value_binding_hash"], "definition_registry_hash": self.freeze["definition_registry_hash"], "created_at": 0, "record_hash": dataset_hash}, hash_column="record_hash", expected_hash=dataset_hash)
        for group, ident in sorted(identities.items()):
            dep_payload = {"group": group, **ident, "lineage": EXPECTED_LOGICAL_LINEAGE, "read_only": True}; dep_id = deterministic_id("g8dep", dep_payload); dep_hash = stable_hash(dep_payload)
            self._insert_immutable("dependency_registry", "dependency_id", dep_id, {"dependency_id": dep_id, "group_name": group, "engine_version": ident.get("engine_version"), "schema_version": ident.get("schema_version"), "config_id": ident.get("config_id"), "filename": ident.get("filename"), "size_bytes": ident.get("size_bytes"), "sha256": ident.get("sha256", "UNKNOWN"), "lineage": EXPECTED_LOGICAL_LINEAGE, "read_only": 1, "transitive": 0 if group in {"source","group7"} else 1, "source_dependency_id": None, "adapter_hash": self.adapter["adapter_map_hash"], "record_hash": dep_hash}, hash_column="record_hash", expected_hash=dep_hash)
        self.out.commit()

    def _insert_immutable(self, table: str, id_column: str, row_id: str, row: Mapping[str, Any], *, hash_column: str, expected_hash: str) -> bool:
        columns = list(row); sql = f"INSERT OR IGNORE INTO {_quoted(table)} ({','.join(_quoted(c) for c in columns)}) VALUES ({','.join('?' for _ in columns)})"; cur = self.out.execute(sql, [row[c] for c in columns])
        if cur.rowcount == 1: return True
        existing = self.out.execute(f"SELECT {_quoted(hash_column)} FROM {_quoted(table)} WHERE {_quoted(id_column)}=?", (row_id,)).fetchone()
        if existing is None or existing[0] != expected_hash: raise Group8InvariantError(f"conflicting deterministic duplicate in {table}: {row_id}")
        return False

    def load_bars(self) -> None:
        where = ""; params: list[Any] = []
        if self.symbol_filter: where = " WHERE symbol=?"; params.append(self.symbol_filter)
        rows = self.input.execute("SELECT id,symbol,timeframe,open_time,close_time,available_at,open,high,low,close,tick_volume FROM source__bars" + where + " ORDER BY symbol,timeframe,close_time,id", params).fetchall(); grouped: dict[tuple[str, str], list[Bar]] = defaultdict(list)
        for r in rows:
            b = Bar(id=int(r["id"]), symbol=r["symbol"], timeframe=r["timeframe"], open_time=int(r["open_time"]), close_time=int(r["close_time"]), available_at=int(r["available_at"]), open=float(r["open"]), high=float(r["high"]), low=float(r["low"]), close=float(r["close"]), tick_volume=int(r["tick_volume"]) if r["tick_volume"] is not None else None)
            if b.available_at < b.close_time: raise Group8InvariantError(f"source bar availability before close: {b.id}")
            grouped[(b.symbol, b.timeframe)].append(b)
        self.bars_by_tf = dict(grouped); period = int(self.config["feature_parameters"]["atr_period"])
        for key, bars in self.bars_by_tf.items():
            prev_close: float | None = None; rma: float | None = None; seed: list[float] = []
            for idx, b in enumerate(bars):
                tr = b.high - b.low if prev_close is None else max(b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close))
                if len(seed) < period:
                    seed.append(tr); atr = sum(seed) / period if len(seed) == period else None
                    if atr is not None: rma = atr
                else:
                    assert rma is not None; rma = ((period - 1) * rma + tr) / period; atr = rma
                self.atr_by_bar[b.id] = atr; self.bar_pos[b.id] = (key, idx); prev_close = b.close
        self.annual_end_time = self.annual_end_time or max((b.available_at for bars in self.bars_by_tf.values() for b in bars), default=0); self.point_increment = {sym: self._verified_price_increment(sym) for sym, _ in self.bars_by_tf}

    def _verified_price_increment(self, symbol: str) -> float | None:
        for key in [f"verified_point:{symbol}", f"verified_tick_size:{symbol}", "verified_point", "verified_tick_size"]:
            row = self.input.execute("SELECT value FROM staging_metadata WHERE key=?", (key,)).fetchone()
            if row:
                try: v = float(row[0])
                except (TypeError, ValueError): continue
                if v > 0: return v
        return None

    def _anatomy(self, bar: Bar, prev: Bar | None) -> dict[str, Any]:
        full = bar.high - bar.low; body = abs(bar.close - bar.open); upper_wick = bar.high - max(bar.open, bar.close); lower_wick = min(bar.open, bar.close) - bar.low; atr = self.atr_by_bar.get(bar.id)
        if full == 0: ratios = {"body_to_range": None, "upper_wick_to_range": None, "lower_wick_to_range": None, "open_location": None, "close_location": None}
        else: ratios = {"body_to_range": body / full, "upper_wick_to_range": upper_wick / full, "lower_wick_to_range": lower_wick / full, "open_location": (bar.open - bar.low) / full, "close_location": (bar.close - bar.low) / full}
        overlap = None
        if prev is not None: overlap = max(0.0, min(bar.high, prev.high) - max(bar.low, prev.low)) / max(full, 1e-300)
        return {"full_range": full, "body": body, "upper_wick": upper_wick, "lower_wick": lower_wick, **ratios, "range_to_atr": full / atr if atr not in (None, 0) else None, "body_to_atr": body / atr if atr not in (None, 0) else None, "overlap_with_previous": overlap, "atr14": atr, "degenerate": full == 0, "direction": direction_from_bar(bar.open, bar.close)}

    def _write_pattern(self, definition_id: str, *, symbol: str, timeframe: str, direction: str, event_time: int, confirmation_time: int, availability_time: int, source_bar_id: int | None = None, related_source_bar_id: int | None = None, lower: float | None = None, upper: float | None = None, ambiguous: bool = False, reasons: Sequence[str] = (), features: Mapping[str, Any] | None = None, upstream_refs: Sequence[Mapping[str, Any]] = (), intrinsic_pass: bool = True) -> str:
        if availability_time < confirmation_time or confirmation_time < event_time: raise Group8InvariantError(f"time ordering violation for {definition_id}")
        feature_payload = json_safe(features or {}); refs = [json_safe(r) for r in upstream_refs]; creation = {"definition_id": definition_id, "symbol": symbol, "timeframe": timeframe, "direction": direction, "source_bar_id": source_bar_id, "related_source_bar_id": related_source_bar_id, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "lower": lower, "upper": upper, "intrinsic_pass": bool(intrinsic_pass), "ambiguous": bool(ambiguous), "reasons": list(reasons), "features": feature_payload, "upstream_refs": refs, "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_id": CONFIG_ID}
        cid = deterministic_id("g8p", creation); feature_hash = stable_hash(feature_payload); candidate_hash = stable_hash(creation)
        row = {"candidate_id": cid, "definition_id": definition_id, "symbol": symbol, "timeframe": timeframe, "direction": direction, "source_bar_id": source_bar_id, "related_source_bar_id": related_source_bar_id, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "lower": lower, "upper": upper, "intrinsic_pass": 1 if intrinsic_pass else 0, "ambiguous": 1 if ambiguous else 0, "reasons_json": canonical_json(list(reasons)), "features_json": canonical_json(feature_payload), "upstream_refs_json": canonical_json(refs), "feature_hash": feature_hash, "candidate_hash": candidate_hash}
        self._insert_immutable("price_action_pattern_candidate", "candidate_id", cid, row, hash_column="candidate_hash", expected_hash=candidate_hash)
        self.definition_coverage[definition_id] += 1
        from group8_postprocess_v0_8_0 import ensure_pattern_creation_state
        ensure_pattern_creation_state(self, cid)
        return cid

    def _write_interpretation(self, definition_id: str, *, symbol: str, timeframe: str, direction: str, event_time: int, confirmation_time: int, availability_time: int, upstream_refs: Sequence[Mapping[str, Any]], reasons: Sequence[str] = (), ambiguous: bool = False, complete: bool = True, support_count: int | None = None, conflict_count: int = 0, evidence_strength: Mapping[str, Any] | None = None, lifecycle_state: str | None = None) -> str:
        definition = self.def_registry["definitions"][definition_id]
        if definition["kind"] in PATTERN_KINDS: raise Group8InvariantError(f"{definition_id} is a pattern, not interpretation")
        if availability_time < confirmation_time or confirmation_time < event_time: raise Group8InvariantError(f"time ordering violation for {definition_id}")
        refs = [json_safe(r) for r in upstream_refs]; support_count = len(refs) if support_count is None else int(support_count); lifecycle_state = lifecycle_state or ("active_ambiguous" if ambiguous else "active_supported" if complete else "candidate")
        if lifecycle_state not in LIFECYCLE_STATES: raise Group8InvariantError(f"invalid lifecycle state {lifecycle_state}")
        creation = {"definition_id": definition_id, "school": definition["school"], "symbol": symbol, "timeframe": timeframe, "direction": direction, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "mandatory_evidence_complete": bool(complete), "ambiguous": bool(ambiguous), "supporting_evidence_count": support_count, "conflicting_evidence_count": int(conflict_count), "evidence_strength": json_safe(evidence_strength or {}), "upstream_refs": refs, "reasons": list(reasons), "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_id": CONFIG_ID}
        rid = deterministic_id("g8i", creation); h = stable_hash(creation); sid = SCHOOL_IDS[definition["school"]]
        row = {"interpretation_id": rid, "definition_id": definition_id, "school_id": sid, "symbol": symbol, "timeframe": timeframe, "direction": direction, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "lifecycle_state": lifecycle_state, "mandatory_evidence_complete": 1 if complete else 0, "ambiguous": 1 if ambiguous else 0, "supporting_evidence_count": support_count, "conflicting_evidence_count": int(conflict_count), "evidence_strength_json": canonical_json(json_safe(evidence_strength or {})), "upstream_refs_json": canonical_json(refs), "reasons_json": canonical_json(list(reasons)), "interpretation_hash": h}
        self._insert_immutable("school_interpretation", "interpretation_id", rid, row, hash_column="interpretation_hash", expected_hash=h); self.definition_coverage[definition_id] += 1; self._write_evidence_chain("school_interpretation", rid, refs); return rid

    def _write_hypothesis(self, definition_id: str, *, symbol: str, timeframe: str, direction: str, event_time: int, confirmation_time: int, availability_time: int, upstream_refs: Sequence[Mapping[str, Any]], reasons: Sequence[str] = (), ambiguous: bool = False, complete: bool = True, support_count: int | None = None, conflict_count: int = 0, evidence_strength: Mapping[str, Any] | None = None, initial_state: str | None = None) -> str:
        definition = self.def_registry["definitions"][definition_id]
        if definition["kind"] != "narrative_hypothesis": raise Group8InvariantError(f"{definition_id} is not narrative_hypothesis")
        refs = [json_safe(r) for r in upstream_refs]; support_count = len(refs) if support_count is None else int(support_count); initial_state = initial_state or ("active_ambiguous" if ambiguous else "active_supported" if complete else "candidate")
        creation = {"definition_id": definition_id, "school": definition["school"], "symbol": symbol, "timeframe": timeframe, "direction": direction, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "initial_state": initial_state, "mandatory_evidence_complete": bool(complete), "ambiguous": bool(ambiguous), "supporting_evidence_count": support_count, "conflicting_evidence_count": int(conflict_count), "evidence_strength": json_safe(evidence_strength or {}), "upstream_refs": refs, "reasons": list(reasons), "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "config_id": CONFIG_ID}
        hid = deterministic_id("g8h", creation); h = stable_hash(creation)
        row = {"hypothesis_id": hid, "definition_id": definition_id, "school_id": SCHOOL_IDS[definition["school"]], "symbol": symbol, "timeframe": timeframe, "direction": direction, "event_time": int(event_time), "confirmation_time": int(confirmation_time), "availability_time": int(availability_time), "initial_state": initial_state, "mandatory_evidence_complete": 1 if complete else 0, "ambiguous": 1 if ambiguous else 0, "supporting_evidence_count": support_count, "conflicting_evidence_count": int(conflict_count), "evidence_strength_json": canonical_json(json_safe(evidence_strength or {})), "upstream_refs_json": canonical_json(refs), "reasons_json": canonical_json(list(reasons)), "hypothesis_hash": h}
        self._insert_immutable("narrative_hypothesis", "hypothesis_id", hid, row, hash_column="hypothesis_hash", expected_hash=h)
        self.definition_coverage[definition_id] += 1
        self._write_evidence_chain("narrative_hypothesis", hid, refs)
        from group8_postprocess_v0_8_0 import ensure_initial_hypothesis_lifecycle
        ensure_initial_hypothesis_lifecycle(self, hid, initial_state, event_time=int(event_time), availability_time=int(availability_time))
        return hid

    def _append_lifecycle(self, hypothesis_id: str, state: str, *, event_time: int, availability_time: int, source_type: str | None, source_id: str | None, details: Mapping[str, Any]) -> str:
        if state not in LIFECYCLE_STATES: raise Group8InvariantError(f"invalid lifecycle state {state}")
        base = self.out.execute("SELECT availability_time FROM narrative_hypothesis WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
        if not base or availability_time < int(base[0]): raise Group8InvariantError("lifecycle before hypothesis availability")
        ordinal = self.out.execute("SELECT COALESCE(MAX(lifecycle_ordinal),-1)+1 FROM hypothesis_lifecycle_event WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()[0]; payload = {"hypothesis_id": hypothesis_id, "ordinal": ordinal, "state": state, "source_type": source_type, "source_id": source_id, "event_time": int(event_time), "availability_time": int(availability_time), "details": json_safe(details)}; lid = deterministic_id("g8life", payload); h = stable_hash(payload)
        row = {"lifecycle_event_id": lid, "hypothesis_id": hypothesis_id, "lifecycle_ordinal": ordinal, "source_type": source_type, "source_id": source_id, "event_time": int(event_time), "availability_time": int(availability_time), "lifecycle_state": state, "details_json": canonical_json(json_safe(details)), "lifecycle_hash": h}; self._insert_immutable("hypothesis_lifecycle_event", "lifecycle_event_id", lid, row, hash_column="lifecycle_hash", expected_hash=h); return lid

    def _write_evidence_chain(self, subject_type: str, subject_id: str, refs: Sequence[Mapping[str, Any]]) -> None:
        for ordinal, ref in enumerate(refs):
            source_group = str(ref.get("source_group", "group8")); source_type = str(ref.get("source_type", "unknown")); source_id = str(ref.get("source_id", "")); availability = int(ref.get("availability_time", 0)); payload = {"subject_type": subject_type, "subject_id": subject_id, "ordinal": ordinal, "source_group": source_group, "source_type": source_type, "source_id": source_id, "relation_type": ref.get("relation_type", "mandatory_evidence"), "source_timeframe": ref.get("timeframe"), "event_time": ref.get("event_time"), "availability_time": availability, "details": json_safe(ref.get("details", {}))}; eid = deterministic_id("g8ev", payload); h = stable_hash(payload)
            row = {"evidence_chain_id": eid, "subject_type": subject_type, "subject_id": subject_id, "evidence_ordinal": ordinal, "source_group": source_group, "source_type": source_type, "source_id": source_id, "relation_type": payload["relation_type"], "source_timeframe": payload["source_timeframe"], "event_time": payload["event_time"], "availability_time": availability, "details_json": canonical_json(payload["details"]), "evidence_hash": h}; self._insert_immutable("evidence_chain", "evidence_chain_id", eid, row, hash_column="evidence_hash", expected_hash=h)

    def _ref(self, group: str, source_type: str, source_id: Any, availability_time: Any, *, event_time: Any = None, timeframe: Any = None, relation_type: str = "mandatory_evidence", details: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {"source_group": group, "source_type": source_type, "source_id": str(source_id), "availability_time": int(availability_time), "event_time": int(event_time) if event_time is not None else None, "timeframe": timeframe, "relation_type": relation_type, "details": json_safe(details or {})}

    def process_base_price_action(self) -> None:
        cfg = self.config["pattern_thresholds"]
        for (symbol, tf), bars in sorted(self.bars_by_tf.items()):
            prev: Bar | None = None
            for bar in bars:
                f = self._anatomy(bar, prev); anatomy_id = self._write_pattern("pa_candle_anatomy", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=bar.available_at, lower=bar.low, upper=bar.high, ambiguous=f["degenerate"], reasons=["zero_range"] if f["degenerate"] else [], features=f, upstream_refs=[self._ref("source", "bars", bar.id, bar.available_at, event_time=bar.close_time, timeframe=tf)])
                if not f["degenerate"]:
                    btr = f["body_to_range"]
                    if btr <= cfg["doji_strict_body_to_range_max"]: self._write_pattern("pa_doji_strict", symbol=symbol, timeframe=tf, direction="neutral", source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=bar.available_at, lower=bar.low, upper=bar.high, features={"body_to_range": btr}, upstream_refs=[self._ref("group8", "price_action_pattern_candidate", anatomy_id, bar.available_at)])
                    if btr <= cfg["doji_broad_body_to_range_max"]: self._write_pattern("pa_doji_broad", symbol=symbol, timeframe=tf, direction="neutral", source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=bar.available_at, lower=bar.low, upper=bar.high, features={"body_to_range": btr}, upstream_refs=[self._ref("group8", "price_action_pattern_candidate", anatomy_id, bar.available_at)])
                    uw, lw = f["upper_wick_to_range"], f["lower_wick_to_range"]; dominant, opposite = (lw, uw) if lw >= uw else (uw, lw); shape_dir = "bullish" if lw > uw else "bearish" if uw > lw else "neutral"
                    if dominant >= cfg["pin_dominant_wick_to_range_min"] and btr <= cfg["pin_body_to_range_max"] and opposite <= cfg["pin_opposite_wick_to_range_max"]: self._write_pattern("pa_pin_bar_like", symbol=symbol, timeframe=tf, direction=shape_dir, source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=bar.available_at, lower=bar.low, upper=bar.high, ambiguous=shape_dir == "neutral", features={"dominant_wick_to_range": dominant, "opposite_wick_to_range": opposite, "body_to_range": btr}, upstream_refs=[self._ref("group8", "price_action_pattern_candidate", anatomy_id, bar.available_at)])
                    close_loc = f["close_location"]; lower_reject = lw >= cfg["rejection_wick_to_range_min"] and close_loc >= 1.0 - cfg["rejection_close_outer_fraction"]; upper_reject = uw >= cfg["rejection_wick_to_range_min"] and close_loc <= cfg["rejection_close_outer_fraction"]
                    if lower_reject or upper_reject:
                        rdir = "bullish" if lower_reject and not upper_reject else "bearish" if upper_reject and not lower_reject else "neutral"; self._write_pattern("pa_rejection_close", symbol=symbol, timeframe=tf, direction=rdir, source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=bar.available_at, lower=bar.low, upper=bar.high, ambiguous=rdir == "neutral", features={"lower_wick_to_range": lw, "upper_wick_to_range": uw, "close_location": close_loc}, upstream_refs=[self._ref("group8", "price_action_pattern_candidate", anatomy_id, bar.available_at)])
                if prev is not None:
                    refs = [self._ref("source", "bars", prev.id, prev.available_at, event_time=prev.close_time, timeframe=tf), self._ref("source", "bars", bar.id, bar.available_at, event_time=bar.close_time, timeframe=tf)]; body_lo, body_hi = min(bar.open, bar.close), max(bar.open, bar.close); p_body_lo, p_body_hi = min(prev.open, prev.close), max(prev.open, prev.close)
                    if bar.high <= prev.high and bar.low >= prev.low: self._write_pattern("pa_inside_bar_edge", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=bar.low, upper=bar.high, features={"edge_equal": bar.high == prev.high or bar.low == prev.low}, upstream_refs=refs)
                    if bar.high < prev.high and bar.low > prev.low: self._write_pattern("pa_inside_bar_strict", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=bar.low, upper=bar.high, upstream_refs=refs)
                    if bar.high >= prev.high and bar.low <= prev.low:
                        self._write_pattern("pa_outside_bar_edge", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=bar.low, upper=bar.high, features={"edge_equal": bar.high == prev.high or bar.low == prev.low}, upstream_refs=refs); self._write_pattern("pa_full_range_engulfing", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=bar.low, upper=bar.high, upstream_refs=refs)
                    if bar.high > prev.high and bar.low < prev.low: self._write_pattern("pa_outside_bar_strict", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=bar.low, upper=bar.high, upstream_refs=refs)
                    if body_lo <= p_body_lo and body_hi >= p_body_hi and abs(bar.close - bar.open) > 0:
                        engulf_id = self._write_pattern("pa_body_engulfing", symbol=symbol, timeframe=tf, direction=f["direction"], source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=body_lo, upper=body_hi, upstream_refs=refs); pd = direction_from_bar(prev.open, prev.close); cd = direction_from_bar(bar.open, bar.close)
                        if pd != "neutral" and cd != "neutral" and pd != cd: self._write_pattern("pa_directional_body_engulfing", symbol=symbol, timeframe=tf, direction=cd, source_bar_id=bar.id, related_source_bar_id=prev.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=max_time(bar.available_at, prev.available_at), lower=body_lo, upper=body_hi, upstream_refs=[self._ref("group8", "price_action_pattern_candidate", engulf_id, max_time(bar.available_at, prev.available_at))] + refs)
                prev = bar
        self.out.commit()

    def _binding_values(self, key: str) -> set[str]:
        d = self.bindings.get("bindings", self.bindings); item = d.get(key)
        if isinstance(item, dict) and "values" in item: item = item["values"]
        if item is None: item = self.config.get("resolved_definition_references", {}).get("bindings", {}).get(key, [])
        return {str(v) for v in (item or [])}

    def process_dow(self) -> None:
        adv = self._binding_values("group3.advancing_bias_values"); dec = self._binding_values("group3.declining_bias_values"); ind = self._binding_values("group3.indeterminate_bias_values"); bullish_events = self._binding_values("group3.bullish_transition_event_types"); bearish_events = self._binding_values("group3.bearish_transition_event_types"); bullish_dirs = self._binding_values("group3.bullish_direction_values"); bearish_dirs = self._binding_values("group3.bearish_direction_values"); symbols = sorted({s for s, _ in self.bars_by_tf}); default_symbol = symbols[0] if len(symbols) == 1 else None
        for r in self.input.execute("SELECT * FROM group3__structure_states ORDER BY symbol,timeframe,layer,close_time,state_id"):
            symbol = r["symbol"] or default_symbol or "UNKNOWN"; tf = r["timeframe"]; availability = int(r["close_time"]); bias_values = {str(r["active_bias"]), str(r["sequence_bias"])}; ref = self._ref("group3", "structure_states", r["state_id"], availability, event_time=r["close_time"], timeframe=tf, details={"layer": r["layer"], "protected_high_id": r["protected_high_id"], "protected_low_id": r["protected_low_id"]})
            if bias_values & adv: self._write_interpretation("dow_advancing_structure", symbol=symbol, timeframe=tf, direction="bullish", event_time=int(r["close_time"]), confirmation_time=int(r["close_time"]), availability_time=availability, upstream_refs=[ref])
            if bias_values & dec: self._write_interpretation("dow_declining_structure", symbol=symbol, timeframe=tf, direction="bearish", event_time=int(r["close_time"]), confirmation_time=int(r["close_time"]), availability_time=availability, upstream_refs=[ref])
            if bias_values & ind: self._write_interpretation("dow_indeterminate_structure", symbol=symbol, timeframe=tf, direction="neutral", event_time=int(r["close_time"]), confirmation_time=int(r["close_time"]), availability_time=availability, upstream_refs=[ref], ambiguous=True)
        for r in self.input.execute("SELECT * FROM group3__break_events ORDER BY symbol,timeframe,resolved_time,event_id"):
            if r["resolved_time"] is None: continue
            symbol = r["symbol"] or default_symbol or "UNKNOWN"; tf = r["timeframe"]; avail = int(r["resolved_time"]); event_type = str(r["event_type"]); d = str(r["direction"]); ref = self._ref("group3", "break_events", r["event_id"], avail, event_time=r["candidate_time"], timeframe=tf, details={"layer": r["layer"], "event_type": event_type, "direction": d, "outcome": r["outcome"]})
            if event_type in bullish_events and d in bullish_dirs: self._write_interpretation("dow_bullish_transition", symbol=symbol, timeframe=tf, direction="bullish", event_time=int(r["candidate_time"]), confirmation_time=avail, availability_time=avail, upstream_refs=[ref])
            if event_type in bearish_events and d in bearish_dirs: self._write_interpretation("dow_bearish_transition", symbol=symbol, timeframe=tf, direction="bearish", event_time=int(r["candidate_time"]), confirmation_time=avail, availability_time=avail, upstream_refs=[ref])
        self.out.commit()

    def _active_zone_status_at(self, zone_id: str, base_status: str, availability: int) -> str:
        row = self.input.execute("SELECT to_status FROM group4__zone_transitions WHERE zone_id=? AND transition_time<=? ORDER BY transition_time DESC,transition_id DESC LIMIT 1", (zone_id, availability)).fetchone()
        if row: return str(row[0])
        row = self.input.execute("SELECT status_after FROM group4__zone_interactions WHERE zone_id=? AND interaction_time<=? ORDER BY interaction_time DESC,interaction_id DESC LIMIT 1", (zone_id, availability)).fetchone()
        return str(row[0]) if row else "active"

    @staticmethod
    def _status_active(status: str | None) -> bool:
        s = (status or "").lower(); return not any(x in s for x in ("invalid", "expired", "broken", "deleted", "inactive"))

    def process_bounded_ranges(self) -> None:
        for (symbol, tf), bars in sorted(self.bars_by_tf.items()):
            zones = [dict(r) for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=? ORDER BY available_at,zone_id", (symbol, tf))]; layers = sorted({str(z["layer"]) for z in zones})
            for bar in bars:
                for layer in layers:
                    active = []
                    for z in zones:
                        if str(z["layer"]) != layer or int(z["available_at"]) > bar.available_at: continue
                        if z["expires_at"] is not None and int(z["expires_at"]) < bar.available_at: continue
                        if not self._status_active(self._active_zone_status_at(str(z["zone_id"]), str(z["status"]), bar.available_at)): continue
                        active.append(z)
                    below = [z for z in active if float(z["upper"]) < bar.close]; above = [z for z in active if float(z["lower"]) > bar.close]
                    if not below or not above: continue
                    max_upper = max(float(z["upper"]) for z in below); min_lower = min(float(z["lower"]) for z in above); lowers = [z for z in below if float(z["upper"]) == max_upper]; uppers = [z for z in above if float(z["lower"]) == min_lower]
                    for lo in lowers:
                        for hi in uppers:
                            lower, upper = float(lo["upper"]), float(hi["lower"])
                            if lower >= upper: continue
                            avail = max_time(bar.available_at, lo["available_at"], hi["available_at"]); self._write_pattern("pa_bounded_range_context", symbol=symbol, timeframe=tf, direction="neutral", source_bar_id=bar.id, event_time=bar.close_time, confirmation_time=bar.close_time, availability_time=avail, lower=lower, upper=upper, features={"midpoint": (lower+upper)/2, "layer": layer, "lower_zone_id": lo["zone_id"], "upper_zone_id": hi["zone_id"]}, upstream_refs=[self._ref("source","bars",bar.id,bar.available_at,event_time=bar.close_time,timeframe=tf), self._ref("group4","zones",lo["zone_id"],lo["available_at"],event_time=lo["origin_time"],timeframe=tf), self._ref("group4","zones",hi["zone_id"],hi["available_at"],event_time=hi["origin_time"],timeframe=tf)])
        self.out.commit()

    def _boundary_rows_for_bar(self, bar: Bar) -> Iterator[dict[str, Any]]:
        for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=? AND available_at<=? AND (expires_at IS NULL OR expires_at>=?)", (bar.symbol, bar.timeframe, bar.available_at, bar.available_at)):
            if not self._status_active(self._active_zone_status_at(str(r["zone_id"]), str(r["status"]), bar.available_at)): continue
            yield {"group":"group4","type":"zones","id":r["zone_id"],"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])}
        for r in self.input.execute("SELECT * FROM group5__liquidity_pools WHERE symbol=? AND timeframe=? AND available_at<=? AND (expires_at IS NULL OR expires_at>=?)", (bar.symbol, bar.timeframe, bar.available_at, bar.available_at)):
            vals = [("anchor",r["anchor_price"]),("lower",r["lower"]),("upper",r["upper"])]; seen=set()
            for label,val in vals:
                if val is None or float(val) in seen: continue
                seen.add(float(val)); yield {"group":"group5","type":"liquidity_pools","id":f"{r['pool_id']}:{label}","source_id":r["pool_id"],"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(val),"upper":float(val)}
        for t,idc,avc,lowc,upc,eventc in [("fvg_events","fvg_id","availability_time","lower","upper","creation_time"),("imbalance_variants","variant_id","availability_time","lower","upper","availability_time"),("liquidity_voids","void_id","availability_time","lower","upper","start_time"),("bpr_relations","bpr_id","availability_time","lower","upper","creation_time")]:
            cols = {x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")}; event_expr = eventc if eventc in cols else avc
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=? AND {avc}<=?", (bar.timeframe, bar.available_at,)): yield {"group":"group6","type":t,"id":r["id"],"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"])}
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=? AND availability_time<=?", (bar.timeframe, bar.available_at)):
            tr = self.input.execute("SELECT status FROM group7__zone_state_transitions WHERE zone_id=? AND transition_time<=? ORDER BY transition_time DESC,transition_ordinal DESC LIMIT 1", (r["zone_id"], bar.available_at)).fetchone()
            if tr and not self._status_active(str(tr[0])): continue
            yield {"group":"group7","type":"institutional_zones","id":r["zone_id"],"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])}
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=? AND availability_time<=?", (bar.symbol,bar.timeframe,bar.available_at)): yield {"group":"group8","type":"pa_bounded_range_context","id":r["candidate_id"],"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])}

    def _pa7_boundary_catalog(self, symbol: str, tf: str) -> list[dict[str, Any]]:
        """Load each PA7 boundary identity once; eligibility is checked causally later."""
        rows: list[dict[str, Any]] = []
        for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=?", (symbol, tf)):
            rows.append({"group":"group4","type":"zones","id":str(r["zone_id"]),"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(r["lower"]),"upper":float(r["upper"]),"expires_at":int(r["expires_at"]) if r["expires_at"] is not None else None,"base_status":str(r["status"] or "active")})
        for r in self.input.execute("SELECT * FROM group5__liquidity_pools WHERE symbol=? AND timeframe=?", (symbol, tf)):
            vals=[("anchor",r["anchor_price"]),("lower",r["lower"]),("upper",r["upper"])]; seen=set()
            for label,val in vals:
                if val is None or float(val) in seen: continue
                seen.add(float(val)); rows.append({"group":"group5","type":"liquidity_pools","id":f"{r['pool_id']}:{label}","source_id":str(r["pool_id"]),"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(val),"upper":float(val),"expires_at":int(r["expires_at"]) if r["expires_at"] is not None else None})
        fvg_terminal={str(r["fvg_id"]):int(r["inactive_at"]) for r in self.input.execute("SELECT fvg_id,MIN(transition_time) inactive_at FROM group6__fvg_state_transitions WHERE lower(event_type)='traversed' AND lower(directional_validity)='invalidated' GROUP BY fvg_id")}
        for t,idc,avc,lowc,upc,eventc in [("fvg_events","fvg_id","availability_time","lower","upper","creation_time"),("imbalance_variants","variant_id","availability_time","lower","upper","availability_time"),("liquidity_voids","void_id","availability_time","lower","upper","start_time"),("bpr_relations","bpr_id","availability_time","lower","upper","creation_time")]:
            cols={x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")}; event_expr=eventc if eventc in cols else avc
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=?", (tf,)):
                inactive=fvg_terminal.get(str(r["id"])) if t=="fvg_events" else None
                rows.append({"group":"group6","type":t,"id":str(r["id"]),"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"]),"inactive_at":inactive})
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=?", (tf,)):
            rows.append({"group":"group7","type":"institutional_zones","id":str(r["zone_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        zone_invalidations: dict[str,list[int]]={}
        for r in self.input.execute("SELECT zone_id,transition_time,to_status FROM group4__zone_transitions ORDER BY zone_id,transition_time,transition_id"):
            if not self._status_active(str(r["to_status"])): zone_invalidations.setdefault(str(r["zone_id"]),[]).append(int(r["transition_time"]))
        for r in self.input.execute("SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions ORDER BY zone_id,interaction_time,interaction_id"):
            if not self._status_active(str(r["status_after"])): zone_invalidations.setdefault(str(r["zone_id"]),[]).append(int(r["interaction_time"]))
        for times in zone_invalidations.values(): times.sort()
        import bisect
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper,features_json FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?", (symbol,tf)):
            start=int(r["availability_time"]); features=json.loads(r["features_json"]); invalidations=[]
            for zid in (features.get("lower_zone_id"),features.get("upper_zone_id")):
                times=zone_invalidations.get(str(zid),[]) if zid is not None else []
                pos=bisect.bisect_right(times,start)
                if pos<len(times): invalidations.append(int(times[pos]))
            inactive=min(invalidations) if invalidations else None
            rows.append({"group":"group8","type":"pa_bounded_range_context","id":str(r["candidate_id"]),"availability":start,"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"]),"inactive_at":inactive})
        return rows

    def _pa7_boundary_active_at(self, bnd: Mapping[str, Any], availability: int) -> bool:
        if int(bnd["availability"]) > int(availability): return False
        inactive=bnd.get("inactive_at")
        if inactive is not None and int(availability) >= int(inactive): return False
        expires=bnd.get("expires_at")
        if expires is not None and int(expires) < int(availability): return False
        if bnd["group"]=="group4":
            return self._status_active(self._active_zone_status_at(str(bnd["id"]),str(bnd.get("base_status","active")),int(availability)))
        if bnd["group"]=="group7":
            tr=self.input.execute("SELECT status FROM group7__zone_state_transitions WHERE zone_id=? AND transition_time<=? ORDER BY transition_time DESC,transition_ordinal DESC LIMIT 1", (bnd["id"],int(availability))).fetchone()
            return not tr or self._status_active(str(tr[0]))
        return True

    def _pa7_beyond(self, definition_id: str, direction: str, bar: Bar, bnd: Mapping[str, Any], *, increment: float | None, atr_fraction: float) -> bool | None:
        level=float(bnd["upper"] if direction=="bullish" else bnd["lower"])
        if definition_id=="pa_breakout_exact":
            return bar.close>level if direction=="bullish" else bar.close<level
        if definition_id=="pa_breakout_point_buffer":
            if increment is None: return None
            return bar.close>=level+increment if direction=="bullish" else bar.close<=level-increment
        if definition_id=="pa_breakout_atr_buffer":
            atr=self.atr_by_bar.get(bar.id)
            if atr in (None,0): return None
            buffer=atr_fraction*float(atr)
            return bar.close>=level+buffer if direction=="bullish" else bar.close<=level-buffer
        raise Group8InvariantError(f"unknown PA7 variant {definition_id}")

    def _pa7_state_boundary_identity(self, bnd: Mapping[str, Any], direction: str) -> str:
        side="upper" if direction=="bullish" else "lower"
        return f"{bnd['group']}:{bnd['type']}:{bnd['id']}:{side}"

    def _pa7_emit_transition(self, definition_id: str, direction: str, bar: Bar, bnd: Mapping[str, Any], *, increment: float | None, atr_fraction: float, previous_bar_id: int | None, initialization_transition: bool) -> None:
        side="upper" if direction=="bullish" else "lower"; level=float(bnd["upper"] if direction=="bullish" else bnd["lower"])
        state_boundary_identity=self._pa7_state_boundary_identity(bnd,direction)
        state_payload={"symbol":bar.symbol,"timeframe":bar.timeframe,"direction":direction,"boundary_identity":state_boundary_identity,"variant":definition_id}
        state_key=deterministic_id("g8pa7state",state_payload)
        features={"boundary_identity":bnd["id"],"state_boundary_identity":state_boundary_identity,"boundary_side":side,"locked_level":level,"pa7_variant":definition_id,"state_key":state_key,"transition_from":"NOT_BEYOND_BOUNDARY","transition_to":"BEYOND_BOUNDARY","previous_eligible_bar_id":previous_bar_id,"initialization_transition":bool(initialization_transition)}
        if definition_id=="pa_breakout_point_buffer": features["verified_increment"]=increment
        elif definition_id=="pa_breakout_atr_buffer":
            atr=self.atr_by_bar.get(bar.id); features["atr14"]=atr; features["buffer"]=atr_fraction*float(atr) if atr not in (None,0) else None
        avail=max_time(bar.available_at,bnd["availability"])
        refs=[self._ref("source","bars",bar.id,bar.available_at,event_time=bar.close_time,timeframe=bar.timeframe),self._ref(bnd["group"],bnd["type"],bnd.get("source_id",bnd["id"]),bnd["availability"],event_time=bnd["event"],timeframe=bar.timeframe,details={"boundary_identity":bnd["id"],"state_boundary_identity":state_boundary_identity,"lower":bnd["lower"],"upper":bnd["upper"]})]
        self._write_pattern(definition_id,symbol=bar.symbol,timeframe=bar.timeframe,direction=direction,source_bar_id=bar.id,event_time=bar.close_time,confirmation_time=bar.close_time,availability_time=avail,lower=level,upper=level,features=features,upstream_refs=refs)

    @staticmethod
    def _pa7_window(levels: Sequence[float], *, definition_id: str, direction: str, previous_bar: Bar, bar: Bar, previous_atr: float | None, current_atr: float | None, increment: float | None, atr_fraction: float) -> tuple[int,int] | None:
        import bisect
        if definition_id=="pa_breakout_exact":
            if direction=="bullish":
                if bar.close<=previous_bar.close: return None
                return bisect.bisect_left(levels,previous_bar.close),bisect.bisect_left(levels,bar.close)
            if bar.close>=previous_bar.close: return None
            return bisect.bisect_right(levels,bar.close),bisect.bisect_right(levels,previous_bar.close)
        if definition_id=="pa_breakout_point_buffer":
            if increment is None: return None
            prev_adj=previous_bar.close-increment if direction=="bullish" else previous_bar.close+increment
            cur_adj=bar.close-increment if direction=="bullish" else bar.close+increment
        elif definition_id=="pa_breakout_atr_buffer":
            if previous_atr in (None,0) or current_atr in (None,0): return None
            prev_buf=atr_fraction*float(previous_atr); cur_buf=atr_fraction*float(current_atr)
            prev_adj=previous_bar.close-prev_buf if direction=="bullish" else previous_bar.close+prev_buf
            cur_adj=bar.close-cur_buf if direction=="bullish" else bar.close+cur_buf
        else:
            raise Group8InvariantError(f"unknown PA7 variant {definition_id}")
        if direction=="bullish":
            if cur_adj<=prev_adj: return None
            return bisect.bisect_right(levels,prev_adj),bisect.bisect_right(levels,cur_adj)
        if cur_adj>=prev_adj: return None
        return bisect.bisect_left(levels,cur_adj),bisect.bisect_left(levels,prev_adj)

    def process_breakouts(self) -> None:
        """Emit only causal PA7 NOT_BEYOND -> BEYOND transition events.

        The level-indexed sweep is semantically required by PA7E/A/P.2 and avoids
        persistent-state bar×boundary materialization. Re-arm is causal: after a
        prior eligible bar is NOT_BEYOND, a later qualifying close may transition
        again. Newly available boundaries initialize in NOT_BEYOND and may
        transition on their first causally eligible confirmed close.
        """
        import bisect
        atr_fraction=float(self.config["pattern_thresholds"]["atr_buffer_breakout_fraction"])
        variants=("pa_breakout_exact","pa_breakout_point_buffer","pa_breakout_atr_buffer")
        for (symbol,tf),bars in sorted(self.bars_by_tf.items()):
            increment=self.point_increment.get(symbol); catalog=self._pa7_boundary_catalog(symbol,tf)
            by_avail=sorted(catalog,key=lambda b:(int(b["availability"]),b["group"],b["type"],b["id"]))
            avail_keys=[int(b["availability"]) for b in by_avail]
            upper=sorted(catalog,key=lambda b:(float(b["upper"]),b["group"],b["type"],b["id"])); upper_levels=[float(b["upper"]) for b in upper]
            lower=sorted(catalog,key=lambda b:(float(b["lower"]),b["group"],b["type"],b["id"])); lower_levels=[float(b["lower"]) for b in lower]
            for idx,bar in enumerate(bars):
                prev=bars[idx-1] if idx else None; current_atr=self.atr_by_bar.get(bar.id); previous_atr=self.atr_by_bar.get(prev.id) if prev else None
                for definition_id in variants:
                    if definition_id=="pa_breakout_point_buffer" and increment is None: continue
                    current_evaluable=definition_id!="pa_breakout_atr_buffer" or current_atr not in (None,0)
                    if not current_evaluable: continue
                    previous_evaluable=prev is not None and (definition_id!="pa_breakout_atr_buffer" or previous_atr not in (None,0))
                    emitted: set[tuple[str,str,str,str]] = set()
                    if previous_evaluable and prev is not None:
                        for direction,entries,levels in (("bullish",upper,upper_levels),("bearish",lower,lower_levels)):
                            window=self._pa7_window(levels,definition_id=definition_id,direction=direction,previous_bar=prev,bar=bar,previous_atr=previous_atr,current_atr=current_atr,increment=increment,atr_fraction=atr_fraction)
                            if window is None: continue
                            lo,hi=window
                            for bnd in entries[lo:hi]:
                                if int(bnd["availability"])>prev.available_at: continue
                                if not self._pa7_boundary_active_at(bnd,prev.available_at) or not self._pa7_boundary_active_at(bnd,bar.available_at): continue
                                key=(bnd["group"],bnd["type"],bnd["id"],direction)
                                if key in emitted: continue
                                if self._pa7_beyond(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction) is True:
                                    self._pa7_emit_transition(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction,previous_bar_id=prev.id,initialization_transition=False); emitted.add(key)
                    if previous_evaluable and prev is not None:
                        a=bisect.bisect_right(avail_keys,prev.available_at); z=bisect.bisect_right(avail_keys,bar.available_at); initial_candidates=by_avail[a:z]
                    else:
                        z=bisect.bisect_right(avail_keys,bar.available_at); initial_candidates=by_avail[:z]
                    for bnd in initial_candidates:
                        if not self._pa7_boundary_active_at(bnd,bar.available_at): continue
                        for direction in ("bullish","bearish"):
                            key=(bnd["group"],bnd["type"],bnd["id"],direction)
                            if key in emitted: continue
                            if self._pa7_beyond(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction) is True:
                                self._pa7_emit_transition(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction,previous_bar_id=None,initialization_transition=True); emitted.add(key)
        self.out.commit()

    def process_context_rejections(self) -> None:
        rejections = self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') ORDER BY availability_time,candidate_id").fetchall()
        for p in rejections:
            bar = self._bar_by_id(p["source_bar_id"])
            if bar is None: continue
            atr = self.atr_by_bar.get(bar.id); increment = self.point_increment.get(bar.symbol); tol = max([x for x in (increment, (self.config["feature_parameters"]["proximity_atr_fraction"]*atr if atr else None)) if x is not None], default=0.0)
            for bnd in self._boundary_rows_for_bar(bar):
                if bnd["availability"] > p["availability_time"]: continue
                pl,pu=float(p["lower"]),float(p["upper"]); bl,bu=bnd["lower"],bnd["upper"]; overlap=max(0.0,min(pu,bu)-max(pl,bl)); distance=0.0 if overlap>0 else min(abs(pl-bu),abs(bl-pu))
                if overlap>0 or distance<=tol: self._write_pattern("pa_context_linked_rejection",symbol=bar.symbol,timeframe=bar.timeframe,direction=p["direction"],source_bar_id=bar.id,event_time=int(p["event_time"]),confirmation_time=int(p["confirmation_time"]),availability_time=max_time(p["availability_time"],bnd["availability"]),lower=pl,upper=pu,ambiguous=bool(p["ambiguous"]),features={"overlap":overlap,"distance":distance,"tolerance":tol,"boundary_identity":bnd["id"]},upstream_refs=[self._ref("group8","price_action_pattern_candidate",p["candidate_id"],p["availability_time"]),self._ref(bnd["group"],bnd["type"],bnd.get("source_id",bnd["id"]),bnd["availability"],event_time=bnd["event"],timeframe=bar.timeframe)])
        self.out.commit()

    def _bar_by_id(self, bar_id: int | None) -> Bar | None:
        if bar_id is None or bar_id not in self.bar_pos: return None
        key, idx = self.bar_pos[bar_id]; return self.bars_by_tf[key][idx]

    def process_failed_breakouts_and_retests(self) -> None:
        breakouts = self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer') ORDER BY availability_time,candidate_id").fetchall()
        for br in breakouts:
            src = self._bar_by_id(br["source_bar_id"])
            if src is None: continue
            key, idx = self.bar_pos[src.id]; bars=self.bars_by_tf[key]; feats=json.loads(br["features_json"]); level=float(feats["locked_level"]); d=br["direction"]; failed=None
            for later in bars[idx+1:]:
                if later.available_at<=br["availability_time"]: continue
                if (d=="bullish" and later.close<level) or (d=="bearish" and later.close>level): failed=later;break
            if failed: self._write_pattern("pa_failed_breakout",symbol=src.symbol,timeframe=src.timeframe,direction="bearish" if d=="bullish" else "bullish",source_bar_id=failed.id,related_source_bar_id=src.id,event_time=failed.close_time,confirmation_time=failed.close_time,availability_time=failed.available_at,lower=level,upper=level,features={"breakout_candidate_id":br["candidate_id"],"boundary_identity":feats["boundary_identity"],"locked_level":level},upstream_refs=[self._ref("group8","price_action_pattern_candidate",br["candidate_id"],br["availability_time"]),self._ref("source","bars",failed.id,failed.available_at,event_time=failed.close_time,timeframe=src.timeframe)])
            band_lo=level; band_hi=level
            if br["definition_id"]=="pa_breakout_point_buffer": inc=float(feats.get("verified_increment",0)); band_lo=level-inc;band_hi=level+inc
            elif br["definition_id"]=="pa_breakout_atr_buffer": buf=float(feats.get("buffer",0));band_lo=level-buf;band_hi=level+buf
            seen_non_overlap=False; ret=None; duration=0; max_pen=0.0
            for later in bars[idx+1:]:
                duration+=1; overlaps=later.high>=band_lo and later.low<=band_hi
                if not overlaps: seen_non_overlap=True; continue
                if seen_non_overlap: ret=later; max_pen=max(0.0,min(later.high,band_hi)-max(later.low,band_lo)); break
            if ret: self._write_pattern("pa_retest",symbol=src.symbol,timeframe=src.timeframe,direction=d,source_bar_id=ret.id,related_source_bar_id=src.id,event_time=ret.close_time,confirmation_time=ret.close_time,availability_time=ret.available_at,lower=band_lo,upper=band_hi,features={"breakout_candidate_id":br["candidate_id"],"touch":True,"penetration":max_pen,"close_side":"above" if ret.close>level else "below" if ret.close<level else "equal","duration_bars":duration,"max_penetration":max_pen,"right_censored":False},upstream_refs=[self._ref("group8","price_action_pattern_candidate",br["candidate_id"],br["availability_time"]),self._ref("source","bars",ret.id,ret.available_at,event_time=ret.close_time,timeframe=src.timeframe)])
        self.out.commit()

    def _validated_legs(self) -> Iterator[sqlite3.Row]:
        sql = """SELECT l.*,v.validation_id,v.confirmation_time AS validation_confirmation_time,v.availability_time AS validation_availability,v.result AS validation_result FROM group6__displacement_legs l JOIN group6__displacement_validation_events v ON v.leg_id=l.leg_id WHERE lower(COALESCE(v.result,'')) IN ('pass','validated','true','1','accepted','valid') OR lower(COALESCE(v.validation_type,'')) LIKE '%valid%' ORDER BY v.availability_time,l.leg_id"""; yield from self.input.execute(sql)

    def process_structural_narratives(self) -> None:
        from group8_postprocess_v0_8_0 import continuation_structure_valid
        states=[dict(r) for r in self.input.execute("SELECT * FROM group3__structure_states ORDER BY close_time,state_id")]; legs=[dict(r) for r in self._validated_legs()]; symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"
        for st in states:
            sd=normalize_direction(st["active_bias"] if st["active_bias"] not in (None,"unknown","transition") else st["sequence_bias"])
            if sd=="neutral": continue
            for leg in legs:
                if leg["timeframe"]!=st["timeframe"] or int(leg["validation_availability"])<int(st["close_time"]): continue
                ld=normalize_direction(leg["direction"])
                if ld=="neutral" or ld==sd: continue
                newer=self.input.execute("SELECT 1 FROM group3__structure_states WHERE symbol=? AND timeframe=? AND layer=? AND close_time>? AND close_time<=? LIMIT 1", (st["symbol"],st["timeframe"],st["layer"],st["close_time"],leg["validation_availability"])).fetchone()
                if newer: continue
                refs=[self._ref("group3","structure_states",st["state_id"],st["close_time"],event_time=st["close_time"],timeframe=st["timeframe"],details={"layer":st["layer"]}), self._ref("group6","displacement_legs",leg["leg_id"],leg["availability_time"],event_time=leg["end_time"],timeframe=leg["timeframe"]), self._ref("group6","displacement_validation_events",leg["validation_id"],leg["validation_availability"],event_time=leg["validation_confirmation_time"],timeframe=leg["timeframe"])]
                hid=self._write_hypothesis("pa_structural_pullback",symbol=st["symbol"] or default_symbol,timeframe=st["timeframe"],direction=sd,event_time=int(leg["end_time"]),confirmation_time=int(leg["validation_confirmation_time"]),availability_time=max_time(st["close_time"],leg["validation_availability"]),upstream_refs=refs,evidence_strength={"counter_direction_displacement":1,"structure_layer":st["layer"]}); dow_def="dow_advancing_structure" if sd=="bullish" else "dow_declining_structure"; dow=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id=? AND timeframe=? AND json_extract(upstream_refs_json,'$[0].source_id')=? ORDER BY availability_time LIMIT 1",(dow_def,st["timeframe"],st["state_id"])).fetchone()
                if dow: self._write_interpretation("dow_protected_pullback",symbol=st["symbol"] or default_symbol,timeframe=st["timeframe"],direction=sd,event_time=int(leg["end_time"]),confirmation_time=int(leg["validation_confirmation_time"]),availability_time=max_time(dow["availability_time"],leg["validation_availability"]),upstream_refs=[self._ref("group8","school_interpretation",dow["interpretation_id"],dow["availability_time"]),self._ref("group8","narrative_hypothesis",hid,max_time(st["close_time"],leg["validation_availability"]))])
                later=next((x for x in legs if x["timeframe"]==st["timeframe"] and normalize_direction(x["direction"])==sd and int(x["validation_availability"])>int(leg["validation_availability"])),None)
                if later and continuation_structure_valid(self, st, leg, later, sd): self._write_hypothesis("pa_continuation_after_pullback",symbol=st["symbol"] or default_symbol,timeframe=st["timeframe"],direction=sd,event_time=int(leg["end_time"]),confirmation_time=int(later["validation_confirmation_time"]),availability_time=max_time(st["close_time"],leg["validation_availability"],later["validation_availability"]),upstream_refs=[self._ref("group8","narrative_hypothesis",hid,max_time(st["close_time"],leg["validation_availability"])),self._ref("group6","displacement_legs",later["leg_id"],later["availability_time"],event_time=later["end_time"],timeframe=later["timeframe"]),self._ref("group6","displacement_validation_events",later["validation_id"],later["validation_availability"],event_time=later["validation_confirmation_time"],timeframe=later["timeframe"])])
        for fb in self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_failed_breakout'").fetchall():
            rej=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') AND source_bar_id=? AND direction=? ORDER BY candidate_id LIMIT 1",(fb["source_bar_id"],fb["direction"])).fetchone()
            if rej: self._write_hypothesis("pa_exhaustion_failed_breakout",symbol=fb["symbol"],timeframe=fb["timeframe"],direction=fb["direction"],event_time=int(fb["event_time"]),confirmation_time=max_time(fb["confirmation_time"],rej["confirmation_time"]),availability_time=max_time(fb["availability_time"],rej["availability_time"]),upstream_refs=[self._ref("group8","price_action_pattern_candidate",fb["candidate_id"],fb["availability_time"]),self._ref("group8","price_action_pattern_candidate",rej["candidate_id"],rej["availability_time"])])
        self.out.commit()

    def process_wyckoff(self) -> None:
        ranges=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchall()
        for rg in ranges:
            feats=json.loads(rg["features_json"]); layer=feats.get("layer"); dows=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id='dow_indeterminate_structure' AND symbol=? AND timeframe=? AND availability_time<=?",(rg["symbol"],rg["timeframe"],rg["availability_time"])).fetchall()
            for dow in dows:
                drefs=json.loads(dow["upstream_refs_json"]);dlayer=(drefs[0].get("details") or {}).get("layer") if drefs else None
                if layer is not None and dlayer is not None and str(layer)!=str(dlayer): continue
                iid=self._write_interpretation("wyckoff_range_context",symbol=rg["symbol"],timeframe=rg["timeframe"],direction="neutral",event_time=max_time(rg["event_time"],dow["event_time"]),confirmation_time=max_time(rg["confirmation_time"],dow["confirmation_time"]),availability_time=max_time(rg["availability_time"],dow["availability_time"]),ambiguous=True,upstream_refs=[self._ref("group8","price_action_pattern_candidate",rg["candidate_id"],rg["availability_time"]),self._ref("group8","school_interpretation",dow["interpretation_id"],dow["availability_time"])],evidence_strength={"range_context":1,"indeterminate_structure":1}); tol_base=float(self.config["feature_parameters"]["proximity_atr_fraction"])
                for ev in self.input.execute("SELECT e.*,p.symbol,p.anchor_price,p.lower,p.upper,p.available_at AS pool_available_at,p.origin_atr FROM group5__liquidity_events e JOIN group5__liquidity_pools p ON p.pool_id=e.pool_id WHERE p.symbol=? AND e.timeframe=? AND e.resolved_time IS NOT NULL AND e.resolved_time>=?",(rg["symbol"],rg["timeframe"],rg["availability_time"])):
                    if not (ev["reclaimed"] and (ev["is_sweep"] or ev["is_stop_run"] or ev["is_false_breakout"])): continue
                    event_av=int(ev["resolved_time"]); pool_av=int(ev["pool_available_at"]); atr=float(ev["origin_atr"] or 0); inc=self.point_increment.get(rg["symbol"]);tol=max([x for x in (inc,tol_base*atr if atr else None) if x is not None],default=0.0); anchor=float(ev["anchor_price"] if ev["anchor_price"] is not None else (ev["lower"]+ev["upper"])/2)
                    for definition,bound,dir_ in [("wyckoff_spring_candidate",float(rg["lower"]),"bullish"),("wyckoff_upthrust_candidate",float(rg["upper"]),"bearish")]:
                        if abs(anchor-bound)>tol: continue
                        self._write_interpretation(definition,symbol=rg["symbol"],timeframe=rg["timeframe"],direction=dir_,event_time=int(ev["candidate_time"]),confirmation_time=event_av,availability_time=max_time(max_time(rg["availability_time"],dow["availability_time"]),event_av,pool_av),upstream_refs=[self._ref("group8","school_interpretation",iid,max_time(rg["availability_time"],dow["availability_time"])),self._ref("group5","liquidity_events",ev["event_id"],event_av,event_time=ev["candidate_time"],timeframe=rg["timeframe"]),self._ref("group5","liquidity_pools",ev["pool_id"],pool_av,timeframe=rg["timeframe"])],evidence_strength={"boundary_distance":abs(anchor-bound),"tolerance":tol})
        wy_ranges=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id='wyckoff_range_context'").fetchall(); valid_legs=[dict(r) for r in self._validated_legs()]
        for wr in wy_ranges:
            rgref=next((x for x in json.loads(wr["upstream_refs_json"]) if x.get("source_type")=="price_action_pattern_candidate"),None)
            if not rgref: continue
            rg=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE candidate_id=?",(rgref["source_id"],)).fetchone()
            if not rg:continue
            for d,definition,breakdir in [("bullish","wyckoff_sign_of_strength","bullish"),("bearish","wyckoff_sign_of_weakness","bearish")]:
                for leg in valid_legs:
                    if leg["timeframe"]!=wr["timeframe"] or normalize_direction(leg["direction"])!=d: continue
                    brs=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_breakout_exact' AND symbol=? AND timeframe=? AND direction=? AND availability_time>=? ORDER BY availability_time",(wr["symbol"],wr["timeframe"],breakdir,leg["validation_availability"])).fetchall(); target=float(rg["upper"] if d=="bullish" else rg["lower"])
                    for br in brs:
                        if abs(float(br["lower"])-target)>1e-12: continue
                        sign=self._write_interpretation(definition,symbol=wr["symbol"],timeframe=wr["timeframe"],direction=d,event_time=int(br["event_time"]),confirmation_time=int(br["confirmation_time"]),availability_time=max_time(wr["availability_time"],leg["validation_availability"],br["availability_time"]),upstream_refs=[self._ref("group8","school_interpretation",wr["interpretation_id"],wr["availability_time"]),self._ref("group6","displacement_legs",leg["leg_id"],leg["availability_time"],event_time=leg["end_time"],timeframe=leg["timeframe"]),self._ref("group8","price_action_pattern_candidate",br["candidate_id"],br["availability_time"])])
                        ret=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_retest' AND symbol=? AND timeframe=? AND availability_time>? AND ABS(lower-?)<1e-12 ORDER BY availability_time LIMIT 1",(wr["symbol"],wr["timeframe"],br["availability_time"],target)).fetchone()
                        if ret:
                            ldef="wyckoff_last_point_of_support" if d=="bullish" else "wyckoff_last_point_of_supply"; self._write_interpretation(ldef,symbol=wr["symbol"],timeframe=wr["timeframe"],direction=d,event_time=int(ret["event_time"]),confirmation_time=int(ret["confirmation_time"]),availability_time=max_time(max_time(wr["availability_time"],leg["validation_availability"],br["availability_time"]),ret["availability_time"]),upstream_refs=[self._ref("group8","school_interpretation",sign,max_time(wr["availability_time"],leg["validation_availability"],br["availability_time"])),self._ref("group8","price_action_pattern_candidate",ret["candidate_id"],ret["availability_time"])])
                        break
        for spring_def, sign_def, hyp_def, direction, prior_def, rehyp in [("wyckoff_spring_candidate","wyckoff_sign_of_strength","wyckoff_accumulation_hypothesis","bullish","dow_advancing_structure","wyckoff_reaccumulation_hypothesis"),("wyckoff_upthrust_candidate","wyckoff_sign_of_weakness","wyckoff_distribution_hypothesis","bearish","dow_declining_structure","wyckoff_redistribution_hypothesis")]:
            for spring in self.out.execute("SELECT * FROM school_interpretation WHERE definition_id=? ORDER BY availability_time",(spring_def,)).fetchall():
                sign=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time>? ORDER BY availability_time LIMIT 1",(sign_def,spring["symbol"],spring["timeframe"],spring["availability_time"])).fetchone()
                if not sign: continue
                hid=self._write_hypothesis(hyp_def,symbol=spring["symbol"],timeframe=spring["timeframe"],direction=direction,event_time=int(spring["event_time"]),confirmation_time=int(sign["confirmation_time"]),availability_time=max_time(spring["availability_time"],sign["availability_time"]),upstream_refs=[self._ref("group8","school_interpretation",spring["interpretation_id"],spring["availability_time"]),self._ref("group8","school_interpretation",sign["interpretation_id"],sign["availability_time"])]); prior=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time<? ORDER BY availability_time DESC LIMIT 1",(prior_def,spring["symbol"],spring["timeframe"],spring["availability_time"])).fetchone()
                if prior: self._write_hypothesis(rehyp,symbol=spring["symbol"],timeframe=spring["timeframe"],direction=direction,event_time=int(spring["event_time"]),confirmation_time=int(sign["confirmation_time"]),availability_time=max_time(max_time(spring["availability_time"],sign["availability_time"]),prior["availability_time"]),upstream_refs=[self._ref("group8","narrative_hypothesis",hid,max_time(spring["availability_time"],sign["availability_time"])),self._ref("group8","school_interpretation",prior["interpretation_id"],prior["availability_time"])])
        self.out.commit()

    def process_ict(self) -> None:
        from group8_postprocess_v0_8_0 import first_bounded_range_invalidator
        symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"
        valid_leg_ids={str(r["leg_id"]):dict(r) for r in self._validated_legs()}
        for ev in self.input.execute("SELECT * FROM group6__group6_evidence WHERE lower(source_group) IN ('group5','5') ORDER BY availability_time,evidence_id"):
            if str(ev["subject_id"]) not in valid_leg_ids: continue
            leg=valid_leg_ids[str(ev["subject_id"])]; liq=self.input.execute("SELECT * FROM group5__liquidity_events WHERE event_id=?",(ev["source_id"],)).fetchone()
            if not liq: continue
            avail=max_time(ev["availability_time"],leg["validation_availability"],liq["resolved_time"] or liq["candidate_time"]); self._write_interpretation("ict_liquidity_sweep_displacement",symbol=default_symbol,timeframe=leg["timeframe"],direction=normalize_direction(leg["direction"]),event_time=int(leg["end_time"]),confirmation_time=int(leg["validation_confirmation_time"]),availability_time=avail,upstream_refs=[self._ref("group6","displacement_legs",leg["leg_id"],leg["availability_time"],event_time=leg["end_time"],timeframe=leg["timeframe"]),self._ref("group6","group6_evidence",ev["evidence_id"],ev["availability_time"],timeframe=ev["source_timeframe"]),self._ref("group5","liquidity_events",liq["event_id"],liq["resolved_time"] or liq["candidate_time"],event_time=liq["candidate_time"],timeframe=liq["timeframe"])])
        allowed=self._binding_values("group3.mss_or_bos_event_types")
        for fvg in self.input.execute("SELECT * FROM group6__fvg_events WHERE associated_group3_event_id IS NOT NULL ORDER BY availability_time,fvg_id"):
            ev=self.input.execute("SELECT * FROM group3__break_events WHERE event_id=?",(fvg["associated_group3_event_id"],)).fetchone()
            if not ev or str(ev["event_type"]) not in allowed or ev["resolved_time"] is None: continue
            self._write_interpretation("ict_mss_fvg_delivery",symbol=ev["symbol"] or default_symbol,timeframe=fvg["timeframe"],direction=normalize_direction(fvg["direction"]),event_time=int(fvg["creation_time"]),confirmation_time=max_time(fvg["confirmation_time"],ev["resolved_time"]),availability_time=max_time(fvg["availability_time"],ev["resolved_time"]),upstream_refs=[self._ref("group6","fvg_events",fvg["fvg_id"],fvg["availability_time"],event_time=fvg["creation_time"],timeframe=fvg["timeframe"]),self._ref("group3","break_events",ev["event_id"],ev["resolved_time"],event_time=ev["candidate_time"],timeframe=ev["timeframe"])])
        for rg in self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchall():
            midpoint=(float(rg["lower"])+float(rg["upper"]))/2; src=self._bar_by_id(rg["source_bar_id"])
            if not src:continue
            invalidator=first_bounded_range_invalidator(self,rg)
            invalidation_availability=int(invalidator["availability_time"]) if invalidator is not None else None
            key,idx=self.bar_pos[src.id]
            for bar in self.bars_by_tf[key][idx:]:
                if bar.available_at<rg["availability_time"]:continue
                if invalidation_availability is not None and bar.available_at>=invalidation_availability:break
                loc="discount" if bar.close<midpoint else "premium" if bar.close>midpoint else "equilibrium"; self._write_interpretation("ict_premium_discount_context",symbol=bar.symbol,timeframe=bar.timeframe,direction="neutral",event_time=bar.close_time,confirmation_time=bar.close_time,availability_time=max_time(bar.available_at,rg["availability_time"]),upstream_refs=[self._ref("group8","price_action_pattern_candidate",rg["candidate_id"],rg["availability_time"]),self._ref("source","bars",bar.id,bar.available_at,event_time=bar.close_time,timeframe=bar.timeframe)],reasons=[loc],evidence_strength={"location":loc,"midpoint":midpoint,"close":bar.close})
        fvg_by_id={str(r["fvg_id"]):dict(r) for r in self.input.execute("SELECT * FROM group6__fvg_events")}
        for tr in self.input.execute("SELECT * FROM group6__fvg_state_transitions ORDER BY transition_time,transition_id"):
            obj=fvg_by_id.get(str(tr["fvg_id"]));
            if not obj or int(tr["transition_time"])<=int(obj["availability_time"]):continue
            et=str(tr["event_type"]).lower()
            if not any(k in et for k in ("touch","visit","fill","ce","traverse")): continue
            self._write_interpretation("ict_return_to_imbalance",symbol=default_symbol,timeframe=obj["timeframe"],direction=normalize_direction(obj["direction"]),event_time=int(tr["transition_time"]),confirmation_time=int(tr["transition_time"]),availability_time=max_time(obj["availability_time"],tr["transition_time"]),upstream_refs=[self._ref("group6","fvg_events",obj["fvg_id"],obj["availability_time"],event_time=obj["creation_time"],timeframe=obj["timeframe"]),self._ref("group6","fvg_state_transitions",tr["transition_id"],tr["transition_time"],event_time=tr["transition_time"],timeframe=obj["timeframe"])])
        for z in self.input.execute("SELECT * FROM group7__institutional_zones ORDER BY availability_time,zone_id"):
            for ev in self.input.execute("SELECT * FROM group7__zone_evidence WHERE zone_id=? ORDER BY availability_time,evidence_id",(z["zone_id"],)).fetchall():
                if str(ev["source_group"]).lower() not in {"group6","6"}: continue
                self._write_interpretation("ict_block_delivery_context",symbol=default_symbol,timeframe=z["timeframe"],direction=normalize_direction(z["direction"]),event_time=int(z["event_time"]),confirmation_time=int(z["confirmation_time"]),availability_time=max_time(z["availability_time"],ev["availability_time"]),upstream_refs=[self._ref("group7","institutional_zones",z["zone_id"],z["availability_time"],event_time=z["event_time"],timeframe=z["timeframe"],details={"definition_id":z["definition_id"]}),self._ref("group7","zone_evidence",ev["evidence_id"],ev["availability_time"],timeframe=z["timeframe"],details={"source_group":ev["source_group"],"source_id":ev["source_id"]})])
        pool_by={str(r["pool_id"]):dict(r) for r in self.input.execute("SELECT * FROM group5__liquidity_pools")}
        for dr in self.input.execute("SELECT * FROM group5__draw_states WHERE selected_pool_id IS NOT NULL ORDER BY close_time,draw_id"):
            pool=pool_by.get(str(dr["selected_pool_id"]));
            if not pool:continue
            st=self.input.execute("SELECT * FROM group3__structure_states WHERE timeframe=? AND close_time<=? ORDER BY close_time DESC,state_id DESC LIMIT 1",(dr["timeframe"],dr["close_time"])).fetchone()
            if not st:continue
            avail=max_time(dr["close_time"],pool["available_at"],st["close_time"]); self._write_interpretation("ict_draw_on_liquidity_context",symbol=pool["symbol"] or default_symbol,timeframe=dr["timeframe"],direction=normalize_direction(dr["draw_side"]),event_time=int(dr["close_time"]),confirmation_time=int(dr["close_time"]),availability_time=avail,upstream_refs=[self._ref("group5","draw_states",dr["draw_id"],dr["close_time"],event_time=dr["close_time"],timeframe=dr["timeframe"]),self._ref("group5","liquidity_pools",pool["pool_id"],pool["available_at"],event_time=pool["origin_time"],timeframe=pool["timeframe"]),self._ref("group3","structure_states",st["state_id"],st["close_time"],event_time=st["close_time"],timeframe=st["timeframe"])],reasons=["descriptive_target_location_only_no_future_reach_label"])
        self.out.commit()

    def process_cross_school_and_mtf(self) -> None:
        subjects=[]
        for table,idc in (("school_interpretation","interpretation_id"),("narrative_hypothesis","hypothesis_id")):
            for r in self.out.execute(f"SELECT {idc} id,school_id,symbol,timeframe,direction,event_time,availability_time,upstream_refs_json FROM {table}"): subjects.append({"type":table,**dict(r)})
        by_source:dict[tuple[str,str,str],list[dict[str,Any]]]=defaultdict(list)
        for s in subjects:
            for ref in json.loads(s["upstream_refs_json"]): by_source[(str(ref.get("source_group")),str(ref.get("source_type")),str(ref.get("source_id")))].append(s)
        for key,subs in by_source.items():
            schools={s["school_id"] for s in subs}
            if len(subs)<2 or len(schools)<2:continue
            ids=sorted(s["id"] for s in subs);avail=max(int(s["availability_time"]) for s in subs);payload={"source":key,"subject_ids":ids,"availability_time":avail,"relation_type":"same_immutable_upstream_evidence"};sid=deterministic_id("g8shared",payload);h=stable_hash(payload);row={"shared_evidence_id":sid,"source_group":key[0],"source_type":key[1],"source_id":key[2],"subject_ids_json":canonical_json(ids),"relation_type":"same_immutable_upstream_evidence","availability_time":avail,"details_json":canonical_json({"school_count":len(schools)}),"shared_evidence_hash":h};self._insert_immutable("shared_evidence","shared_evidence_id",sid,row,hash_column="shared_evidence_hash",expected_hash=h)
            dirs={s["direction"] for s in subs if s["direction"] not in ("neutral","unknown")}
            if "bullish" in dirs and "bearish" in dirs:
                for a in subs:
                    for b in subs:
                        if a["id"]>=b["id"] or a["school_id"]==b["school_id"] or a["direction"]==b["direction"]:continue
                        avail2=max_time(a["availability_time"],b["availability_time"]);payload2={"left":a["id"],"right":b["id"],"type":"opposing_descriptive_claim_same_evidence","availability":avail2};cid=deterministic_id("g8conf",payload2);ch=stable_hash(payload2);row2={"conflict_id":cid,"left_subject_type":a["type"],"left_subject_id":a["id"],"right_subject_type":b["type"],"right_subject_id":b["id"],"conflict_type":"opposing_descriptive_claim_same_evidence","event_time":max_time(a["event_time"],b["event_time"]),"availability_time":avail2,"details_json":canonical_json({"shared_source":key}),"conflict_hash":ch};self._insert_immutable("conflicting_evidence","conflict_id",cid,row2,hash_column="conflict_hash",expected_hash=ch)
        tf_seconds={r["timeframe"]:int(r["seconds"]) for r in self.input.execute("SELECT * FROM group2__timeframe_dictionary")}; ordered=[s for s in subjects if s["timeframe"] in tf_seconds]; by_symbol:dict[str,list[dict[str,Any]]]=defaultdict(list)
        for s in ordered:by_symbol[s["symbol"]].append(s)
        for symbol,subs in by_symbol.items():
            for i,a in enumerate(subs):
                for b in subs[i+1:]:
                    if a["timeframe"]==b["timeframe"]:continue
                    if abs(int(a["event_time"])-int(b["event_time"]))>max(tf_seconds[a["timeframe"]],tf_seconds[b["timeframe"]])*2:continue
                    rel="same-direction context" if a["direction"]==b["direction"] and a["direction"]!="neutral" else "opposing-direction context" if {a["direction"],b["direction"]}=={"bullish","bearish"} else "partial overlap"; payload={"a":a["id"],"b":b["id"],"relation":rel,"availability":max_time(a["availability_time"],b["availability_time"])};rid=deterministic_id("g8mtf",payload);h=stable_hash(payload);row={"relation_id":rid,"subject_type":a["type"],"subject_id":a["id"],"subject_timeframe":a["timeframe"],"object_type":b["type"],"object_id":b["id"],"object_timeframe":b["timeframe"],"relation_type":rel,"event_time":max_time(a["event_time"],b["event_time"]),"availability_time":payload["availability"],"overlap_ratio":None,"details_json":canonical_json({"timeframe_seconds":{a["timeframe"]:tf_seconds[a["timeframe"]],b["timeframe"]:tf_seconds[b["timeframe"]]}}),"relation_hash":h};self._insert_immutable("multi_timeframe_context_relation","relation_id",rid,row,hash_column="relation_hash",expected_hash=h)
        self.out.commit()

    def audit(self, require_all_definitions_producible: bool = False) -> dict[str, Any]:
        failures=[];qc=self.out.execute("PRAGMA quick_check").fetchone()[0];ic=self.out.execute("PRAGMA integrity_check").fetchone()[0];fk=self.out.execute("PRAGMA foreign_key_check").fetchall()
        if qc!="ok":failures.append(f"quick_check:{qc}")
        if ic!="ok":failures.append(f"integrity_check:{ic}")
        if fk:failures.append(f"foreign_key_errors:{len(fk)}")
        causal_queries={"price_action_pattern_candidate":"availability_time < confirmation_time OR confirmation_time < event_time","school_interpretation":"availability_time < confirmation_time OR confirmation_time < event_time","narrative_hypothesis":"availability_time < confirmation_time OR confirmation_time < event_time","invalidation_record":"availability_time < confirmation_time OR confirmation_time < event_time","hypothesis_lifecycle_event":"availability_time < event_time","multi_timeframe_context_relation":"availability_time < event_time"}
        for table,where in causal_queries.items():
            n=self.out.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
            if n:failures.append(f"causality:{table}:{n}")
        locked_context_violations=self.out.execute("""SELECT COUNT(*) FROM school_interpretation i JOIN invalidation_record inv ON inv.subject_type='price_action_pattern_candidate' AND inv.rule_id='pa_bounded_range_context.invalidation_rule' AND inv.subject_id=json_extract(i.upstream_refs_json,'$[0].source_id') WHERE i.definition_id='ict_premium_discount_context' AND i.availability_time>=inv.availability_time""").fetchone()[0]
        if locked_context_violations:failures.append(f"locked_context:ict_premium_discount_context:{locked_context_violations}")
        n=self.out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0]
        if n:failures.append(f"lifecycle_before_creation:{n}")
        for table,idc in (("price_action_pattern_candidate","candidate_id"),("school_interpretation","interpretation_id"),("narrative_hypothesis","hypothesis_id")):
            n=self.out.execute(f"SELECT COUNT(*)-COUNT(DISTINCT {idc}) FROM {table}").fetchone()[0]
            if n:failures.append(f"duplicate_ids:{table}:{n}")
        for table in ("price_action_pattern_candidate","school_interpretation","narrative_hypothesis"):
            allowed=set(self.def_registry["definitions"]);unknown={r[0] for r in self.out.execute(f"SELECT DISTINCT definition_id FROM {table}") if r[0] not in allowed}
            if unknown:failures.append(f"unknown_definition:{table}:{sorted(unknown)}")
        tokens=[]
        for r in self.out.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"):
            words=set(re.findall(r"[a-z_]+",(r[1] or "").lower()));hit=sorted(words & FORBIDDEN_OUTPUT_TOKENS)
            if hit:tokens.append((r[0],hit))
        if tokens:failures.append(f"prohibited_schema_tokens:{tokens}")
        for table,cols in [("price_action_pattern_candidate",["reasons_json","features_json"]),("school_interpretation",["reasons_json","evidence_strength_json"]),("narrative_hypothesis",["reasons_json","evidence_strength_json"])]:
            for col in cols:
                for rid,val in self.out.execute(f"SELECT rowid,{col} FROM {table}"):
                    hit=set(re.findall(r"[a-z_]+",str(val).lower()))&FORBIDDEN_OUTPUT_TOKENS
                    if hit:failures.append(f"prohibited_value:{table}:{rid}:{col}:{sorted(hit)}");break
        evaluators=set(self.evaluator_registry());missing_eval=sorted(set(self.def_registry["definitions"])-evaluators);extra_eval=sorted(evaluators-set(self.def_registry["definitions"]))
        if missing_eval:failures.append(f"missing_evaluators:{missing_eval}")
        if extra_eval:failures.append(f"unknown_evaluators:{extra_eval}")
        if require_all_definitions_producible:
            missing_rows=sorted(k for k,v in self.definition_coverage.items() if v==0)
            if missing_rows:failures.append(f"synthetic_fixture_missing_definition_rows:{missing_rows}")
        counts={t:self.out.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["price_action_pattern_candidate","price_action_pattern_state","school_interpretation","narrative_hypothesis","hypothesis_lifecycle_event","invalidation_record","group8_audit_evidence","processing_checkpoint","shared_evidence","conflicting_evidence","multi_timeframe_context_relation","evidence_chain"]};report={"format_version":1,"status":"PASS" if not failures else "FAIL","engine_version":ENGINE_VERSION,"schema_version":SCHEMA_VERSION,"config_id":CONFIG_ID,"year":self.year,"counts":counts,"definition_coverage":dict(sorted(self.definition_coverage.items())),"evaluator_count":len(evaluators),"failures":failures};report["report_hash"]=stable_hash(report);return report

    @staticmethod
    def evaluator_registry() -> Mapping[str, str]:
        return {"pa_candle_anatomy":"process_base_price_action","pa_inside_bar_edge":"process_base_price_action","pa_inside_bar_strict":"process_base_price_action","pa_outside_bar_edge":"process_base_price_action","pa_outside_bar_strict":"process_base_price_action","pa_body_engulfing":"process_base_price_action","pa_directional_body_engulfing":"process_base_price_action","pa_full_range_engulfing":"process_base_price_action","pa_doji_strict":"process_base_price_action","pa_doji_broad":"process_base_price_action","pa_pin_bar_like":"process_base_price_action","pa_rejection_close":"process_base_price_action","pa_bounded_range_context":"process_bounded_ranges","pa_breakout_exact":"process_breakouts","pa_breakout_point_buffer":"process_breakouts","pa_breakout_atr_buffer":"process_breakouts","pa_context_linked_rejection":"process_context_rejections","pa_failed_breakout":"process_failed_breakouts_and_retests","pa_retest":"process_failed_breakouts_and_retests","pa_structural_pullback":"process_structural_narratives","pa_continuation_after_pullback":"process_structural_narratives","pa_exhaustion_failed_breakout":"process_structural_narratives","dow_advancing_structure":"process_dow","dow_declining_structure":"process_dow","dow_indeterminate_structure":"process_dow","dow_bullish_transition":"process_dow","dow_bearish_transition":"process_dow","dow_protected_pullback":"process_structural_narratives","wyckoff_range_context":"process_wyckoff","wyckoff_spring_candidate":"process_wyckoff","wyckoff_upthrust_candidate":"process_wyckoff","wyckoff_sign_of_strength":"process_wyckoff","wyckoff_sign_of_weakness":"process_wyckoff","wyckoff_last_point_of_support":"process_wyckoff","wyckoff_last_point_of_supply":"process_wyckoff","wyckoff_accumulation_hypothesis":"process_wyckoff","wyckoff_distribution_hypothesis":"process_wyckoff","wyckoff_reaccumulation_hypothesis":"process_wyckoff","wyckoff_redistribution_hypothesis":"process_wyckoff","ict_liquidity_sweep_displacement":"process_ict","ict_mss_fvg_delivery":"process_ict","ict_premium_discount_context":"process_ict","ict_return_to_imbalance":"process_ict","ict_block_delivery_context":"process_ict","ict_draw_on_liquidity_context":"process_ict"}

    def run(self) -> dict[str, Any]:
        from group8_postprocess_v0_8_0 import checkpoint, finalize_postprocessing, persist_audit_evidence
        stages = [
            ("load_bars", self.load_bars),
            ("base_price_action", self.process_base_price_action),
            ("dow", self.process_dow),
            ("bounded_ranges", self.process_bounded_ranges),
            ("breakouts", self.process_breakouts),
            ("context_rejections", self.process_context_rejections),
            ("failed_breakouts_retests", self.process_failed_breakouts_and_retests),
            ("structural_narratives", self.process_structural_narratives),
            ("wyckoff", self.process_wyckoff),
            ("ict", self.process_ict),
            ("cross_school_mtf", self.process_cross_school_and_mtf),
        ]
        for stage_name, stage_fn in stages:
            stage_fn()
            checkpoint(self, stage_name)
        persistence_report = finalize_postprocessing(self)
        checkpoint(self, "lifecycle_persistence")
        report = self.audit(require_all_definitions_producible=False)
        persist_audit_evidence(self, report, persistence_report)
        checkpoint(self, "final_audit")
        report = self.audit(require_all_definitions_producible=False)
        self.out.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",("engine_audit_hash",report["report_hash"]))
        self.out.commit()
        return report


def main() -> int:
    p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--output-db",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--year",type=int,required=True);p.add_argument("--symbol");p.add_argument("--audit-output",type=Path);a=p.parse_args();engine=Group8Engine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=a.artifacts_root,year=a.year,symbol=a.symbol)
    try: report=engine.run()
    finally: engine.close()
    if a.audit_output: a.audit_output.parent.mkdir(parents=True,exist_ok=True);a.audit_output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True));return 0 if report["status"]=="PASS" else 1

if __name__=="__main__": raise SystemExit(main())
