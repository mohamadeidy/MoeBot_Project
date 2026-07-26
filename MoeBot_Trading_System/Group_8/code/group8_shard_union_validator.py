#!/usr/bin/env python3
"""Validate a lossless Group 8 shard set without rebuilding a monolithic DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

DOMAIN_TABLES = {
    "price_action_pattern_candidate": ("candidate_id", "candidate_hash"),
    "price_action_pattern_state": ("state_event_id", "state_hash"),
    "school_interpretation": ("interpretation_id", "interpretation_hash"),
    "shared_evidence": ("shared_evidence_id", "shared_evidence_hash"),
    "conflicting_evidence": ("conflict_id", "conflict_hash"),
    "narrative_hypothesis": ("hypothesis_id", "hypothesis_hash"),
    "hypothesis_lifecycle_event": ("lifecycle_event_id", "lifecycle_hash"),
    "multi_timeframe_context_relation": ("relation_id", "relation_hash"),
    "evidence_chain": ("evidence_chain_id", "evidence_hash"),
    "invalidation_record": ("invalidation_id", "invalidation_hash"),
}
REGISTRY_TABLES = {
    "config_registry": ("config_id", "config_hash"),
    "school_registry": ("school_id", "school_hash"),
    "pattern_definition_registry": ("definition_id", "definition_hash"),
    "interpretation_definition_registry": ("definition_id", "definition_hash"),
    "dataset_registry": ("dataset_id", "record_hash"),
    "dependency_registry": ("dependency_id", "record_hash"),
}
GROUP8_REF_COLUMNS = {
    "price_action_pattern_candidate": ("upstream_refs_json",),
    "school_interpretation": ("upstream_refs_json",),
    "narrative_hypothesis": ("upstream_refs_json",),
}
EXPECTED_CONTRACT = "d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a"
EXPECTED_FREEZE = "213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a"
EXPECTED_ENGINE = "ab674be7601aed36d4d9e83eaedf7a1855f8e86297f7e9fc50ba01a9200dd4a0"


def canonical_json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def stable_hash(v: Any) -> str:
    return hashlib.sha256(canonical_json(v).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _json_refs(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    parsed = json.loads(value)
    return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []


def validate(index_path: Path, output_path: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text())
    pairs = index.get("shards")
    if not isinstance(pairs, list) or not pairs:
        raise RuntimeError("shard index contains no shards")
    expected_year = int(index["year"])
    expected_symbol = str(index["symbol"])
    if expected_year == 2024 and index.get("oos_2024_authorized") is not True:
        raise RuntimeError("2024 union validation requires explicit OOS authorization in index")

    with tempfile.TemporaryDirectory() as td:
        catalog_path = Path(td) / "catalog.sqlite"
        cat = sqlite3.connect(catalog_path)
        cat.execute("PRAGMA journal_mode=OFF")
        cat.execute("PRAGMA synchronous=OFF")
        cat.execute("CREATE TABLE domain(table_name TEXT NOT NULL,row_id TEXT NOT NULL,row_hash TEXT NOT NULL,shard_id TEXT NOT NULL,PRIMARY KEY(table_name,row_id)) WITHOUT ROWID")
        cat.execute("CREATE TABLE registry(table_name TEXT NOT NULL,row_id TEXT NOT NULL,row_hash TEXT NOT NULL,PRIMARY KEY(table_name,row_id)) WITHOUT ROWID")
        cat.execute("CREATE TABLE refs(source_table TEXT NOT NULL,source_id TEXT NOT NULL,target_type TEXT NOT NULL,target_id TEXT NOT NULL,shard_id TEXT NOT NULL)")
        manifests: list[dict[str, Any]] = []
        total_bytes = 0
        duplicate_errors: list[dict[str, Any]] = []
        registry_conflicts: list[dict[str, Any]] = []

        for item in pairs:
            db = Path(item["database"]).resolve(); mp = Path(item["manifest"]).resolve()
            m = json.loads(mp.read_text()); payload = dict(m); saved = payload.pop("manifest_hash", None)
            if saved != stable_hash(payload):
                raise RuntimeError(f"manifest self-hash mismatch: {mp}")
            for key, expected in (("year", expected_year), ("symbol", expected_symbol), ("storage_contract_hash", EXPECTED_CONTRACT), ("design_freeze_hash", EXPECTED_FREEZE), ("engine_sha256", EXPECTED_ENGINE)):
                if m.get(key) != expected:
                    raise RuntimeError(f"manifest identity mismatch {key}: {mp}")
            if sha256_file(db) != m.get("sha256") or db.stat().st_size != int(m.get("file_size_bytes", -1)):
                raise RuntimeError(f"shard file identity mismatch: {db}")
            con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True); con.row_factory = sqlite3.Row
            try:
                if con.execute("PRAGMA quick_check").fetchone()[0] != "ok" or con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"sqlite check failed: {db}")
                if con.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError(f"foreign-key errors: {db}")
                existing_tables = _tables(con)
                for table, (id_col, hash_col) in DOMAIN_TABLES.items():
                    if table not in existing_tables:
                        continue
                    for row_id, row_hash in con.execute(f'SELECT "{id_col}","{hash_col}" FROM "{table}"'):
                        try:
                            cat.execute("INSERT INTO domain VALUES(?,?,?,?)", (table, str(row_id), str(row_hash), m["shard_id"]))
                        except sqlite3.IntegrityError:
                            prev = cat.execute("SELECT row_hash,shard_id FROM domain WHERE table_name=? AND row_id=?", (table, str(row_id))).fetchone()
                            duplicate_errors.append({"table": table, "row_id": str(row_id), "existing_hash": prev[0], "new_hash": str(row_hash), "existing_shard": prev[1], "new_shard": m["shard_id"]})
                    for ref_col in GROUP8_REF_COLUMNS.get(table, ()): 
                        cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
                        if ref_col not in cols:
                            continue
                        for source_id, refs_json in con.execute(f'SELECT "{id_col}","{ref_col}" FROM "{table}"'):
                            for ref in _json_refs(refs_json):
                                if str(ref.get("source_group", "")).lower() != "group8":
                                    continue
                                st = str(ref.get("source_type") or "")
                                target = str(ref.get("source_id") or "")
                                if target:
                                    cat.execute("INSERT INTO refs VALUES(?,?,?,?,?)", (table, str(source_id), st, target, m["shard_id"]))
                for table, (id_col, hash_col) in REGISTRY_TABLES.items():
                    if table not in existing_tables:
                        continue
                    for row_id, row_hash in con.execute(f'SELECT "{id_col}","{hash_col}" FROM "{table}"'):
                        prev = cat.execute("SELECT row_hash FROM registry WHERE table_name=? AND row_id=?", (table, str(row_id))).fetchone()
                        if prev is None:
                            cat.execute("INSERT INTO registry VALUES(?,?,?)", (table, str(row_id), str(row_hash)))
                        elif prev[0] != str(row_hash):
                            registry_conflicts.append({"table": table, "row_id": str(row_id), "existing_hash": prev[0], "new_hash": str(row_hash)})
            finally:
                con.close()
            total_bytes += db.stat().st_size; manifests.append(m); cat.commit()

        if duplicate_errors:
            raise RuntimeError(f"duplicate domain IDs across shards: {duplicate_errors[:5]}")
        if registry_conflicts:
            raise RuntimeError(f"registry conflicts across shards: {registry_conflicts[:5]}")

        # Map source_type names used in refs to domain tables.
        known_ids: set[str] = {r[0] for r in cat.execute("SELECT row_id FROM domain")}
        unresolved: list[dict[str, str]] = []
        for source_table, source_id, target_type, target_id, shard_id in cat.execute("SELECT source_table,source_id,target_type,target_id,shard_id FROM refs"):
            if target_id not in known_ids:
                unresolved.append({"source_table": source_table, "source_id": source_id, "target_type": target_type, "target_id": target_id, "shard_id": shard_id})
        # It is valid for a partial-family validation to reference Group8 records
        # outside this index. Full annual index must require complete resolution.
        full_annual = bool(index.get("full_annual_union", False))
        if full_annual and unresolved:
            raise RuntimeError(f"unresolved cross-shard Group8 refs: {unresolved[:5]}")

        table_counts: dict[str, int] = {}
        table_hashes: dict[str, str] = {}
        for table in DOMAIN_TABLES:
            count = cat.execute("SELECT COUNT(*) FROM domain WHERE table_name=?", (table,)).fetchone()[0]
            if not count:
                continue
            h = hashlib.sha256()
            for row_id, row_hash in cat.execute("SELECT row_id,row_hash FROM domain WHERE table_name=? ORDER BY row_id", (table,)):
                h.update(str(row_id).encode()); h.update(b"\0"); h.update(str(row_hash).encode()); h.update(b"\n")
            table_counts[table] = int(count); table_hashes[table] = h.hexdigest()
        global_payload = {"tables": {t: {"count": table_counts[t], "logical_sha256": table_hashes[t]} for t in sorted(table_counts)}}
        global_logical = stable_hash(global_payload)

    report = {
        "format_version": 1, "status": "PASS", "year": expected_year, "symbol": expected_symbol,
        "full_annual_union": bool(index.get("full_annual_union", False)), "shard_count": len(manifests), "total_shard_bytes": total_bytes,
        "storage_contract_hash": EXPECTED_CONTRACT, "design_freeze_hash": EXPECTED_FREEZE, "engine_sha256": EXPECTED_ENGINE,
        "table_row_counts": table_counts, "table_logical_sha256": table_hashes, "global_logical_sha256": global_logical,
        "unresolved_group8_reference_count": len(unresolved), "unresolved_group8_reference_sample": unresolved[:20],
        "duplicate_domain_id_count": 0, "registry_conflict_count": 0,
        "oos_2024_accessed": expected_year == 2024,
    }
    report["report_hash"] = stable_hash(report); output_path.parent.mkdir(parents=True, exist_ok=True); output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--index", type=Path, required=True); p.add_argument("--output", type=Path, required=True); a = p.parse_args()
    print(json.dumps(validate(a.index.resolve(), a.output.resolve()), indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
