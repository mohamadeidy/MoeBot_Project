#!/usr/bin/env python3
"""Group 8 V3 production Stage 6 executor.

Physical/execution-layer change only. The frozen Group 8 semantics, definitions,
IDs, hashes, causal ordering, evidence payloads, and upstream Groups 1-7 remain
unchanged.

Stage 5 is opened read-only and is never modified. Stage 6 (Wyckoff core) is
materialized into deterministic range_chain shards defined by the already-frozen
SHARDED_STORAGE_CONTRACT.json. Each shard commits in bounded chunks and records an
external atomic checkpoint. Resume may replay at most the last committed chunk;
all writes are deterministic/idempotent through the frozen engine writers.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from moebot_group8_engine_v0_8_0 import Group8Engine, Group8InvariantError, max_time, sha256_file

STAGE5_CHECKPOINT = "structural_narratives_fast"
STAGE6_CHECKPOINT = "wyckoff_core"
STAGE6_DEFINITIONS = (
    "wyckoff_range_context",
    "wyckoff_spring_candidate",
    "wyckoff_upthrust_candidate",
)
EXPECTED_STORAGE_CONTRACT = "d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a"
EXPECTED_DESIGN_FREEZE = "213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def epoch_month(epoch: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m")


def bucket_for_root(root_id: str, bucket_count: int) -> int:
    if bucket_count <= 0 or bucket_count & (bucket_count - 1):
        raise ValueError("bucket_count must be a positive power of two")
    return int(hashlib.sha256(str(root_id).encode("utf-8")).hexdigest()[:16], 16) % bucket_count


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _logical_table_hash(con: sqlite3.Connection, table: str, id_col: str, hash_col: str, where: str = "", params: Iterable[Any] = ()) -> str:
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


@dataclass(frozen=True)
class RangeShardSpec:
    year: int
    symbol: str
    timeframe: str
    root_month: str
    bucket_count: int
    bucket_index: int

    def validate(self) -> None:
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
            "year": self.year,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "root_month": self.root_month,
            "bucket_count": self.bucket_count,
            "bucket_index": self.bucket_index,
        }


class Stage6RangeShardEngine(Group8Engine):
    def __init__(
        self,
        *,
        stage5_db: Path,
        checkpoint_path: Path,
        shard_spec: RangeShardSpec,
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
        if contract["partitioning"]["partition_root_rules"]["range_chain"] != "pa_bounded_range_context candidate_id; all range descendants inherit it":
            raise RuntimeError("range_chain partition-root rule drift")
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

    def _expected_pairs(self) -> set[tuple[str, str]]:
        rows = self.input.execute(
            "SELECT DISTINCT symbol,timeframe FROM source__bars WHERE symbol=? ORDER BY symbol,timeframe",
            (self.shard_spec.symbol,),
        ).fetchall()
        return {(str(r[0]), str(r[1])) for r in rows}

    def verify_stage5_boundary(self) -> None:
        expected = self._expected_pairs()
        got = {
            (str(r[0]), str(r[1]))
            for r in self.base.execute(
                "SELECT symbol,timeframe FROM processing_checkpoint WHERE stage=? AND status='PASS'",
                (STAGE5_CHECKPOINT,),
            )
        }
        if got != expected:
            raise RuntimeError(f"Stage 5 boundary mismatch: expected={sorted(expected)} got={sorted(got)}")
        stage6 = int(
            self.base.execute(
                "SELECT COUNT(*) FROM processing_checkpoint WHERE stage=? AND status='PASS'",
                (STAGE6_CHECKPOINT,),
            ).fetchone()[0]
        )
        if stage6:
            raise RuntimeError("Stage 5 boundary already contains Stage 6 PASS checkpoints")
        defs = ",".join("?" for _ in STAGE6_DEFINITIONS)
        stage6_rows = int(
            self.base.execute(
                f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({defs})",
                STAGE6_DEFINITIONS,
            ).fetchone()[0]
        )
        if stage6_rows:
            raise RuntimeError(f"Stage 5 boundary contains Stage 6 domain rows: {stage6_rows}")

    def load_target_context(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[int]]:
        spec = self.shard_spec
        ranges: list[dict[str, Any]] = []
        for r in self.base.execute(
            """SELECT candidate_id,symbol,timeframe,event_time,confirmation_time,availability_time,
                      lower,upper,features_json
               FROM price_action_pattern_candidate
               WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?
               ORDER BY availability_time,candidate_id""",
            (spec.symbol, spec.timeframe),
        ):
            rid = str(r["candidate_id"])
            if epoch_month(int(r["event_time"])) != spec.root_month:
                continue
            if bucket_for_root(rid, spec.bucket_count) != spec.bucket_index:
                continue
            d = dict(r)
            d["_layer"] = (json.loads(r["features_json"]) or {}).get("layer")
            ranges.append(d)

        dows: list[dict[str, Any]] = []
        for r in self.base.execute(
            """SELECT interpretation_id,event_time,confirmation_time,availability_time,upstream_refs_json
               FROM school_interpretation
               WHERE definition_id='dow_indeterminate_structure' AND symbol=? AND timeframe=?
               ORDER BY availability_time,interpretation_id""",
            (spec.symbol, spec.timeframe),
        ):
            d = dict(r)
            refs = json.loads(r["upstream_refs_json"])
            d["_layer"] = ((refs[0].get("details") or {}).get("layer")) if refs else None
            dows.append(d)

        liquidity: list[dict[str, Any]] = [
            dict(r)
            for r in self.input.execute(
                """SELECT e.event_id,e.pool_id,e.timeframe,e.candidate_time,e.resolved_time,
                          e.reclaimed,e.is_sweep,e.is_stop_run,e.is_false_breakout,
                          p.symbol,p.anchor_price,p.lower,p.upper,p.available_at AS pool_available_at,
                          p.origin_atr
                   FROM group5__liquidity_events e
                   JOIN group5__liquidity_pools p ON p.pool_id=e.pool_id
                   WHERE p.symbol=? AND e.timeframe=? AND e.resolved_time IS NOT NULL
                   ORDER BY e.resolved_time,e.event_id""",
                (spec.symbol, spec.timeframe),
            )
        ]
        liquidity_times = [int(r["resolved_time"]) for r in liquidity]
        return ranges, dows, liquidity, liquidity_times

    @staticmethod
    def _eligible_dows(rg: dict[str, Any], dows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        avail = int(rg["availability_time"])
        layer = rg.get("_layer")
        out = []
        for dow in dows:
            if int(dow["availability_time"]) > avail:
                break
            dlayer = dow.get("_layer")
            if layer is not None and dlayer is not None and str(layer) != str(dlayer):
                continue
            out.append(dow)
        return out

    def _process_pair(
        self,
        rg: dict[str, Any],
        dow: dict[str, Any],
        liquidity: list[dict[str, Any]],
        liquidity_times: list[int],
    ) -> tuple[int, int]:
        iid = self._write_interpretation(
            "wyckoff_range_context",
            symbol=rg["symbol"],
            timeframe=rg["timeframe"],
            direction="neutral",
            event_time=max_time(rg["event_time"], dow["event_time"]),
            confirmation_time=max_time(rg["confirmation_time"], dow["confirmation_time"]),
            availability_time=max_time(rg["availability_time"], dow["availability_time"]),
            ambiguous=True,
            upstream_refs=[
                self._ref("group8", "price_action_pattern_candidate", rg["candidate_id"], rg["availability_time"]),
                self._ref("group8", "school_interpretation", dow["interpretation_id"], dow["availability_time"]),
            ],
            evidence_strength={"range_context": 1, "indeterminate_structure": 1},
        )
        tol_base = float(self.config["feature_parameters"]["proximity_atr_fraction"])
        start = bisect.bisect_left(liquidity_times, int(rg["availability_time"]))
        emitted = 0
        scanned = 0
        for ev in liquidity[start:]:
            scanned += 1
            if not (ev["reclaimed"] and (ev["is_sweep"] or ev["is_stop_run"] or ev["is_false_breakout"])):
                continue
            event_av = int(ev["resolved_time"])
            pool_av = int(ev["pool_available_at"])
            atr = float(ev["origin_atr"] or 0)
            inc = self.point_increment.get(rg["symbol"])
            tol = max([x for x in (inc, tol_base * atr if atr else None) if x is not None], default=0.0)
            anchor = float(
                ev["anchor_price"]
                if ev["anchor_price"] is not None
                else (float(ev["lower"]) + float(ev["upper"])) / 2
            )
            for definition, bound, direction in (
                ("wyckoff_spring_candidate", float(rg["lower"]), "bullish"),
                ("wyckoff_upthrust_candidate", float(rg["upper"]), "bearish"),
            ):
                if abs(anchor - bound) > tol:
                    continue
                self._write_interpretation(
                    definition,
                    symbol=rg["symbol"],
                    timeframe=rg["timeframe"],
                    direction=direction,
                    event_time=int(ev["candidate_time"]),
                    confirmation_time=event_av,
                    availability_time=max_time(rg["availability_time"], dow["availability_time"], event_av, pool_av),
                    upstream_refs=[
                        self._ref(
                            "group8",
                            "school_interpretation",
                            iid,
                            max_time(rg["availability_time"], dow["availability_time"]),
                        ),
                        self._ref(
                            "group5",
                            "liquidity_events",
                            ev["event_id"],
                            event_av,
                            event_time=ev["candidate_time"],
                            timeframe=rg["timeframe"],
                        ),
                        self._ref(
                            "group5",
                            "liquidity_pools",
                            ev["pool_id"],
                            pool_av,
                            timeframe=rg["timeframe"],
                        ),
                    ],
                    evidence_strength={"boundary_distance": abs(anchor - bound), "tolerance": tol},
                )
                emitted += 1
        return emitted, scanned

    def _load_checkpoint(self) -> dict[str, Any] | None:
        if not self.checkpoint_path.exists():
            defs = ",".join("?" for _ in STAGE6_DEFINITIONS)
            rows = int(
                self.out.execute(
                    f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({defs})",
                    STAGE6_DEFINITIONS,
                ).fetchone()[0]
            )
            if rows:
                raise RuntimeError("Stage 6 shard has rows but no checkpoint; fail closed")
            return None
        cp = json.loads(self.checkpoint_path.read_text())
        if cp.get("spec") != self.shard_spec.identity:
            raise RuntimeError("checkpoint shard identity mismatch")
        return cp

    def _write_progress(
        self,
        *,
        committed_pairs: int,
        total_pairs: int,
        commit_count: int,
        started: float,
        emitted_candidates: int,
        scanned_liquidity_rows: int,
        completed: bool,
    ) -> dict[str, Any]:
        elapsed = max(time.monotonic() - started, 1e-9)
        rate = committed_pairs / elapsed
        remaining = max(total_pairs - committed_pairs, 0)
        eta = (remaining / rate) if rate > 0 else None
        rec = {
            "schema": "moebot-group8-v3-stage6-checkpoint-v1",
            "status": "PASS" if completed else "RUNNING",
            "spec": self.shard_spec.identity,
            "committed_pairs": committed_pairs,
            "total_pairs": total_pairs,
            "progress_percent": 100.0 if total_pairs == 0 else round(100.0 * committed_pairs / total_pairs, 6),
            "elapsed_seconds": round(elapsed, 3),
            "pairs_per_second": round(rate, 6),
            "eta_seconds": None if eta is None else round(eta, 3),
            "commit_count": commit_count,
            "emitted_spring_upthrust_rows": emitted_candidates,
            "scanned_liquidity_rows": scanned_liquidity_rows,
            "output_db_size_bytes": self.output_db.stat().st_size if self.output_db.exists() else 0,
            "completed": completed,
            "updated_unix": int(time.time()),
        }
        rec["checkpoint_hash"] = stable_hash(rec)
        _atomic_json(self.checkpoint_path, rec)
        return rec

    def run_resumable(self, *, chunk_pairs: int, max_chunks: int | None = None) -> dict[str, Any]:
        if chunk_pairs <= 0:
            raise ValueError("chunk_pairs must be positive")
        self.verify_stage5_boundary()
        self.load_bars()
        key = (self.shard_spec.symbol, self.shard_spec.timeframe)
        bars = self.bars_by_tf.get(key)
        if not bars:
            raise RuntimeError(f"no bars for Stage 6 shard {key}")
        self.bars_by_tf = {key: bars}
        self.bar_pos = {bar.id: (key, i) for i, bar in enumerate(bars)}
        ranges, dows, liquidity, liquidity_times = self.load_target_context()
        eligible = [(rg, self._eligible_dows(rg, dows)) for rg in ranges]
        total_pairs = sum(len(x[1]) for x in eligible)
        cp = self._load_checkpoint()
        already = int(cp.get("committed_pairs", 0)) if cp else 0
        if cp and cp.get("completed") is True:
            return cp
        if already > total_pairs:
            raise RuntimeError("checkpoint exceeds deterministic work-unit cardinality")

        started = time.monotonic()
        commit_count = int(cp.get("commit_count", 0)) if cp else 0
        emitted = int(cp.get("emitted_spring_upthrust_rows", 0)) if cp else 0
        scanned = int(cp.get("scanned_liquidity_rows", 0)) if cp else 0
        ordinal = 0
        chunk_work = 0
        chunks_this_run = 0

        for rg, rg_dows in eligible:
            for dow in rg_dows:
                if ordinal < already:
                    ordinal += 1
                    continue
                new_emitted, new_scanned = self._process_pair(rg, dow, liquidity, liquidity_times)
                emitted += new_emitted
                scanned += new_scanned
                ordinal += 1
                chunk_work += 1
                if chunk_work >= chunk_pairs:
                    self.out.commit()
                    commit_count += 1
                    chunks_this_run += 1
                    if self.output_db.stat().st_size > self.hard_guard_bytes:
                        raise RuntimeError("Stage 6 shard exceeded frozen runtime hard guard")
                    self._write_progress(
                        committed_pairs=ordinal,
                        total_pairs=total_pairs,
                        commit_count=commit_count,
                        started=started,
                        emitted_candidates=emitted,
                        scanned_liquidity_rows=scanned,
                        completed=False,
                    )
                    chunk_work = 0
                    if max_chunks is not None and chunks_this_run >= max_chunks:
                        return json.loads(self.checkpoint_path.read_text())

        if chunk_work:
            self.out.commit()
            commit_count += 1
        if self.output_db.stat().st_size > self.hard_guard_bytes:
            raise RuntimeError("Stage 6 shard exceeded frozen runtime hard guard")
        return self._write_progress(
            committed_pairs=total_pairs,
            total_pairs=total_pairs,
            commit_count=commit_count,
            started=started,
            emitted_candidates=emitted,
            scanned_liquidity_rows=scanned,
            completed=True,
        )


def build_manifest(
    *,
    output_db: Path,
    artifacts_root: Path,
    spec: RangeShardSpec,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{output_db.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        qc = con.execute("PRAGMA quick_check").fetchone()[0]
        ic = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if qc != "ok" or ic != "ok" or fk:
            raise RuntimeError(f"Stage 6 shard validation failed qc={qc} ic={ic} fk={len(fk)}")
        defs = ",".join("?" for _ in STAGE6_DEFINITIONS)
        counts = {
            "school_interpretation": int(
                con.execute(
                    f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({defs})",
                    STAGE6_DEFINITIONS,
                ).fetchone()[0]
            ),
            "evidence_chain": int(con.execute("SELECT COUNT(*) FROM evidence_chain").fetchone()[0]),
        }
        by_def = {
            str(r[0]): int(r[1])
            for r in con.execute(
                f"SELECT definition_id,COUNT(*) FROM school_interpretation WHERE definition_id IN ({defs}) GROUP BY definition_id ORDER BY definition_id",
                STAGE6_DEFINITIONS,
            )
        }
        times = con.execute(
            f"""SELECT MIN(event_time),MAX(event_time),MIN(availability_time),MAX(availability_time)
                FROM school_interpretation WHERE definition_id IN ({defs})""",
            STAGE6_DEFINITIONS,
        ).fetchone()
        logical = {
            "school_interpretation": _logical_table_hash(
                con,
                "school_interpretation",
                "interpretation_id",
                "interpretation_hash",
                f"definition_id IN ({defs})",
                STAGE6_DEFINITIONS,
            ),
            "evidence_chain": _logical_table_hash(
                con,
                "evidence_chain",
                "evidence_chain_id",
                "evidence_hash",
            ),
        }
    finally:
        con.close()

    freeze = json.loads((artifacts_root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    contract = json.loads((artifacts_root / "SHARDED_STORAGE_CONTRACT.json").read_text())
    payload = {
        "family": "range_chain",
        "year": spec.year,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "causal_root_window": spec.root_month,
        "partition_root_rule": contract["partitioning"]["partition_root_rules"]["range_chain"],
        "bucket_index": spec.bucket_index,
        "bucket_count": spec.bucket_count,
    }
    rec = {
        "format_version": 1,
        "status": "PASS",
        "stage": 6,
        "stage_name": "wyckoff_core",
        "shard_id": "g8shard_" + stable_hash(payload),
        **payload,
        "file_size_bytes": output_db.stat().st_size,
        "sha256": sha256_file(output_db),
        "compressed_sha256": None,
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
        "stage5_database_sha256": None,
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
    spec: RangeShardSpec,
    chunk_pairs: int,
    hard_guard_bytes: int,
    max_chunks: int | None = None,
) -> dict[str, Any]:
    engine = Stage6RangeShardEngine(
        staging_db=staging_db,
        output_db=output_db,
        artifacts_root=artifacts_root,
        year=spec.year,
        symbol=spec.symbol,
        stage5_db=stage5_db,
        checkpoint_path=checkpoint_path,
        shard_spec=spec,
        hard_guard_bytes=hard_guard_bytes,
    )
    try:
        cp = engine.run_resumable(chunk_pairs=chunk_pairs, max_chunks=max_chunks)
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
    )
    manifest["stage5_database_sha256"] = sha256_file(stage5_db)
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = stable_hash(manifest)
    _atomic_json(manifest_path, manifest)
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--root-month", required=True)
    p.add_argument("--bucket-count", type=int, required=True)
    p.add_argument("--bucket-index", type=int, required=True)
    p.add_argument("--chunk-pairs", type=int, default=100)
    p.add_argument("--hard-guard-bytes", type=int, default=2_500_000_000)
    a = p.parse_args()
    spec = RangeShardSpec(
        a.year,
        a.symbol,
        a.timeframe,
        a.root_month,
        a.bucket_count,
        a.bucket_index,
    )
    report = run_shard(
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        output_db=a.output_db.resolve(),
        checkpoint_path=a.checkpoint.resolve(),
        manifest_path=a.manifest.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        spec=spec,
        chunk_pairs=a.chunk_pairs,
        hard_guard_bytes=a.hard_guard_bytes,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
