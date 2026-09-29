#!/usr/bin/env python3
"""Build the exact real Group 9 root inventory from frozen Group 8 V3 outputs.

Read-only upstream rules:
- Stage 5 is restored one year at a time from its verified zstd archive.
- Stage 7 is decompressed one relevant school_core shard at a time.
- Every decompressed raw SQLite SHA-256 is verified while streaming.
- No outcome data is read and no Group 8 semantic artifact is modified.
- The retained inventory is a compact SQLite index, not a giant JSON list.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT_DEFS = {
    "ict_liquidity_sweep_displacement": ("G9_ICT_LIQUIDITY_DELIVERY", "school_interpretation"),
    "wyckoff_spring_candidate": ("G9_WYCKOFF_RANGE_RESOLUTION", "school_interpretation"),
    "wyckoff_upthrust_candidate": ("G9_WYCKOFF_RANGE_RESOLUTION", "school_interpretation"),
    "pa_structural_pullback": ("G9_STRUCTURAL_PULLBACK_CONTINUATION", "narrative_hypothesis"),
}
SCHOOL_ROOTS = tuple(k for k, (_, t) in ROOT_DEFS.items() if t == "school_interpretation")
NARRATIVE_ROOTS = tuple(k for k, (_, t) in ROOT_DEFS.items() if t == "narrative_hypothesis")
ALLOWED_DIRECTIONS = {"bullish", "bearish"}


def stable(v: Any) -> str:
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_hashed(path: Path, fields=("manifest_hash", "report_hash", "release_hash", "registry_hash", "closure_hash")) -> dict[str, Any]:
    rec = json.loads(path.read_text())
    for field in fields:
        if field in rec:
            x = dict(rec)
            saved = str(x.pop(field))
            if stable(x) != saved:
                raise RuntimeError(f"{path.name}:{field}_mismatch")
            return rec
    raise RuntimeError(f"{path.name}:no_self_hash")


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def restore_marker_path(raw: Path) -> Path:
    return raw.with_suffix(raw.suffix + ".verified.json")


def load_verified_restore_marker(raw: Path, rep: dict[str, Any]) -> bool:
    marker = restore_marker_path(raw)
    if not raw.is_file() or not marker.is_file():
        return False
    try:
        m = json.loads(marker.read_text())
    except Exception:
        return False
    if "marker_hash" not in m:
        return False
    mx = dict(m)
    saved_marker_hash = str(mx.pop("marker_hash"))
    if stable(mx) != saved_marker_hash:
        return False
    return (
        m.get("status") == "VERIFIED_STAGE5_RESTORE"
        and int(m.get("year", -1)) == int(rep["year"])
        and int(m.get("raw_size_bytes", -1)) == int(rep["raw_size_bytes"])
        and str(m.get("raw_sha256")) == str(rep["raw_sha256"])
        and str(m.get("archive_report_hash")) == str(rep["report_hash"])
        and raw.stat().st_size == int(rep["raw_size_bytes"])
    )


def write_verified_restore_marker(raw: Path, rep: dict[str, Any], *, provenance: str) -> None:
    marker = restore_marker_path(raw)
    rec = {
        "format_version": 1,
        "status": "VERIFIED_STAGE5_RESTORE",
        "year": int(rep["year"]),
        "raw_size_bytes": int(rep["raw_size_bytes"]),
        "raw_sha256": str(rep["raw_sha256"]),
        "archive_sha256": str(rep["archive_sha256"]),
        "archive_report_hash": str(rep["report_hash"]),
        "provenance": provenance,
    }
    rec["marker_hash"] = stable(rec)
    atomic_json(marker, rec)


def month_utc(epoch: int) -> str:
    return time.strftime("%Y-%m", time.gmtime(int(epoch)))


def stream_decompress_verified(zstd: Path, archive: Path, output: Path, expected_raw_sha: str) -> tuple[int, float]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    started = time.perf_counter()
    h = hashlib.sha256()
    total = 0
    proc = subprocess.Popen(
        [str(zstd), "-d", "-c", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        with output.open("wb") as out:
            while True:
                chunk = proc.stdout.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                total += len(chunk)
        stderr = b""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
        rc = proc.wait()
        if rc:
            raise RuntimeError(f"zstd_decompress_failed:{archive}:{stderr.decode(errors='replace')[-2000:]}")
    except Exception:
        proc.kill()
        if output.exists():
            output.unlink()
        raise
    got = h.hexdigest()
    if got != str(expected_raw_sha):
        output.unlink(missing_ok=True)
        raise RuntimeError(f"raw_sha_mismatch:{archive.name}:expected={expected_raw_sha}:got={got}")
    return total, time.perf_counter() - started


def fast_readonly_schema_check(path: Path, required_tables: tuple[str, ...]) -> None:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        tables = {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(set(required_tables) - tables)
        if missing:
            raise RuntimeError(f"sqlite_required_tables_missing:{path}:{','.join(missing)}")
        # Fast header/page accessibility probe only. Full quick_check on 70-150 GiB
        # immutable upstream copies would duplicate Group 8 integrity work and add
        # hours of I/O; exact raw SHA + official upstream closure remain authoritative.
        con.execute("PRAGMA schema_version").fetchone()
    finally:
        con.close()


def init_inventory(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.executescript(
        """
        CREATE TABLE root_candidate(
          root_key TEXT PRIMARY KEY,
          dataset_year INTEGER NOT NULL,
          setup_family TEXT NOT NULL,
          source_group INTEGER NOT NULL,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          timeframe TEXT NOT NULL,
          direction TEXT NOT NULL CHECK(direction IN ('bullish','bearish')),
          event_time INTEGER NOT NULL,
          availability_time INTEGER NOT NULL,
          root_month TEXT NOT NULL,
          source_row_hash TEXT NOT NULL
        );
        CREATE INDEX ix_root_candidate_scope
          ON root_candidate(dataset_year,symbol,timeframe,root_month,setup_family,definition_id);
        CREATE INDEX ix_root_candidate_availability
          ON root_candidate(availability_time,event_time);
        CREATE TABLE inventory_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """
    )
    return con


def insert_rows(con: sqlite3.Connection, rows: Iterable[tuple], *, expected_source_type: str) -> tuple[int, int]:
    inserted = 0
    seen = 0
    sql = """
      INSERT INTO root_candidate(
        root_key,dataset_year,setup_family,source_group,source_type,source_id,
        definition_id,symbol,timeframe,direction,event_time,availability_time,
        root_month,source_row_hash
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    for (
        dataset_year,
        source_id,
        definition_id,
        symbol,
        timeframe,
        direction,
        event_time,
        availability_time,
        source_row_hash,
    ) in rows:
        seen += 1
        definition_id = str(definition_id)
        if definition_id not in ROOT_DEFS:
            raise RuntimeError(f"unexpected_root_definition:{definition_id}")
        setup_family, source_type = ROOT_DEFS[definition_id]
        if source_type != expected_source_type:
            raise RuntimeError(f"root_source_type_mismatch:{definition_id}")
        direction = str(direction)
        if direction not in ALLOWED_DIRECTIONS:
            raise RuntimeError(f"invalid_root_direction:{definition_id}:{source_id}:{direction}")
        event_time = int(event_time)
        availability_time = int(availability_time)
        if event_time > availability_time:
            raise RuntimeError(f"root_event_after_availability:{source_id}")
        source_id = str(source_id)
        root_key = f"{source_type}:{source_id}"
        try:
            con.execute(
                sql,
                (
                    root_key,
                    int(dataset_year),
                    setup_family,
                    8,
                    source_type,
                    source_id,
                    definition_id,
                    str(symbol),
                    str(timeframe),
                    direction,
                    event_time,
                    availability_time,
                    month_utc(event_time),
                    str(source_row_hash),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(f"duplicate_or_invalid_root:{root_key}") from exc
    return seen, inserted


def query_stage5_roots(path: Path, year: int) -> Iterable[tuple]:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        q = ",".join("?" for _ in NARRATIVE_ROOTS)
        for r in con.execute(
            f"""
            SELECT hypothesis_id,definition_id,symbol,timeframe,direction,
                   event_time,availability_time,hypothesis_hash
            FROM narrative_hypothesis
            WHERE definition_id IN ({q})
            ORDER BY hypothesis_id
            """,
            NARRATIVE_ROOTS,
        ):
            yield (year, *r)
    finally:
        con.close()


def query_stage7_roots(path: Path, year: int) -> Iterable[tuple]:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        q = ",".join("?" for _ in SCHOOL_ROOTS)
        for r in con.execute(
            f"""
            SELECT interpretation_id,definition_id,symbol,timeframe,direction,
                   event_time,availability_time,interpretation_hash
            FROM school_interpretation
            WHERE definition_id IN ({q})
            ORDER BY interpretation_id
            """,
            SCHOOL_ROOTS,
        ):
            yield (year, *r)
    finally:
        con.close()


def logical_fingerprint(con: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for r in con.execute(
        """
        SELECT root_key,dataset_year,setup_family,source_type,source_id,definition_id,
               symbol,timeframe,direction,event_time,availability_time,root_month,source_row_hash
        FROM root_candidate ORDER BY root_key
        """
    ):
        h.update(json.dumps(list(r), separators=(",", ":"), ensure_ascii=False).encode())
        h.update(b"\n")
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dependency-intake", type=Path, required=True)
    p.add_argument("--g9-definitions", type=Path, required=True)
    p.add_argument("--stage5-archive-report", type=Path, action="append", required=True)
    p.add_argument("--stage5-archive", type=Path, action="append", required=True)
    p.add_argument("--stage7-release", type=Path, action="append", required=True)
    p.add_argument("--stage7-output-root", type=Path, action="append", required=True)
    p.add_argument("--zstd-exe", type=Path, required=True)
    p.add_argument("--scratch-root", type=Path, required=True)
    p.add_argument("--inventory-db", type=Path, required=True)
    p.add_argument("--inventory-report", type=Path, required=True)
    p.add_argument("--benchmark-report", type=Path, required=True)
    a = p.parse_args()

    dep = load_hashed(a.dependency_intake)
    defs = load_hashed(a.g9_definitions)
    if dep.get("status") != "PASS" or dep.get("dependency_intake_authorized") is not True:
        raise RuntimeError("dependency_intake_not_pass")
    if defs.get("status") != "FROZEN" or defs.get("frozen_without_outcome_tuning") is not True:
        raise RuntimeError("group9_semantics_not_frozen")
    if dep.get("semantic_registry_hash") != defs.get("registry_hash"):
        raise RuntimeError("dependency_intake_semantic_hash_drift")
    if len(a.stage5_archive_report) != len(a.stage5_archive):
        raise RuntimeError("stage5_argument_count_mismatch")
    if len(a.stage7_release) != len(a.stage7_output_root):
        raise RuntimeError("stage7_argument_count_mismatch")
    if not a.zstd_exe.is_file():
        raise RuntimeError("zstd_executable_missing")

    a.scratch_root.mkdir(parents=True, exist_ok=True)
    con = init_inventory(a.inventory_db)
    started_all = time.perf_counter()
    bench_sources: list[dict[str, Any]] = []
    source_identities: dict[str, Any] = {"stage5": [], "stage7": []}
    try:
        # Stage 5 narrative roots, restored one year at a time.
        for report_path, archive_path in zip(a.stage5_archive_report, a.stage5_archive):
            rep = load_hashed(report_path)
            if rep.get("status") != "PASS" or rep.get("lossless_roundtrip_verified") is not True:
                raise RuntimeError(f"invalid_stage5_archive_report:{report_path}")
            if not archive_path.is_file():
                raise RuntimeError(f"stage5_archive_missing:{archive_path}")
            year = int(rep["year"])
            raw = a.scratch_root / f"g9_stage5_{year}_restore.sqlite"
            if load_verified_restore_marker(raw, rep):
                raw_bytes = raw.stat().st_size
                dec_seconds = 0.0
            else:
                raw_bytes, dec_seconds = stream_decompress_verified(
                    a.zstd_exe, archive_path, raw, str(rep["raw_sha256"])
                )
                if raw_bytes != int(rep["raw_size_bytes"]):
                    raw.unlink(missing_ok=True)
                    restore_marker_path(raw).unlink(missing_ok=True)
                    raise RuntimeError(f"stage5_raw_size_mismatch:{year}")
                write_verified_restore_marker(
                    raw, rep, provenance="stream_decompress_verified_sha256_match"
                )
            if raw_bytes != int(rep["raw_size_bytes"]):
                raw.unlink(missing_ok=True)
                restore_marker_path(raw).unlink(missing_ok=True)
                raise RuntimeError(f"stage5_raw_size_mismatch:{year}")
            fast_readonly_schema_check(raw, ("narrative_hypothesis",))
            t0 = time.perf_counter()
            seen, inserted = insert_rows(
                con, query_stage5_roots(raw, year), expected_source_type="narrative_hypothesis"
            )
            con.commit()
            extract_seconds = time.perf_counter() - t0
            raw.unlink(missing_ok=True)
            restore_marker_path(raw).unlink(missing_ok=True)
            bench_sources.append(
                {
                    "source": "stage5_narrative_hypothesis",
                    "year": year,
                    "candidate_count": inserted,
                    "rows_seen": seen,
                    "decompressed_raw_bytes": raw_bytes,
                    "decompression_seconds": dec_seconds,
                    "extraction_seconds": extract_seconds,
                    "candidate_rows_per_second": inserted / max(extract_seconds, 1e-9),
                }
            )
            source_identities["stage5"].append(
                {
                    "year": year,
                    "archive_report_hash": rep["report_hash"],
                    "raw_sha256": rep["raw_sha256"],
                    "archive_sha256": rep["archive_sha256"],
                }
            )

        # Stage 7 school roots, only shards whose verified manifest says a root definition exists.
        for release_path, output_root in zip(a.stage7_release, a.stage7_output_root):
            rel = load_hashed(release_path)
            if rel.get("status") != "PASS" or int(rel.get("stage", 0)) != 7:
                raise RuntimeError(f"invalid_stage7_release:{release_path}")
            year = int(rel["year"])
            relevant = 0
            skipped = 0
            year_inserted = 0
            year_seen = 0
            year_raw_bytes = 0
            year_dec_seconds = 0.0
            year_extract_seconds = 0.0
            for x in sorted(rel["shards"], key=lambda z: int(z["ordinal"])):
                spec = x.get("spec") or {}
                if spec.get("family") != "school_core":
                    continue
                manifest_path = output_root / str(x["manifest_path"])
                archive_path = output_root / str(x["archive_path"])
                m = load_hashed(manifest_path)
                if m.get("manifest_hash") != x.get("manifest_hash"):
                    raise RuntimeError(f"stage7_manifest_identity_mismatch:{year}:{x['ordinal']}")
                coverage = m.get("definition_coverage") or {}
                expected_roots = sum(int(coverage.get(d, 0)) for d in SCHOOL_ROOTS)
                if expected_roots == 0:
                    skipped += 1
                    continue
                relevant += 1
                if not archive_path.is_file():
                    raise RuntimeError(f"stage7_archive_missing:{archive_path}")
                raw = a.scratch_root / f"g9_stage7_{year}_{int(x['ordinal']):05d}.sqlite"
                raw_bytes, dec_seconds = stream_decompress_verified(
                    a.zstd_exe, archive_path, raw, str(x["raw_sha256"])
                )
                fast_readonly_schema_check(raw, ("school_interpretation",))
                t0 = time.perf_counter()
                seen, inserted = insert_rows(
                    con, query_stage7_roots(raw, year), expected_source_type="school_interpretation"
                )
                con.commit()
                extract_seconds = time.perf_counter() - t0
                raw.unlink(missing_ok=True)
                if seen != expected_roots or inserted != expected_roots:
                    raise RuntimeError(
                        f"stage7_root_count_mismatch:{year}:{x['ordinal']}:"
                        f"manifest={expected_roots}:seen={seen}:inserted={inserted}"
                    )
                year_seen += seen
                year_inserted += inserted
                year_raw_bytes += raw_bytes
                year_dec_seconds += dec_seconds
                year_extract_seconds += extract_seconds
            bench_sources.append(
                {
                    "source": "stage7_school_interpretation",
                    "year": year,
                    "candidate_count": year_inserted,
                    "rows_seen": year_seen,
                    "relevant_shards": relevant,
                    "skipped_school_core_shards": skipped,
                    "decompressed_raw_bytes": year_raw_bytes,
                    "decompression_seconds": year_dec_seconds,
                    "extraction_seconds": year_extract_seconds,
                    "candidate_rows_per_second": year_inserted / max(year_extract_seconds, 1e-9),
                }
            )
            source_identities["stage7"].append(
                {
                    "year": year,
                    "release_hash": rel["release_hash"],
                    "shard_count": int(rel["shard_count"]),
                    "school_core_shard_count": int(rel.get("school_core_shard_count", 0)),
                }
            )

        qc = con.execute("PRAGMA quick_check").fetchone()
        if not qc or qc[0] != "ok":
            raise RuntimeError("inventory_quick_check_failed")
        total = int(con.execute("SELECT COUNT(*) FROM root_candidate").fetchone()[0])
        if total <= 0:
            raise RuntimeError("zero_group9_root_candidates")
        by_year = {str(y): int(n) for y, n in con.execute(
            "SELECT dataset_year,COUNT(*) FROM root_candidate GROUP BY dataset_year ORDER BY dataset_year"
        )}
        by_family = {str(k): int(n) for k, n in con.execute(
            "SELECT setup_family,COUNT(*) FROM root_candidate GROUP BY setup_family ORDER BY setup_family"
        )}
        by_definition = {str(k): int(n) for k, n in con.execute(
            "SELECT definition_id,COUNT(*) FROM root_candidate GROUP BY definition_id ORDER BY definition_id"
        )}
        by_tf = {str(k): int(n) for k, n in con.execute(
            "SELECT timeframe,COUNT(*) FROM root_candidate GROUP BY timeframe ORDER BY timeframe"
        )}
        by_scope_rows = [
            {
                "dataset_year": int(y),
                "symbol": str(s),
                "timeframe": str(tf),
                "root_month": str(m),
                "candidate_count": int(n),
            }
            for y, s, tf, m, n in con.execute(
                """
                SELECT dataset_year,symbol,timeframe,root_month,COUNT(*)
                FROM root_candidate
                GROUP BY dataset_year,symbol,timeframe,root_month
                ORDER BY dataset_year,symbol,timeframe,root_month
                """
            )
        ]
        fingerprint = logical_fingerprint(con)
        con.execute("INSERT INTO inventory_metadata(key,value) VALUES(?,?)", ("logical_sha256", fingerprint))
        con.execute("INSERT INTO inventory_metadata(key,value) VALUES(?,?)", ("semantic_registry_hash", str(defs["registry_hash"])))
        con.execute("INSERT INTO inventory_metadata(key,value) VALUES(?,?)", ("dependency_intake_report_hash", str(dep["report_hash"])))
        con.commit()
    finally:
        con.close()

    db_sha = sha256_file(a.inventory_db)
    db_bytes = a.inventory_db.stat().st_size
    elapsed_all = time.perf_counter() - started_all
    total_candidates = sum(int(x.get("candidate_count", 0)) for x in bench_sources)
    total_extract = sum(float(x.get("extraction_seconds", 0.0)) for x in bench_sources)
    total_decompress = sum(float(x.get("decompression_seconds", 0.0)) for x in bench_sources)
    all_expected_years = sorted({int(x["year"]) for x in source_identities["stage5"]}) == sorted(
        {int(x["year"]) for x in source_identities["stage7"]}
    )
    benchmark = {
        "format_version": 1,
        "group": 9,
        "scope": "REAL_ROOT_INVENTORY_EXTRACTION_BENCHMARK",
        "status": "PASS" if total_candidates > 0 and all_expected_years else "BLOCKED",
        "semantic_registry_hash": defs["registry_hash"],
        "dependency_intake_report_hash": dep["report_hash"],
        "candidate_count": total_candidates,
        "sources": bench_sources,
        "total_decompression_seconds": total_decompress,
        "total_extraction_seconds": total_extract,
        "total_elapsed_seconds": elapsed_all,
        "candidate_rows_per_extraction_second": total_candidates / max(total_extract, 1e-9),
        "inventory_db_bytes": db_bytes,
        "inventory_bytes_per_candidate": db_bytes / max(total_candidates, 1),
        "candidate_inventory_benchmark_pass": total_candidates > 0 and all_expected_years,
        "outcome_data_accessed": False,
        "trade_policy_accessed": False,
        "note": "This benchmark measures exact Group 9 root discovery/extraction only; it does not estimate full setup-state materialization runtime.",
    }
    benchmark["report_hash"] = stable(benchmark)
    atomic_json(a.benchmark_report, benchmark)

    report = {
        "format_version": 1,
        "group": 9,
        "scope": "REAL_EXACT_ROOT_CANDIDATE_INVENTORY",
        "status": "PASS",
        "exact_candidate_inventory": True,
        "semantic_registry_hash": defs["registry_hash"],
        "dependency_intake_report_hash": dep["report_hash"],
        "candidate_count": total_candidates,
        "counts_by_year": by_year,
        "counts_by_family": by_family,
        "counts_by_definition": by_definition,
        "counts_by_timeframe": by_tf,
        "scopes": by_scope_rows,
        "source_identities": source_identities,
        "inventory_db_path": str(a.inventory_db.resolve()),
        "inventory_db_bytes": db_bytes,
        "inventory_db_sha256": db_sha,
        "root_logical_sha256": fingerprint,
        "benchmark_report_hash": benchmark["report_hash"],
        "upstream_read_only": True,
        "outcome_data_accessed": False,
        "trade_policy_accessed": False,
    }
    report["report_hash"] = stable(report)
    atomic_json(a.inventory_report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({"benchmark": benchmark}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
