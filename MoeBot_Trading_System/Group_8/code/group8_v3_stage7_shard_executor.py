#!/usr/bin/env python3
"""Group 8 V3 production Stage 7 ICT shard executor.

Physical/execution-layer change only. Frozen Group 8 definitions, IDs, hashes,
causal ordering, upstream identities, and Groups 1-7 semantics are unchanged.

Two frozen storage families are materialized:
- range_chain: ICT3.1 premium/discount descendants rooted at pa_bounded_range_context.
- school_core: all other ICT interpretations rooted at the first mandatory immutable
  upstream evidence identity.

Inputs are read-only. Writes are deterministic/idempotent, commits are bounded,
resume is external-checkpoint based, and completed raw SQLite shards may be
losslessly zstd-compressed and deleted only after a streamed SHA-256 round-trip
verification.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from group8_v3_stage6_range_shard_executor import (
    bucket_for_root,
    canonical_json,
    epoch_month,
    stable_hash,
)
from moebot_group8_engine_v0_8_0 import (
    Group8Engine,
    max_time,
    normalize_direction,
    sha256_file,
)

STAGE5_CHECKPOINT = "structural_narratives_fast"
STAGE7_CHECKPOINT = "ict_core"
RANGE_DEFINITIONS = ("ict_premium_discount_context",)
SCHOOL_DEFINITIONS = (
    "ict_liquidity_sweep_displacement",
    "ict_mss_fvg_delivery",
    "ict_return_to_imbalance",
    "ict_block_delivery_context",
    "ict_draw_on_liquidity_context",
)
STAGE7_DEFINITIONS = RANGE_DEFINITIONS + SCHOOL_DEFINITIONS
EXPECTED_STORAGE_CONTRACT = "d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a"
EXPECTED_DESIGN_FREEZE = "213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _logical_table_hash(
    con: sqlite3.Connection,
    table: str,
    id_col: str,
    hash_col: str,
    where: str = "",
    params: Iterable[Any] = (),
) -> str:
    h = hashlib.sha256()
    sql = f'SELECT "{id_col}","{hash_col}" FROM "{table}"'
    if where:
        sql += " WHERE " + where
    sql += f' ORDER BY "{id_col}"'
    for rid, rh in con.execute(sql, tuple(params)):
        h.update(str(rid).encode("utf-8"))
        h.update(b"\0")
        h.update(str(rh).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _qualified_root(source_group: str, source_type: str, source_id: Any) -> str:
    return f"{source_group}:{source_type}:{source_id}"


def _status_active(status: str | None) -> bool:
    s = (status or "").lower()
    return not any(x in s for x in ("invalid", "expired", "broken", "deleted", "inactive"))


def _first_after(times: list[int], availability: int) -> int | None:
    i = bisect.bisect_right(times, int(availability))
    return None if i >= len(times) else int(times[i])


@dataclass(frozen=True)
class Stage7ShardSpec:
    family: str
    year: int
    symbol: str
    timeframe: str
    root_month: str
    bucket_count: int
    bucket_index: int

    def validate(self) -> None:
        if self.family not in {"range_chain", "school_core"}:
            raise ValueError("Stage 7 family must be range_chain or school_core")
        y, m = self.root_month.split("-")
        if int(y) != int(self.year) or not 1 <= int(m) <= 12:
            raise ValueError("root_month must be YYYY-MM within shard year")
        if self.bucket_count <= 0 or self.bucket_count & (self.bucket_count - 1):
            raise ValueError("bucket_count must be a positive power of two")
        if not 0 <= self.bucket_index < self.bucket_count:
            raise ValueError("bucket_index outside bucket_count")

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "year": self.year,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "root_month": self.root_month,
            "bucket_count": self.bucket_count,
            "bucket_index": self.bucket_index,
        }


class _Stage7BaseEngine(Group8Engine):
    def __init__(
        self,
        *,
        stage5_db: Path,
        checkpoint_path: Path,
        shard_spec: Stage7ShardSpec,
        hard_guard_bytes: int,
        **kwargs: Any,
    ) -> None:
        self.stage5_db = stage5_db.resolve()
        self.checkpoint_path = checkpoint_path.resolve()
        self.shard_spec = shard_spec
        self.shard_spec.validate()
        self.hard_guard_bytes = int(hard_guard_bytes)
        super().__init__(**kwargs)
        self.base = sqlite3.connect(f"file:{self.stage5_db}?mode=ro&immutable=1", uri=True)
        self.base.row_factory = sqlite3.Row

        contract = json.loads((self.root / "SHARDED_STORAGE_CONTRACT.json").read_text())
        freeze = json.loads((self.root / "DESIGN_FREEZE_MANIFEST.json").read_text())
        if contract.get("storage_contract_hash") != EXPECTED_STORAGE_CONTRACT:
            raise RuntimeError("unexpected frozen storage contract")
        if freeze.get("design_freeze_hash") != EXPECTED_DESIGN_FREEZE:
            raise RuntimeError("unexpected frozen design freeze")
        rule = contract["partitioning"]["partition_root_rules"][self.shard_spec.family]
        expected = (
            "pa_bounded_range_context candidate_id; all range descendants inherit it"
            if self.shard_spec.family == "range_chain"
            else "first mandatory immutable upstream evidence identity under the frozen definition"
        )
        if rule != expected:
            raise RuntimeError(f"{self.shard_spec.family} partition-root rule drift")

        self.out.execute("PRAGMA journal_mode=DELETE")
        self.out.execute("PRAGMA synchronous=FULL")
        self.out.commit()

    def close(self, *, commit: bool = True) -> None:
        try:
            if commit:
                self.out.commit()
            else:
                self.out.rollback()
        finally:
            self.base.close()
            self.out.close()
            self.input.close()

    def verify_stage5_boundary(self) -> None:
        expected = {
            (str(r[0]), str(r[1]))
            for r in self.input.execute(
                "SELECT DISTINCT symbol,timeframe FROM source__bars WHERE symbol=? ORDER BY symbol,timeframe",
                (self.shard_spec.symbol,),
            )
        }
        got = {
            (str(r[0]), str(r[1]))
            for r in self.base.execute(
                "SELECT symbol,timeframe FROM processing_checkpoint WHERE stage=? AND status='PASS'",
                (STAGE5_CHECKPOINT,),
            )
        }
        if got != expected:
            raise RuntimeError(f"Stage 5 boundary mismatch: expected={sorted(expected)} got={sorted(got)}")
        if int(self.base.execute(
            "SELECT COUNT(*) FROM processing_checkpoint WHERE stage=? AND status='PASS'",
            (STAGE7_CHECKPOINT,),
        ).fetchone()[0]):
            raise RuntimeError("protected Stage 5 boundary contains ict_core PASS checkpoint")
        q = ",".join("?" for _ in STAGE7_DEFINITIONS)
        physical = int(self.base.execute(
            f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",
            STAGE7_DEFINITIONS,
        ).fetchone()[0])
        if physical:
            raise RuntimeError(f"protected Stage 5 boundary unexpectedly contains Stage 7 rows:{physical}")

    def _load_checkpoint(self, total_work: int) -> dict[str, Any] | None:
        if not self.checkpoint_path.exists():
            q = ",".join("?" for _ in STAGE7_DEFINITIONS)
            rows = int(self.out.execute(
                f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",
                STAGE7_DEFINITIONS,
            ).fetchone()[0])
            if rows:
                raise RuntimeError("Stage 7 shard has rows but no checkpoint; fail closed")
            return None
        cp = json.loads(self.checkpoint_path.read_text())
        if cp.get("spec") != self.shard_spec.identity:
            raise RuntimeError("checkpoint shard identity mismatch")
        if int(cp.get("total_work", -1)) != int(total_work):
            raise RuntimeError("checkpoint deterministic-work cardinality drift")
        return cp

    def _write_progress(
        self,
        *,
        committed_work: int,
        total_work: int,
        commit_count: int,
        emitted_interpretations: int,
        started: float,
        completed: bool,
    ) -> dict[str, Any]:
        elapsed = max(time.monotonic() - started, 1e-9)
        rate = committed_work / elapsed
        remaining = max(total_work - committed_work, 0)
        rec = {
            "schema": "moebot-group8-v3-stage7-checkpoint-v1",
            "status": "PASS" if completed else "RUNNING",
            "spec": self.shard_spec.identity,
            "committed_work": int(committed_work),
            "total_work": int(total_work),
            "progress_percent": 100.0 if total_work == 0 else round(100.0 * committed_work / total_work, 6),
            "elapsed_seconds": round(elapsed, 3),
            "work_per_second": round(rate, 6),
            "eta_seconds": None if rate <= 0 else round(remaining / rate, 3),
            "commit_count": int(commit_count),
            "emitted_interpretations": int(emitted_interpretations),
            "output_db_size_bytes": self.output_db.stat().st_size if self.output_db.exists() else 0,
            "completed": bool(completed),
            "updated_unix": int(time.time()),
        }
        rec["checkpoint_hash"] = stable_hash(rec)
        _atomic_json(self.checkpoint_path, rec)
        return rec

    def _guard_size(self) -> None:
        if self.output_db.exists() and self.output_db.stat().st_size > self.hard_guard_bytes:
            raise RuntimeError("Stage 7 shard exceeded frozen runtime hard guard")


class Stage7RangeChainEngine(_Stage7BaseEngine):
    def __init__(self, *, root_allowlist: set[str] | None = None, **kwargs: Any) -> None:
        self.root_allowlist = None if root_allowlist is None else {str(x) for x in root_allowlist}
        super().__init__(**kwargs)
        if self.shard_spec.family != "range_chain":
            raise ValueError("Stage7RangeChainEngine requires family=range_chain")

    def _load_invalidators(self) -> dict[str, list[int]]:
        by_zone: dict[str, list[int]] = defaultdict(list)
        for r in self.input.execute(
            "SELECT zone_id,transition_time,to_status FROM group4__zone_transitions "
            "ORDER BY zone_id,transition_time,transition_id"
        ):
            if not _status_active(str(r["to_status"])):
                by_zone[str(r["zone_id"])].append(int(r["transition_time"]))
        for r in self.input.execute(
            "SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions "
            "ORDER BY zone_id,interaction_time,interaction_id"
        ):
            if not _status_active(str(r["status_after"])):
                by_zone[str(r["zone_id"])].append(int(r["interaction_time"]))
        for times in by_zone.values():
            times.sort()
        return by_zone

    @staticmethod
    def _cutoff(rg: dict[str, Any], invalidators: dict[str, list[int]]) -> int | None:
        features = json.loads(str(rg["features_json"] or "{}"))
        found: list[int] = []
        for zid in (features.get("lower_zone_id"), features.get("upper_zone_id")):
            if not zid:
                continue
            t = _first_after(invalidators.get(str(zid), []), int(rg["availability_time"]))
            if t is not None:
                found.append(t)
        return min(found) if found else None

    def _ranges(self) -> list[dict[str, Any]]:
        spec = self.shard_spec
        out: list[dict[str, Any]] = []
        for r in self.base.execute(
            """SELECT candidate_id,symbol,timeframe,source_bar_id,event_time,
                      confirmation_time,availability_time,lower,upper,features_json
               FROM price_action_pattern_candidate
               WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?
               ORDER BY event_time,availability_time,candidate_id""",
            (spec.symbol, spec.timeframe),
        ):
            rid = str(r["candidate_id"])
            if self.root_allowlist is not None and rid not in self.root_allowlist:
                continue
            if epoch_month(int(r["event_time"])) != spec.root_month:
                continue
            if bucket_for_root(rid, spec.bucket_count) != spec.bucket_index:
                continue
            out.append(dict(r))
        return out

    def _emit_root(self, rg: dict[str, Any], invalidators: dict[str, list[int]]) -> int:
        src = self._bar_by_id(rg["source_bar_id"])
        if not src:
            raise RuntimeError(f"bounded range source bar missing:{rg['candidate_id']}")
        key, idx = self.bar_pos[src.id]
        cutoff = self._cutoff(rg, invalidators)
        midpoint = (float(rg["lower"]) + float(rg["upper"])) / 2.0
        emitted = 0
        for bar in self.bars_by_tf[key][idx:]:
            if int(bar.available_at) < int(rg["availability_time"]):
                continue
            if cutoff is not None and int(bar.available_at) >= int(cutoff):
                break
            loc = "discount" if bar.close < midpoint else "premium" if bar.close > midpoint else "equilibrium"
            self._write_interpretation(
                "ict_premium_discount_context",
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                direction="neutral",
                event_time=bar.close_time,
                confirmation_time=bar.close_time,
                availability_time=max_time(bar.available_at, rg["availability_time"]),
                upstream_refs=[
                    self._ref(
                        "group8",
                        "price_action_pattern_candidate",
                        rg["candidate_id"],
                        rg["availability_time"],
                    ),
                    self._ref(
                        "source",
                        "bars",
                        bar.id,
                        bar.available_at,
                        event_time=bar.close_time,
                        timeframe=bar.timeframe,
                    ),
                ],
                reasons=[loc],
                evidence_strength={"location": loc, "midpoint": midpoint, "close": bar.close},
            )
            emitted += 1
        return emitted

    def run_resumable(
        self,
        *,
        chunk_interpretations: int,
        max_chunks: int | None = None,
    ) -> dict[str, Any]:
        if chunk_interpretations <= 0:
            raise ValueError("chunk_interpretations must be positive")
        self.verify_stage5_boundary()
        self.load_bars()
        key = (self.shard_spec.symbol, self.shard_spec.timeframe)
        bars = self.bars_by_tf.get(key)
        if not bars:
            raise RuntimeError(f"no bars for Stage 7 shard:{key}")
        self.bars_by_tf = {key: bars}
        self.bar_pos = {bar.id: (key, i) for i, bar in enumerate(bars)}
        ranges = self._ranges()
        invalidators = self._load_invalidators()
        total = len(ranges)
        cp = self._load_checkpoint(total)
        already = int(cp.get("committed_work", 0)) if cp else 0
        if cp and cp.get("completed") is True:
            return cp
        if already > total:
            raise RuntimeError("checkpoint exceeds deterministic root cardinality")

        started = time.monotonic()
        commit_count = int(cp.get("commit_count", 0)) if cp else 0
        emitted = int(cp.get("emitted_interpretations", 0)) if cp else 0
        pending_i = 0
        chunks = 0

        for ordinal, rg in enumerate(ranges):
            if ordinal < already:
                continue
            n = self._emit_root(rg, invalidators)
            emitted += n
            pending_i += n
            completed_roots = ordinal + 1
            if pending_i >= chunk_interpretations or completed_roots == total:
                self.out.commit()
                commit_count += 1
                chunks += 1
                self._guard_size()
                done = completed_roots == total
                cp = self._write_progress(
                    committed_work=completed_roots,
                    total_work=total,
                    commit_count=commit_count,
                    emitted_interpretations=emitted,
                    started=started,
                    completed=done,
                )
                pending_i = 0
                if max_chunks is not None and chunks >= max_chunks and not done:
                    return cp

        if total == 0:
            self.out.commit()
            return self._write_progress(
                committed_work=0,
                total_work=0,
                commit_count=commit_count,
                emitted_interpretations=0,
                started=started,
                completed=True,
            )
        return json.loads(self.checkpoint_path.read_text())


class Stage7SchoolCoreEngine(_Stage7BaseEngine):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.shard_spec.family != "school_core":
            raise ValueError("Stage7SchoolCoreEngine requires family=school_core")
        self.allowed_mss_bos = self._binding_values("group3.mss_or_bos_event_types")
        self._valid_leg_map: dict[str, dict[str, Any]] | None = None
        self._liq_map: dict[str, dict[str, Any]] | None = None
        self._break_map: dict[str, dict[str, Any]] | None = None
        self._fvg_map: dict[str, dict[str, Any]] | None = None
        self._pool_map: dict[str, dict[str, Any]] | None = None
        self._states: dict[str, list[dict[str, Any]]] | None = None
        self._state_times: dict[str, list[int]] | None = None

    def _belongs(self, root_key: str, timeframe: str, root_time: int) -> bool:
        s = self.shard_spec
        return (
            str(timeframe) == s.timeframe
            and epoch_month(int(root_time)) == s.root_month
            and bucket_for_root(root_key, s.bucket_count) == s.bucket_index
        )

    def _load_maps(self) -> None:
        if self._valid_leg_map is not None:
            return
        self._valid_leg_map = {str(r["leg_id"]): dict(r) for r in self._validated_legs()}
        self._liq_map = {
            str(r["event_id"]): dict(r)
            for r in self.input.execute("SELECT * FROM group5__liquidity_events")
        }
        self._break_map = {
            str(r["event_id"]): dict(r)
            for r in self.input.execute("SELECT * FROM group3__break_events")
        }
        self._fvg_map = {
            str(r["fvg_id"]): dict(r)
            for r in self.input.execute("SELECT * FROM group6__fvg_events")
        }
        self._pool_map = {
            str(r["pool_id"]): dict(r)
            for r in self.input.execute("SELECT * FROM group5__liquidity_pools")
        }
        states: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.input.execute(
            "SELECT * FROM group3__structure_states ORDER BY timeframe,close_time,state_id"
        ):
            states[str(r["timeframe"])].append(dict(r))
        self._states = dict(states)
        self._state_times = {
            tf: [int(r["close_time"]) for r in rows] for tf, rows in self._states.items()
        }

    def _latest_structure(self, timeframe: str, close_time: int) -> dict[str, Any] | None:
        self._load_maps()
        assert self._states is not None and self._state_times is not None
        rows = self._states.get(str(timeframe), [])
        times = self._state_times.get(str(timeframe), [])
        i = bisect.bisect_right(times, int(close_time)) - 1
        return None if i < 0 else rows[i]

    def _iter_actions(self) -> Iterator[tuple[str, dict[str, Any]]]:
        self._load_maps()
        assert self._valid_leg_map is not None
        assert self._liq_map is not None
        assert self._break_map is not None
        assert self._fvg_map is not None
        assert self._pool_map is not None
        default_symbol = self.shard_spec.symbol

        # ICT1.1: exact current frozen process_ict relation, N+1 lookups replaced by maps.
        for ev in self.input.execute(
            "SELECT * FROM group6__group6_evidence "
            "WHERE lower(source_group) IN ('group5','5') ORDER BY availability_time,evidence_id"
        ):
            leg = self._valid_leg_map.get(str(ev["subject_id"]))
            if not leg:
                continue
            liq = self._liq_map.get(str(ev["source_id"]))
            if not liq:
                continue
            root = _qualified_root("group6", "displacement_legs", leg["leg_id"])
            if not self._belongs(root, str(leg["timeframe"]), int(leg["end_time"])):
                continue
            avail = max_time(
                ev["availability_time"],
                leg["validation_availability"],
                liq["resolved_time"] or liq["candidate_time"],
            )
            yield "ict_liquidity_sweep_displacement", {
                "symbol": default_symbol,
                "timeframe": leg["timeframe"],
                "direction": normalize_direction(leg["direction"]),
                "event_time": int(leg["end_time"]),
                "confirmation_time": int(leg["validation_confirmation_time"]),
                "availability_time": avail,
                "upstream_refs": [
                    self._ref(
                        "group6", "displacement_legs", leg["leg_id"], leg["availability_time"],
                        event_time=leg["end_time"], timeframe=leg["timeframe"],
                    ),
                    self._ref(
                        "group6", "group6_evidence", ev["evidence_id"], ev["availability_time"],
                        timeframe=ev["source_timeframe"],
                    ),
                    self._ref(
                        "group5", "liquidity_events", liq["event_id"],
                        liq["resolved_time"] or liq["candidate_time"],
                        event_time=liq["candidate_time"], timeframe=liq["timeframe"],
                    ),
                ],
            }

        # ICT2.1.
        for fvg in self.input.execute(
            "SELECT * FROM group6__fvg_events "
            "WHERE associated_group3_event_id IS NOT NULL ORDER BY availability_time,fvg_id"
        ):
            ev = self._break_map.get(str(fvg["associated_group3_event_id"]))
            if not ev or str(ev["event_type"]) not in self.allowed_mss_bos or ev["resolved_time"] is None:
                continue
            root = _qualified_root("group6", "fvg_events", fvg["fvg_id"])
            if not self._belongs(root, str(fvg["timeframe"]), int(fvg["creation_time"])):
                continue
            yield "ict_mss_fvg_delivery", {
                "symbol": ev["symbol"] or default_symbol,
                "timeframe": fvg["timeframe"],
                "direction": normalize_direction(fvg["direction"]),
                "event_time": int(fvg["creation_time"]),
                "confirmation_time": max_time(fvg["confirmation_time"], ev["resolved_time"]),
                "availability_time": max_time(fvg["availability_time"], ev["resolved_time"]),
                "upstream_refs": [
                    self._ref(
                        "group6", "fvg_events", fvg["fvg_id"], fvg["availability_time"],
                        event_time=fvg["creation_time"], timeframe=fvg["timeframe"],
                    ),
                    self._ref(
                        "group3", "break_events", ev["event_id"], ev["resolved_time"],
                        event_time=ev["candidate_time"], timeframe=ev["timeframe"],
                    ),
                ],
            }

        # ICT4.1: only exact causal lifecycle transitions exposed by the frozen adapter.
        for tr in self.input.execute(
            "SELECT * FROM group6__fvg_state_transitions ORDER BY transition_time,transition_id"
        ):
            obj = self._fvg_map.get(str(tr["fvg_id"]))
            if not obj or int(tr["transition_time"]) <= int(obj["availability_time"]):
                continue
            et = str(tr["event_type"]).lower()
            if not any(k in et for k in ("touch", "visit", "fill", "ce", "traverse")):
                continue
            root = _qualified_root("group6", "fvg_events", obj["fvg_id"])
            if not self._belongs(root, str(obj["timeframe"]), int(obj["creation_time"])):
                continue
            yield "ict_return_to_imbalance", {
                "symbol": default_symbol,
                "timeframe": obj["timeframe"],
                "direction": normalize_direction(obj["direction"]),
                "event_time": int(tr["transition_time"]),
                "confirmation_time": int(tr["transition_time"]),
                "availability_time": max_time(obj["availability_time"], tr["transition_time"]),
                "upstream_refs": [
                    self._ref(
                        "group6", "fvg_events", obj["fvg_id"], obj["availability_time"],
                        event_time=obj["creation_time"], timeframe=obj["timeframe"],
                    ),
                    self._ref(
                        "group6", "fvg_state_transitions", tr["transition_id"], tr["transition_time"],
                        event_time=tr["transition_time"], timeframe=obj["timeframe"],
                    ),
                ],
            }

        # ICT5.1: one row per exact qualifying Group7 zone/evidence relation.
        for r in self.input.execute(
            """SELECT z.*,e.evidence_id,e.evidence_type,e.source_group,e.source_id,
                      e.relation_type,e.availability_time AS evidence_availability
               FROM group7__institutional_zones z
               JOIN group7__zone_evidence e ON e.zone_id=z.zone_id
               WHERE lower(e.source_group) IN ('group6','6')
               ORDER BY z.availability_time,z.zone_id,e.availability_time,e.evidence_id"""
        ):
            root = _qualified_root("group7", "institutional_zones", r["zone_id"])
            if not self._belongs(root, str(r["timeframe"]), int(r["event_time"])):
                continue
            yield "ict_block_delivery_context", {
                "symbol": default_symbol,
                "timeframe": r["timeframe"],
                "direction": normalize_direction(r["direction"]),
                "event_time": int(r["event_time"]),
                "confirmation_time": int(r["confirmation_time"]),
                "availability_time": max_time(r["availability_time"], r["evidence_availability"]),
                "upstream_refs": [
                    self._ref(
                        "group7", "institutional_zones", r["zone_id"], r["availability_time"],
                        event_time=r["event_time"], timeframe=r["timeframe"],
                        details={"definition_id": r["definition_id"]},
                    ),
                    self._ref(
                        "group7", "zone_evidence", r["evidence_id"], r["evidence_availability"],
                        timeframe=r["timeframe"],
                        details={"source_group": r["source_group"], "source_id": r["source_id"]},
                    ),
                ],
            }

        # ICT6.1: latest causally available Group3 structure state by timeframe.
        for dr in self.input.execute(
            "SELECT * FROM group5__draw_states "
            "WHERE selected_pool_id IS NOT NULL ORDER BY close_time,draw_id"
        ):
            pool = self._pool_map.get(str(dr["selected_pool_id"]))
            if not pool:
                continue
            st = self._latest_structure(str(dr["timeframe"]), int(dr["close_time"]))
            if not st:
                continue
            root = _qualified_root("group5", "draw_states", dr["draw_id"])
            if not self._belongs(root, str(dr["timeframe"]), int(dr["close_time"])):
                continue
            avail = max_time(dr["close_time"], pool["available_at"], st["close_time"])
            yield "ict_draw_on_liquidity_context", {
                "symbol": pool["symbol"] or default_symbol,
                "timeframe": dr["timeframe"],
                "direction": normalize_direction(dr["draw_side"]),
                "event_time": int(dr["close_time"]),
                "confirmation_time": int(dr["close_time"]),
                "availability_time": avail,
                "upstream_refs": [
                    self._ref(
                        "group5", "draw_states", dr["draw_id"], dr["close_time"],
                        event_time=dr["close_time"], timeframe=dr["timeframe"],
                    ),
                    self._ref(
                        "group5", "liquidity_pools", pool["pool_id"], pool["available_at"],
                        event_time=pool["origin_time"], timeframe=pool["timeframe"],
                    ),
                    self._ref(
                        "group3", "structure_states", st["state_id"], st["close_time"],
                        event_time=st["close_time"], timeframe=st["timeframe"],
                    ),
                ],
                "reasons": ["descriptive_target_location_only_no_future_reach_label"],
            }

    def run_resumable(
        self,
        *,
        chunk_interpretations: int,
        max_chunks: int | None = None,
        expected_total_work: int | None = None,
    ) -> dict[str, Any]:
        if chunk_interpretations <= 0:
            raise ValueError("chunk_interpretations must be positive")
        self.verify_stage5_boundary()
        total = (
            sum(1 for _ in self._iter_actions())
            if expected_total_work is None
            else int(expected_total_work)
        )
        if total < 0:
            raise ValueError("expected_total_work must be non-negative")
        cp = self._load_checkpoint(total)
        already = int(cp.get("committed_work", 0)) if cp else 0
        if cp and cp.get("completed") is True:
            return cp
        if already > total:
            raise RuntimeError("checkpoint exceeds deterministic interpretation cardinality")

        started = time.monotonic()
        commit_count = int(cp.get("commit_count", 0)) if cp else 0
        emitted = int(cp.get("emitted_interpretations", 0)) if cp else 0
        pending = 0
        chunks = 0
        ordinal = 0

        for definition, kwargs in self._iter_actions():
            if ordinal < already:
                ordinal += 1
                continue
            if ordinal >= total:
                raise RuntimeError(
                    f"Stage 7 school_core plan cardinality understated: more than {total} actions"
                )
            self._write_interpretation(definition, **kwargs)
            ordinal += 1
            emitted += 1
            pending += 1
            if pending >= chunk_interpretations or ordinal == total:
                self.out.commit()
                commit_count += 1
                chunks += 1
                self._guard_size()
                done = ordinal == total
                cp = self._write_progress(
                    committed_work=ordinal,
                    total_work=total,
                    commit_count=commit_count,
                    emitted_interpretations=emitted,
                    started=started,
                    completed=done,
                )
                pending = 0
                if max_chunks is not None and chunks >= max_chunks and not done:
                    return cp

        if ordinal != total:
            raise RuntimeError(
                f"Stage 7 school_core plan cardinality mismatch: observed={ordinal} expected={total}"
            )
        if total == 0:
            self.out.commit()
            return self._write_progress(
                committed_work=0,
                total_work=0,
                commit_count=commit_count,
                emitted_interpretations=0,
                started=started,
                completed=True,
            )
        return json.loads(self.checkpoint_path.read_text())


def build_manifest(
    *,
    output_db: Path,
    artifacts_root: Path,
    spec: Stage7ShardSpec,
    checkpoint: dict[str, Any],
    stage5_sha256: str,
    stage6_release_hash: str,
    stage6_union_report_hash: str,
) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{output_db.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        qc = con.execute("PRAGMA quick_check").fetchone()[0]
        ic = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if qc != "ok" or ic != "ok" or fk:
            raise RuntimeError(f"Stage 7 shard validation failed qc={qc} ic={ic} fk={len(fk)}")
        defs = RANGE_DEFINITIONS if spec.family == "range_chain" else SCHOOL_DEFINITIONS
        q = ",".join("?" for _ in defs)
        counts = {
            "school_interpretation": int(con.execute(
                f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})", defs
            ).fetchone()[0]),
            "evidence_chain": int(con.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0]),
        }
        by_def = {
            str(r[0]): int(r[1])
            for r in con.execute(
                f"SELECT definition_id,COUNT(*) FROM school_interpretation "
                f"WHERE definition_id IN ({q}) GROUP BY definition_id ORDER BY definition_id",
                defs,
            )
        }
        times = con.execute(
            f"SELECT MIN(event_time),MAX(event_time),MIN(availability_time),MAX(availability_time) "
            f"FROM school_interpretation WHERE definition_id IN ({q})",
            defs,
        ).fetchone()
        logical = {
            "school_interpretation": _logical_table_hash(
                con, "school_interpretation", "interpretation_id", "interpretation_hash",
                f"definition_id IN ({q})", defs,
            ),
            "evidence_chain": _logical_table_hash(
                con, "evidence_chain", "evidence_chain_id", "evidence_hash",
            ),
        }
    finally:
        con.close()

    freeze = json.loads((artifacts_root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    contract = json.loads((artifacts_root / "SHARDED_STORAGE_CONTRACT.json").read_text())
    payload = {
        "family": spec.family,
        "year": spec.year,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "causal_root_window": spec.root_month,
        "partition_root_rule": contract["partitioning"]["partition_root_rules"][spec.family],
        "bucket_index": spec.bucket_index,
        "bucket_count": spec.bucket_count,
    }
    rec = {
        "format_version": 1,
        "status": "PASS",
        "stage": 7,
        "stage_name": "ict_core",
        "shard_id": "g8shard_" + stable_hash(payload),
        **payload,
        "file_size_bytes": output_db.stat().st_size,
        "sha256": sha256_file(output_db),
        "compressed_sha256": None,
        "compressed_size_bytes": None,
        "compression_level": None,
        "compression_roundtrip_sha256": None,
        "raw_retained": True,
        "table_row_counts": counts,
        "table_logical_sha256": logical,
        "definition_coverage": by_def,
        "min_event_time": times[0],
        "max_event_time": times[1],
        "min_availability_time": times[2],
        "max_availability_time": times[3],
        "upstream_lineage_id": freeze["logical_dependency_lineage_id"],
        "engine_sha256": sha256_file(artifacts_root / "code/moebot_group8_engine_v0_8_0.py"),
        "physical_executor_sha256": sha256_file(Path(__file__).resolve()),
        "design_freeze_hash": freeze["design_freeze_hash"],
        "storage_contract_hash": contract["storage_contract_hash"],
        "checkpoint_hash": checkpoint["checkpoint_hash"],
        "stage5_database_sha256": stage5_sha256,
        "stage6_release_hash": stage6_release_hash,
        "stage6_union_report_hash": stage6_union_report_hash,
        "oos_2024_accessed": spec.year == 2024,
    }
    rec["manifest_hash"] = stable_hash(rec)
    return rec


def run_shard(
    *,
    staging_db: Path,
    stage5_db: Path,
    output_db: Path,
    checkpoint_path: Path,
    manifest_path: Path,
    artifacts_root: Path,
    spec: Stage7ShardSpec,
    chunk_interpretations: int,
    hard_guard_bytes: int,
    stage6_release_hash: str,
    stage6_union_report_hash: str,
    max_chunks: int | None = None,
    root_allowlist: set[str] | None = None,
    expected_total_work: int | None = None,
) -> dict[str, Any]:
    if spec.year == 2024:
        raise RuntimeError("2024 OOS remains forbidden")
    cls = Stage7RangeChainEngine if spec.family == "range_chain" else Stage7SchoolCoreEngine
    kwargs: dict[str, Any] = {}
    if spec.family == "range_chain":
        kwargs["root_allowlist"] = root_allowlist
    engine = cls(
        staging_db=staging_db,
        output_db=output_db,
        artifacts_root=artifacts_root,
        year=spec.year,
        symbol=spec.symbol,
        stage5_db=stage5_db,
        checkpoint_path=checkpoint_path,
        shard_spec=spec,
        hard_guard_bytes=hard_guard_bytes,
        **kwargs,
    )
    try:
        run_kwargs: dict[str, Any] = {
            "chunk_interpretations": chunk_interpretations,
            "max_chunks": max_chunks,
        }
        if spec.family == "school_core":
            run_kwargs["expected_total_work"] = expected_total_work
        cp = engine.run_resumable(**run_kwargs)
        if cp.get("completed") is not True:
            return {"status": "RUNNING", "checkpoint": cp}
    except Exception:
        engine.close(commit=False)
        raise
    else:
        engine.close(commit=True)

    manifest = build_manifest(
        output_db=output_db,
        artifacts_root=artifacts_root,
        spec=spec,
        checkpoint=cp,
        stage5_sha256=sha256_file(stage5_db),
        stage6_release_hash=stage6_release_hash,
        stage6_union_report_hash=stage6_union_report_hash,
    )
    _atomic_json(manifest_path, manifest)
    return manifest


def _stream_decompressed_sha256(zstd_exe: Path, archive: Path) -> str:
    h = hashlib.sha256()
    p = subprocess.Popen(
        [str(zstd_exe), "-d", "-c", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert p.stdout is not None
    for chunk in iter(lambda: p.stdout.read(1024 * 1024), b""):
        h.update(chunk)
    stderr = b"" if p.stderr is None else p.stderr.read()
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"zstd streamed decompression failed rc={rc}: {stderr.decode(errors='replace')}")
    return h.hexdigest()


def compress_verified_shard(
    *,
    database: Path,
    manifest_path: Path,
    archive: Path,
    zstd_exe: Path,
    level: int = 6,
    remove_raw: bool = True,
) -> dict[str, Any]:
    if not database.is_file() or not manifest_path.is_file():
        raise RuntimeError("raw shard and manifest are required for compression")
    m = json.loads(manifest_path.read_text())
    saved = str(m.pop("manifest_hash"))
    if stable_hash(m) != saved:
        raise RuntimeError("manifest self-hash mismatch before compression")
    m["manifest_hash"] = saved
    raw_sha = sha256_file(database)
    if raw_sha != m.get("sha256") or database.stat().st_size != int(m.get("file_size_bytes", -1)):
        raise RuntimeError("raw shard identity mismatch before compression")

    archive.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(zstd_exe), f"-{int(level)}", "-f", str(database), "-o", str(archive)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [str(zstd_exe), "-t", str(archive)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    roundtrip = _stream_decompressed_sha256(zstd_exe, archive)
    if roundtrip != raw_sha:
        raise RuntimeError(f"zstd round-trip SHA mismatch:{roundtrip}!={raw_sha}")

    m["compressed_sha256"] = sha256_file(archive)
    m["compressed_size_bytes"] = archive.stat().st_size
    m["compression_level"] = int(level)
    m["compression_roundtrip_sha256"] = roundtrip
    if remove_raw:
        database.unlink()
        m["raw_retained"] = False
    else:
        m["raw_retained"] = True
    m.pop("manifest_hash", None)
    m["manifest_hash"] = stable_hash(m)
    _atomic_json(manifest_path, m)
    return m


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--family", choices=("range_chain", "school_core"), required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--root-month", required=True)
    p.add_argument("--bucket-count", type=int, required=True)
    p.add_argument("--bucket-index", type=int, required=True)
    p.add_argument("--chunk-interpretations", type=int, default=5000)
    p.add_argument("--hard-guard-bytes", type=int, default=2_500_000_000)
    p.add_argument("--stage6-release-hash", required=True)
    p.add_argument("--stage6-union-report-hash", required=True)
    p.add_argument("--expected-total-work", type=int)
    a = p.parse_args()
    spec = Stage7ShardSpec(
        a.family, a.year, a.symbol, a.timeframe, a.root_month, a.bucket_count, a.bucket_index
    )
    r = run_shard(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        output_db=a.output_db.resolve(),
        checkpoint_path=a.checkpoint.resolve(),
        manifest_path=a.manifest.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        spec=spec,
        chunk_interpretations=a.chunk_interpretations,
        hard_guard_bytes=a.hard_guard_bytes,
        stage6_release_hash=a.stage6_release_hash,
        stage6_union_report_hash=a.stage6_union_report_hash,
        expected_total_work=a.expected_total_work,
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
