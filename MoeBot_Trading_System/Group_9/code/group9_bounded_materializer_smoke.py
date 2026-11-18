#!/usr/bin/env python3
"""Bounded Group 9 materialization/parity smoke on EXISTING frozen sample.

Never writes upstream Group 8, benchmark, or support-index SQLite.
This is NOT an annual shard executor or permission to launch one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from group9_real_setup_benchmark import (
    init_sample_output, materialize_one, stable,
)
from group9_real_root_inventory import atomic_json, load_hashed

FAMILIES = (
    "G9_ICT_LIQUIDITY_DELIVERY",
    "G9_STRUCTURAL_PULLBACK_CONTINUATION",
    "G9_WYCKOFF_RANGE_RESOLUTION",
)
TABLES = ("setup_instance", "setup_component_evidence", "setup_transition")


def readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def select_references(reference: sqlite3.Connection, per_family: int) -> list[sqlite3.Row]:
    if per_family < 1 or per_family > 32:
        raise ValueError("per_family_outside_1_to_32")
    selected = []
    seen = set()
    for fam in FAMILIES:
        # The benchmark's complete sample is already known and frozen.
        # Use distinct states to verify materialization transitions, not to
        # select or optimize trading outcomes.
        states = [str(r[0]) for r in reference.execute(
            "SELECT DISTINCT current_state FROM setup_instance WHERE setup_family=? "
            "ORDER BY current_state", (fam,)
        )]
        if not states:
            raise ValueError("missing_family_in_reference:" + fam)
        for state in states:
            rows = reference.execute(
                "SELECT * FROM setup_instance WHERE setup_family=? AND current_state=? "
                "ORDER BY setup_id LIMIT ?", (fam, state, per_family)
            ).fetchall()
            for row in rows:
                if row["setup_id"] not in seen:
                    selected.append(row)
                    seen.add(row["setup_id"])
    if len(selected) > 128:
        raise ValueError("test_root_limit_exceeded")
    return selected


def rows_for_setup(c: sqlite3.Connection, table: str, setup_id: str) -> list:
    return [tuple(x) for x in c.execute(
        f"SELECT * FROM {table} WHERE setup_id=? ORDER BY 1", (setup_id,)
    )]


def run(*, idx_path: Path, reference_path: Path, schema_path: Path,
        inventory_report: Path, benchmark_report: Path, registry_path: Path,
        output_path: Path, report_path: Path, per_family: int) -> dict:
    inv = load_hashed(inventory_report)
    benchmark = load_hashed(benchmark_report)
    defs = load_hashed(registry_path, ("registry_hash",))
    if inv["report_hash"] != benchmark["inventory_report_hash"]:
        raise ValueError("benchmark_inventory_lineage_mismatch")
    if defs["registry_hash"] != benchmark["semantic_registry_hash"]:
        raise ValueError("semantic_registry_drift")
    if defs["status"] != "FROZEN" or defs["definition_version"] != "G9-SSI-1.0.0":
        raise ValueError("unapproved_frozen_definition")
    if idx_path.stat().st_size != int(benchmark["support_index_bytes"]):
        raise ValueError("support_index_size_drift")
    if reference_path.stat().st_size != int(benchmark["sample_output_bytes"]):
        raise ValueError("reference_sample_size_drift")
    if output_path.exists() or report_path.exists():
        raise FileExistsError("smoke_output_or_report_already_exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with closing(readonly(reference_path)) as ref, closing(readonly(idx_path)) as idx:
        selected = select_references(ref, per_family)
        if not selected:
            raise ValueError("no_reference_setups")
        out = init_sample_output(output_path, schema_path)
        try:
            out.execute("PRAGMA foreign_keys=ON")
            stats = defaultdict(lambda: {
                "roots": 0, "setup_rows": 0, "evidence_rows": 0,
                "transition_rows": 0, "logical_bytes": 0,
            })
            compared = defaultdict(int)
            for item in selected:
                root_key = str(item["root_subject_type"]) + ":" + str(item["root_subject_id"])
                sample = idx.execute(
                    "SELECT * FROM benchmark_sample WHERE root_key=?", (root_key,)
                ).fetchone()
                if sample is None:
                    raise ValueError("sample_root_missing:" + root_key)
                if (sample["setup_family"] != item["setup_family"]
                    or sample["source_id"] != item["root_subject_id"]):
                    raise ValueError("sample_root_mismatch:" + root_key)
                materialize_one(idx, out, sample, defs["definition_version"], stats)
                sid = str(item["setup_id"])
                for table in TABLES:
                    actual = rows_for_setup(out, table, sid)
                    expected = rows_for_setup(ref, table, sid)
                    if actual != expected:
                        raise ValueError("parity_mismatch:" + table + ":" + sid)
                    compared[table] += len(actual)
                if compared["setup_instance"] > 128:
                    raise ValueError("sample_hard_limit")
            out.commit()
            if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("quick_check_failed")
            fk = out.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                raise ValueError("foreign_key_check_failed")
            for table in TABLES:
                actual = int(out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if actual != compared[table]:
                    raise ValueError("unexpected_rows:" + table)
        finally:
            out.close()
    h = hashlib.sha256()
    with output_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    result = {
        "format_version": 1,
        "scope": "GROUP9_BOUNDED_MATERIALIZER_PARITY_SMOKE",
        "status": "PASS_SMALL_SAMPLE_PARITY_ONLY",
        "source_inventory_report_hash": inv["report_hash"],
        "source_benchmark_report_hash": benchmark["report_hash"],
        "definition_registry_hash": defs["registry_hash"],
        "sample_setup_count": len(selected),
        "actual_rows": dict(compared),
        "sample_state_counts": dict(sorted({
            state: sum(str(s["current_state"]) == state for s in selected)
            for state in {str(s["current_state"]) for s in selected}
        }.items())),
        "elapsed_seconds": time.perf_counter() - start,
        "output_bytes": output_path.stat().st_size,
        "output_sha256": h.hexdigest(),
        "output_path": str(output_path),
        "reference_rows_match_exactly": True,
        "foreign_key_check": "PASS",
        "quick_check": "PASS",
        "upstream_read_only": True,
        "actual_annual_shard_sizes_verified": False,
        "resume_verified": False,
        "union_verified": False,
        "real_annual_execution_authorized": False,
    }
    result["report_hash"] = stable(result)
    atomic_json(report_path, result)
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--support-index", type=Path, required=True)
    p.add_argument("--reference-sample", type=Path, required=True)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--inventory-report", type=Path, required=True)
    p.add_argument("--benchmark-report", type=Path, required=True)
    p.add_argument("--definitions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--per-family", type=int, default=4)
    a = p.parse_args()
    result = run(
        idx_path=a.support_index, reference_path=a.reference_sample,
        schema_path=a.schema, inventory_report=a.inventory_report,
        benchmark_report=a.benchmark_report, registry_path=a.definitions,
        output_path=a.output, report_path=a.report, per_family=a.per_family,
    )
    print(json.dumps({
        k: result[k] for k in (
            "status", "sample_setup_count", "actual_rows", "sample_state_counts",
            "elapsed_seconds", "output_bytes", "reference_rows_match_exactly",
            "real_annual_execution_authorized",
        )
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
