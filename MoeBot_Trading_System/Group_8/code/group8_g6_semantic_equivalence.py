#!/usr/bin/env python3
"""Prove semantic equivalence between two Group 6 annual SQLite databases.

Operational registries, checkpoints, audit timestamps, dependency-byte-derived internal IDs,
and record hashes are not market semantics. This comparator therefore checks:
- SQLite integrity and schema-column equality;
- source/year/config semantic equality;
- exact multiset equality of research payloads after excluding only Group6-internal IDs/hashes;
- external upstream references (Group2/3/5 IDs) remain in the projection and must match exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

G6_EXCLUDES: dict[str, list[str]] = {
    "displacement_legs": ["leg_id", "feature_hash", "record_hash"],
    "displacement_validation_events": ["validation_id", "leg_id", "fvg_id", "record_hash"],
    "fvg_events": ["fvg_id", "associated_leg_id", "feature_hash", "record_hash"],
    "fvg_lifecycle_summary": ["fvg_id", "record_hash"],
    "fvg_state_transitions": ["transition_id", "fvg_id", "record_hash"],
    "fvg_visit_observations": ["visit_id", "fvg_id", "record_hash"],
    "fvg_visit_reactions": ["reaction_id", "visit_id", "fvg_id", "record_hash"],
    "group6_evidence": ["evidence_id", "subject_id", "record_hash"],
    "imbalance_variants": ["variant_id", "record_hash"],
    "inversion_fvg_relations": ["inversion_id", "original_fvg_id", "record_hash"],
    "inversion_retest_observations": ["observation_id", "inversion_id", "original_fvg_id", "record_hash"],
    "liquidity_voids": ["void_id", "record_hash"],
    "liquidity_void_members": ["void_id", "member_id", "record_hash"],
    "liquidity_void_state_transitions": ["transition_id", "void_id", "record_hash"],
    "liquidity_void_lifecycle_summary": ["void_id", "record_hash"],
    "bpr_relations": ["bpr_id", "bullish_fvg_id", "bearish_fvg_id", "record_hash"],
    "bpr_state_transitions": ["transition_id", "bpr_id", "record_hash"],
    "bpr_lifecycle_summary": ["bpr_id", "record_hash"],
    "mtf_imbalance_relations": ["relation_id", "child_id", "parent_id", "record_hash"],
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def integrity(path: Path) -> dict[str, Any]:
    con = connect_ro(path)
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    full = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    con.close()
    return {"quick_check": quick, "integrity_check": full, "foreign_key_errors": len(fk), "tables": tables,
            "pass": quick == "ok" and full == "ok" and len(fk) == 0}


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in con.execute(f'PRAGMA table_info("{table}")')]


def semantic_counter(con: sqlite3.Connection, table: str, excluded: list[str]) -> tuple[list[str], Counter[str]]:
    cols = [c for c in columns(con, table) if c not in set(excluded)]
    if not cols:
        raise RuntimeError(f"no semantic columns for {table}")
    q = ",".join(f'"{c}"' for c in cols)
    counter: Counter[str] = Counter()
    for row in con.execute(f'SELECT {q} FROM "{table}"'):
        counter[canonical([row[c] for c in cols])] += 1
    return cols, counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--published", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    candidate = args.candidate.resolve(); published = args.published.resolve()
    if not candidate.is_file() or not published.is_file():
        raise FileNotFoundError("candidate and published Group 6 databases are required")
    ci = integrity(candidate); pi = integrity(published)
    if not ci["pass"] or not pi["pass"]:
        raise RuntimeError("SQLite integrity gate failed")

    cc = connect_ro(candidate); pc = connect_ro(published)
    c_tables=set(ci["tables"]); p_tables=set(pi["tables"])
    failures: list[str]=[]; results: dict[str,Any]={}
    for table, excluded in G6_EXCLUDES.items():
        if table not in c_tables or table not in p_tables:
            failures.append(f"missing_table:{table}")
            continue
        c_cols=columns(cc,table); p_cols=columns(pc,table); schema_equal=c_cols==p_cols
        c_sem_cols,c_counter=semantic_counter(cc,table,excluded)
        p_sem_cols,p_counter=semantic_counter(pc,table,excluded)
        semantic_cols_equal=c_sem_cols==p_sem_cols
        semantic_equal=semantic_cols_equal and c_counter==p_counter
        row={
          "excluded_internal_columns":excluded,
          "semantic_columns":c_sem_cols,
          "schema_columns_equal":schema_equal,
          "semantic_columns_equal":semantic_cols_equal,
          "candidate_count":sum(c_counter.values()),
          "published_count":sum(p_counter.values()),
          "candidate_semantic_digest":digest(sorted(c_counter.items())),
          "published_semantic_digest":digest(sorted(p_counter.items())),
          "sample_only_candidate":list((c_counter-p_counter).items())[:3],
          "sample_only_published":list((p_counter-c_counter).items())[:3],
          "semantic_equal":semantic_equal,
          "pass":schema_equal and semantic_equal,
        }
        results[table]=row
        if not row["pass"]: failures.append(f"semantic_table_mismatch:{table}")

    def rows(sql: str, con: sqlite3.Connection) -> list[dict[str,Any]]:
        return [dict(r) for r in con.execute(sql)]
    c_dataset=rows("SELECT year,source_sha256,symbol FROM dataset_registry ORDER BY year,source_sha256,symbol",cc)
    p_dataset=rows("SELECT year,source_sha256,symbol FROM dataset_registry ORDER BY year,source_sha256,symbol",pc)
    c_config=rows("SELECT engine_version,schema_version,config_json FROM config_registry ORDER BY engine_version,schema_version,config_json",cc)
    p_config=rows("SELECT engine_version,schema_version,config_json FROM config_registry ORDER BY engine_version,schema_version,config_json",pc)
    metadata_equal=c_dataset==p_dataset and c_config==p_config
    if not metadata_equal: failures.append("dataset_or_config_semantic_mismatch")
    cc.close(); pc.close()

    report={
      "format_version":2,
      "comparison_scope":"Group6 market/research semantics with only Group6-internal identity/hash fields excluded; external upstream references remain mandatory",
      "candidate":{"filename":candidate.name,"size_bytes":candidate.stat().st_size,"sha256":sha256_file(candidate),"sqlite":ci},
      "published":{"filename":published.name,"size_bytes":published.stat().st_size,"sha256":sha256_file(published),"sqlite":pi},
      "dataset_config_semantics_equal":metadata_equal,
      "core_tables":results,
      "failures":failures,
      "status":"PASS" if not failures else "FAIL",
    }
    report["report_hash"]=digest(report)
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":report["status"],"failures":failures,"report_hash":report["report_hash"],"tables":len(results)},indent=2))
    return 0 if not failures else 1

if __name__=="__main__": raise SystemExit(main())
