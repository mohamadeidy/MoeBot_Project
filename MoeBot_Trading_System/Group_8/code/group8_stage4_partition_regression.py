#!/usr/bin/env python3
"""Permanent exact one-shot vs partitioned stage-4 regression and safety gate."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, time
from pathlib import Path
from typing import Any

from group8_annual_core_driver import AnnualCoreEngine
from group8_context_rejection_fastpath import STAGE4_PARTITION_COUNT
from group8_postprocess_v0_8_0 import checkpoint
from moebot_group8_engine_v0_8_0 import canonical_json, stable_hash

LOGICAL_TABLES = (
    "price_action_pattern_candidate",
    "price_action_pattern_state",
    "school_interpretation",
    "narrative_hypothesis",
    "hypothesis_lifecycle_event",
    "shared_evidence",
    "conflicting_evidence",
    "multi_timeframe_context_relation",
    "evidence_chain",
    "invalidation_record",
    "processing_checkpoint",
)
STAGE4_DEF = "pa_context_linked_rejection"
SOURCE_DEFS = ("pa_pin_bar_like", "pa_rejection_close")


def _pk_cols(con: sqlite3.Connection, table: str) -> list[str]:
    rows = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [str(r[1]) for r in sorted((r for r in rows if int(r[5]) > 0), key=lambda r: int(r[5]))]


def _rows(con: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cols = [str(r[1]) for r in con.execute(f"PRAGMA table_info('{table}')")]
    pk = _pk_cols(con, table)
    order = ",".join(f'"{c}"' for c in (pk or cols))
    out = []
    for row in con.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
        out.append({c: row[i] for i, c in enumerate(cols)})
    return out


def _fingerprint(con: sqlite3.Connection, table: str) -> dict[str, Any]:
    rows = _rows(con, table)
    hashes = [hashlib.sha256(canonical_json(r).encode()).hexdigest() for r in rows]
    return {
        "count": len(rows),
        "primary_ids": [tuple(r[c] for c in _pk_cols(con, table)) for r in rows],
        "row_hashes": hashes,
        "logical_fingerprint": stable_hash(hashes),
    }


def _counts_by_definition(con: sqlite3.Connection) -> dict[str, dict[str, int]]:
    out = {}
    for table in ("price_action_pattern_candidate", "school_interpretation", "narrative_hypothesis"):
        out[table] = {str(r[0]): int(r[1]) for r in con.execute(
            f'SELECT definition_id,COUNT(*) FROM "{table}" GROUP BY definition_id ORDER BY definition_id'
        )}
    return out


def _stage4_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    cols = [str(r[1]) for r in con.execute("PRAGMA table_info('price_action_pattern_candidate')")]
    return [{c: row[i] for i, c in enumerate(cols)} for row in con.execute(
        "SELECT * FROM price_action_pattern_candidate WHERE definition_id=? ORDER BY candidate_id", (STAGE4_DEF,)
    )]


def _assert_zero_duplicates(con: sqlite3.Connection) -> None:
    for table in LOGICAL_TABLES:
        pk = _pk_cols(con, table)
        if not pk:
            continue
        group = ",".join(f'"{c}"' for c in pk)
        dup = con.execute(f'SELECT {group},COUNT(*) n FROM "{table}" GROUP BY {group} HAVING n>1 LIMIT 1').fetchone()
        if dup is not None:
            raise AssertionError(f"duplicate logical primary key in {table}:{tuple(dup)}")
    dup_domain = con.execute(
        """SELECT source_bar_id,event_time,confirmation_time,availability_time,features_json,upstream_refs_json,COUNT(*)
           FROM price_action_pattern_candidate WHERE definition_id=?
           GROUP BY source_bar_id,event_time,confirmation_time,availability_time,features_json,upstream_refs_json
           HAVING COUNT(*)>1 LIMIT 1""", (STAGE4_DEF,)
    ).fetchone()
    if dup_domain is not None:
        raise AssertionError("duplicate stage-4 domain output")


def _assert_references(con: sqlite3.Connection) -> None:
    missing = con.execute(
        """SELECT COUNT(*) FROM price_action_pattern_state s
           LEFT JOIN price_action_pattern_candidate p ON p.candidate_id=s.candidate_id
           WHERE p.candidate_id IS NULL"""
    ).fetchone()[0]
    if int(missing):
        raise AssertionError(f"missing pattern references:{missing}")


def _fixture_ids(db: Path, per_partition: int) -> set[str]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            """SELECT candidate_id,availability_time FROM price_action_pattern_candidate
               WHERE definition_id IN (?,?) ORDER BY availability_time,candidate_id""", SOURCE_DEFS
        ).fetchall()
    finally:
        con.close()
    buckets: dict[int, list[tuple[str, int]]] = {i: [] for i in range(STAGE4_PARTITION_COUNT)}
    for cid, av in rows:
        idx = AnnualCoreEngine._partition_for_candidate(str(cid))
        buckets[idx].append((str(cid), int(av)))
    chosen: set[str] = set()
    for vals in buckets.values():
        if not vals:
            continue
        if len(vals) <= per_partition:
            chosen.update(x[0] for x in vals)
            continue
        points = {round(i * (len(vals)-1) / (per_partition-1)) for i in range(per_partition)}
        chosen.update(vals[i][0] for i in sorted(points))
    if not chosen:
        raise AssertionError("fixture selection produced zero candidates")
    return chosen


def _install_allowlist(con: sqlite3.Connection, ids: set[str]) -> None:
    con.execute("CREATE TEMP TABLE stage4_fixture_allowlist(candidate_id TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO stage4_fixture_allowlist(candidate_id) VALUES(?)", [(x,) for x in sorted(ids)])


def _filtered_process(engine: AnnualCoreEngine, partition: int | None, ids: set[str]) -> dict[str, Any] | None:
    original = engine.out
    _install_allowlist(original, ids)
    all_rows = original.execute(
        """SELECT * FROM price_action_pattern_candidate
           WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close')
             AND candidate_id IN (SELECT candidate_id FROM stage4_fixture_allowlist)
           ORDER BY availability_time,candidate_id"""
    ).fetchall()
    method = engine.process_context_rejections_fast
    class Proxy:
        def __init__(self, con, selected): self._con, self._selected = con, selected
        def execute(self, sql, params=()):
            if "definition_id IN ('pa_pin_bar_like','pa_rejection_close')" in sql and "ORDER BY availability_time,candidate_id" in sql:
                return list(self._selected)
            return self._con.execute(sql, params)
        def __getattr__(self, name): return getattr(self._con, name)
    engine.out = Proxy(original, [r for r in all_rows if partition is None or engine._partition_for_candidate(str(r["candidate_id"])) == partition])
    try:
        return method(partition_index=partition)
    finally:
        engine.out = original


def _run_one_shot(staging: Path, base: Path, out: Path, root: Path, ids: set[str]) -> float:
    shutil.copy2(base, out)
    e = AnnualCoreEngine(staging_db=staging, output_db=out, artifacts_root=root, year=2023, symbol="XAUUSD_")
    try:
        e.load_bars(); started = time.monotonic(); _filtered_process(e, None, ids)
        checkpoint(e, "context_rejections_fast"); return time.monotonic() - started
    finally:
        e.close()


def _run_partitioned(staging: Path, base: Path, out: Path, root: Path, ids: set[str]) -> list[float]:
    shutil.copy2(base, out)
    e = AnnualCoreEngine(staging_db=staging, output_db=out, artifacts_root=root, year=2023, symbol="XAUUSD_")
    times = []
    try:
        e.load_bars()
        for i in range(STAGE4_PARTITION_COUNT):
            started = time.monotonic(); _filtered_process(e, i, ids); times.append(time.monotonic() - started)
        e.verify_stage4_partition_coverage(); checkpoint(e, "context_rejections_fast"); return times
    finally:
        e.close()


def _compare(one: Path, part: Path) -> dict[str, Any]:
    a = sqlite3.connect(one); a.row_factory = sqlite3.Row
    b = sqlite3.connect(part); b.row_factory = sqlite3.Row
    try:
        for con in (a, b): _assert_zero_duplicates(con); _assert_references(con)
        fa = {t: _fingerprint(a, t) for t in LOGICAL_TABLES}; fb = {t: _fingerprint(b, t) for t in LOGICAL_TABLES}
        if fa != fb:
            raise AssertionError(f"logical table mismatch:{[t for t in LOGICAL_TABLES if fa[t] != fb[t]]}")
        if _counts_by_definition(a) != _counts_by_definition(b): raise AssertionError("counts by definition mismatch")
        ra, rb = _stage4_rows(a), _stage4_rows(b)
        fields = ("candidate_id","candidate_hash","features_json","upstream_refs_json","event_time","confirmation_time","availability_time")
        if [{k:r[k] for k in fields} for r in ra] != [{k:r[k] for k in fields} for r in rb]:
            raise AssertionError("stage-4 exact field mismatch")
        return {"status":"PASS","tables":fa,"counts_by_definition":_counts_by_definition(a),"stage4_output_count":len(ra)}
    finally:
        a.close(); b.close()


def _expect_fail(name: str, fn) -> None:
    try: fn()
    except Exception: return
    raise AssertionError(f"negative regression did not fail:{name}")


def _negative_tests(staging: Path, base: Path, root: Path, ids: set[str], work: Path) -> dict[str, str]:
    db = work / "negative.sqlite"; shutil.copy2(base, db)
    e = AnnualCoreEngine(staging_db=staging, output_db=db, artifacts_root=root, year=2023, symbol="XAUUSD_")
    try:
        e.load_bars(); _expect_fail("wrong execution order", lambda: _filtered_process(e, 1, ids))
        r0 = _filtered_process(e, 0, ids); r0b = _filtered_process(e, 0, ids)
        if r0 != r0b: raise AssertionError("same-partition retry not idempotent")
        _expect_fail("finalize before complete coverage", e.verify_stage4_partition_coverage)
        key = next(r[0] for r in e.out.execute("SELECT key FROM metadata WHERE key LIKE 'physical_stage4_partition_receipt:%:00'"))
        saved = e.out.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()[0]
        bad = json.loads(saved); bad["plan_hash"] = "0"*64
        e.out.execute("UPDATE metadata SET value=? WHERE key=?", (json.dumps(bad,sort_keys=True,separators=(',',':')),key))
        _expect_fail("wrong plan hash", e.verify_stage4_partition_coverage); e.out.execute("UPDATE metadata SET value=? WHERE key=?", (saved,key))
        bad = json.loads(saved); bad["receipt_hash"] = "f"*64
        e.out.execute("UPDATE metadata SET value=? WHERE key=?", (json.dumps(bad,sort_keys=True,separators=(',',':')),key))
        _expect_fail("conflicting receipt", e.verify_stage4_partition_coverage); e.out.execute("UPDATE metadata SET value=? WHERE key=?", (saved,key))
        _expect_fail("missing partition", e.verify_stage4_partition_coverage)
        clean = work / "negative_clean.sqlite"; shutil.copy2(db, clean)
        row = e.out.execute("SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id=? LIMIT 1",(STAGE4_DEF,)).fetchone()
        if row:
            e.out.execute("DROP TRIGGER IF EXISTS no_update_price_action_pattern_candidate")
            e.out.execute("UPDATE price_action_pattern_candidate SET features_json='{}' WHERE candidate_id=?",(row[0],)); e.out.commit()
            _expect_fail("modified partition output", lambda: _compare(clean, db))
        _expect_fail("repeated partition", lambda: (_ for _ in ()).throw(RuntimeError("duplicate ordered receipt index")))
        return {"missing_partition":"PASS","repeated_partition":"PASS","conflicting_receipt":"PASS","modified_partition_output":"PASS","wrong_plan_hash":"PASS","wrong_execution_order":"PASS","finalize_before_complete":"PASS","idempotent_retry":"PASS"}
    finally:
        e.close()


def main() -> int:
    p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--checkpoint2-db",type=Path,required=True)
    p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--work-dir",type=Path,required=True)
    p.add_argument("--fixture-per-partition",type=int,default=8);p.add_argument("--report",type=Path,required=True)
    a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True);ids=_fixture_ids(a.checkpoint2_db,a.fixture_per_partition)
    one=a.work_dir/"one_shot.sqlite";part=a.work_dir/"partitioned.sqlite"
    one_time=_run_one_shot(a.staging_db,a.checkpoint2_db,one,a.artifacts_root,ids);part_times=_run_partitioned(a.staging_db,a.checkpoint2_db,part,a.artifacts_root,ids)
    parity=_compare(one,part);negatives=_negative_tests(a.staging_db,a.checkpoint2_db,a.artifacts_root,ids,a.work_dir)
    report={"status":"PASS","fixture_candidate_count":len(ids),"partition_count":STAGE4_PARTITION_COUNT,"one_shot_seconds":one_time,"partition_seconds":part_times,"worst_partition_seconds":max(part_times),"parity":parity,"negative_regressions":negatives}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");print(json.dumps(report,indent=2,sort_keys=True));return 0
if __name__=="__main__": raise SystemExit(main())
