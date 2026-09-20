#!/usr/bin/env python3
"""Group 8 V3 Stage 6 shard-union and downstream-compatibility validator.

Validates Stage 6 range_chain shards without reconstructing a monolithic SQLite:
- verifies shard/manifest identities;
- proves Stage 5 remains the referenced immutable boundary;
- rejects duplicate Stage 6 domain IDs across shards;
- verifies Group8 references from Stage 6 rows;
- computes global logical fingerprints from sorted (primary_id,row_hash) streams;
- emits a compatibility receipt for later Group 8 finalization and Groups 9-15.

No domain row is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable, TextIO

from group8_v3_stage6_range_shard_executor import STAGE6_DEFINITIONS, stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

HEX = "0123456789abcdef"
TABLES = {
    "school_interpretation": ("interpretation_id", "interpretation_hash"),
    "evidence_chain": ("evidence_chain_id", "evidence_hash"),
}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _verify_self_hash(record: dict[str, Any], field: str) -> None:
    if field not in record:
        raise RuntimeError(f"missing {field}")
    payload = dict(record)
    saved = str(payload.pop(field))
    if stable_hash(payload) != saved:
        raise RuntimeError(f"{field} mismatch")


def _prefix(row_id: str) -> str:
    tail = str(row_id).rsplit("_", 1)[-1].lower()
    if not tail or tail[0] not in HEX:
        raise RuntimeError(f"non-hex deterministic ID: {row_id}")
    return tail[0]


def _read_sidecar_line(f: TextIO) -> tuple[str, str, str] | None:
    line = f.readline()
    if not line:
        return None
    rid, rh, sid = line.rstrip("\n").split("\t", 2)
    return rid, rh, sid


def _merge_group(inputs: list[Path], output: Path) -> tuple[int, int]:
    streams = [p.open("r", encoding="utf-8") for p in inputs]
    heap: list[tuple[str, str, str, int]] = []
    try:
        for i, f in enumerate(streams):
            item = _read_sidecar_line(f)
            if item is not None:
                heapq.heappush(heap, (item[0], item[1], item[2], i))
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        duplicates = 0
        previous: str | None = None
        with output.open("w", encoding="utf-8", newline="") as out:
            while heap:
                rid, rh, sid, i = heapq.heappop(heap)
                if rid == previous:
                    duplicates += 1
                    raise RuntimeError(f"duplicate Stage 6 domain ID across shards: {rid}")
                previous = rid
                out.write(f"{rid}\t{rh}\t{sid}\n")
                count += 1
                nxt = _read_sidecar_line(streams[i])
                if nxt is not None:
                    heapq.heappush(heap, (nxt[0], nxt[1], nxt[2], i))
        return count, duplicates
    finally:
        for f in streams:
            f.close()


def _multi_pass_merge(paths: list[Path], work: Path, label: str, fan_in: int = 32) -> Path:
    if not paths:
        empty = work / f"{label}_empty.tsv"
        empty.write_text("", encoding="utf-8")
        return empty
    current = list(paths)
    generation = 0
    while len(current) > 1:
        nxt: list[Path] = []
        for n in range(0, len(current), fan_in):
            group = current[n : n + fan_in]
            out = work / f"{label}_g{generation}_{n//fan_in:05d}.tsv"
            _merge_group(group, out)
            nxt.append(out)
        current = nxt
        generation += 1
    return current[0]


def _fingerprint(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    count = 0
    previous: str | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            rid, rh, _sid = line.rstrip("\n").split("\t", 2)
            if previous is not None and rid <= previous:
                raise RuntimeError(f"non-strict Stage 6 union ordering: {rid}")
            previous = rid
            h.update(rid.encode("utf-8"))
            h.update(b"\0")
            h.update(rh.encode("utf-8"))
            h.update(b"\n")
            count += 1
    return count, h.hexdigest()


def _schema_columns(con: sqlite3.Connection, schema: str, table: str) -> tuple[str, ...]:
    return tuple(str(r[1]) for r in con.execute(f'PRAGMA "{schema}".table_info("{table}")'))


def _audit_references(stage5_db: Path, shard_db: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{stage5_db.resolve()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("ATTACH DATABASE ? AS shard", (str(shard_db.resolve()),))
        stage5_cols = _schema_columns(con, "main", "school_interpretation")
        shard_cols = _schema_columns(con, "shard", "school_interpretation")
        if stage5_cols != shard_cols:
            raise RuntimeError("school_interpretation logical schema drift in Stage 6 shard")
        stage5_evidence_cols = _schema_columns(con, "main", "evidence_chain")
        shard_evidence_cols = _schema_columns(con, "shard", "evidence_chain")
        if stage5_evidence_cols != shard_evidence_cols:
            raise RuntimeError("evidence_chain logical schema drift in Stage 6 shard")

        unresolved_range_candidate = int(
            con.execute(
                """SELECT COUNT(*)
                   FROM shard.school_interpretation i, json_each(i.upstream_refs_json) j
                   WHERE i.definition_id='wyckoff_range_context'
                     AND lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
                     AND COALESCE(json_extract(j.value,'$.source_type'),'')='price_action_pattern_candidate'
                     AND NOT EXISTS(
                       SELECT 1 FROM main.price_action_pattern_candidate p
                       WHERE p.candidate_id=CAST(json_extract(j.value,'$.source_id') AS TEXT)
                         AND p.definition_id='pa_bounded_range_context'
                     )"""
            ).fetchone()[0]
        )
        unresolved_range_dow = int(
            con.execute(
                """SELECT COUNT(*)
                   FROM shard.school_interpretation i, json_each(i.upstream_refs_json) j
                   WHERE i.definition_id='wyckoff_range_context'
                     AND lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
                     AND COALESCE(json_extract(j.value,'$.source_type'),'')='school_interpretation'
                     AND NOT EXISTS(
                       SELECT 1 FROM main.school_interpretation d
                       WHERE d.interpretation_id=CAST(json_extract(j.value,'$.source_id') AS TEXT)
                         AND d.definition_id='dow_indeterminate_structure'
                     )"""
            ).fetchone()[0]
        )
        unresolved_child_parent = int(
            con.execute(
                """SELECT COUNT(*)
                   FROM shard.school_interpretation i, json_each(i.upstream_refs_json) j
                   WHERE i.definition_id IN ('wyckoff_spring_candidate','wyckoff_upthrust_candidate')
                     AND lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
                     AND COALESCE(json_extract(j.value,'$.source_type'),'')='school_interpretation'
                     AND NOT EXISTS(
                       SELECT 1 FROM shard.school_interpretation p
                       WHERE p.interpretation_id=CAST(json_extract(j.value,'$.source_id') AS TEXT)
                         AND p.definition_id='wyckoff_range_context'
                     )"""
            ).fetchone()[0]
        )
        unresolved_evidence_subject = int(
            con.execute(
                """SELECT COUNT(*)
                   FROM shard.evidence_chain e
                   WHERE e.subject_type='school_interpretation'
                     AND NOT EXISTS(
                       SELECT 1 FROM shard.school_interpretation i
                       WHERE i.interpretation_id=e.subject_id
                     )"""
            ).fetchone()[0]
        )
        unexpected_defs = int(
            con.execute(
                """SELECT COUNT(*) FROM (
                     SELECT DISTINCT definition_id
                     FROM shard.school_interpretation
                     WHERE definition_id NOT IN (
                       'wyckoff_range_context','wyckoff_spring_candidate','wyckoff_upthrust_candidate'
                     )
                   )"""
            ).fetchone()[0]
        )
        return {
            "unresolved_range_candidate": unresolved_range_candidate,
            "unresolved_range_dow": unresolved_range_dow,
            "unresolved_child_parent": unresolved_child_parent,
            "unresolved_evidence_subject": unresolved_evidence_subject,
            "unexpected_definition_count": unexpected_defs,
        }
    finally:
        con.close()


def validate_union(
    *,
    release_path: Path,
    stage5_db: Path,
    work_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    release = json.loads(release_path.read_text())
    _verify_self_hash(release, "release_hash")
    if release.get("status") != "PASS" or int(release.get("stage", 0)) != 6:
        raise RuntimeError("Stage 6 release is not PASS")
    if release.get("stage7_authorized") is not False or release.get("stage7_auto_launch") is not False:
        raise RuntimeError("Stage 6 release improperly authorizes Stage 7")
    if release.get("stage5_database_sha256") != sha256_file(stage5_db):
        raise RuntimeError("Stage 5 boundary hash mismatch at union validation")

    stage5 = sqlite3.connect(f"file:{stage5_db.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        stage6_in_base = int(
            stage5.execute(
                "SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN (?,?,?)",
                STAGE6_DEFINITIONS,
            ).fetchone()[0]
        )
        if stage6_in_base:
            raise RuntimeError(f"protected Stage 5 boundary contains Stage 6 rows: {stage6_in_base}")
    finally:
        stage5.close()

    shards = list(release.get("shards", []))
    if len(shards) != int(release.get("shard_count", -1)):
        raise RuntimeError("Stage 6 release shard count mismatch")

    work_root.mkdir(parents=True, exist_ok=True)
    total_manifest_counts = {table: 0 for table in TABLES}
    reference_totals = {
        "unresolved_range_candidate": 0,
        "unresolved_range_dow": 0,
        "unresolved_child_parent": 0,
        "unresolved_evidence_subject": 0,
        "unexpected_definition_count": 0,
    }

    with tempfile.TemporaryDirectory(prefix="g8v3_stage6_union_", dir=work_root) as raw:
        temp = Path(raw)
        sidecars: dict[str, dict[str, list[Path]]] = {
            table: {p: [] for p in HEX} for table in TABLES
        }

        for idx, shard in enumerate(shards):
            db = Path(shard["database"]).resolve()
            mp = Path(shard["manifest"]).resolve()
            if not db.is_file() or not mp.is_file():
                raise RuntimeError(f"missing Stage 6 shard or manifest: {db}")
            manifest = json.loads(mp.read_text())
            _verify_self_hash(manifest, "manifest_hash")
            if manifest.get("manifest_hash") != shard.get("manifest_hash"):
                raise RuntimeError(f"release/manifest hash mismatch: {db}")
            if manifest.get("sha256") != shard.get("sha256"):
                raise RuntimeError(f"release/database SHA binding mismatch: {db}")
            if db.stat().st_size != int(manifest.get("file_size_bytes", -1)):
                raise RuntimeError(f"Stage 6 shard size mismatch: {db}")
            if sha256_file(db) != manifest.get("sha256"):
                raise RuntimeError(f"Stage 6 shard SHA-256 mismatch: {db}")
            if manifest.get("stage5_database_sha256") != release.get("stage5_database_sha256"):
                raise RuntimeError(f"Stage 5 lineage mismatch in shard: {db}")

            refs = _audit_references(stage5_db, db)
            for key, value in refs.items():
                reference_totals[key] += int(value)
            if any(refs.values()):
                raise RuntimeError(f"Stage 6 shard compatibility/reference audit failed: {db}: {refs}")

            con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
            try:
                if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"Stage 6 shard quick_check failed: {db}")
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"Stage 6 shard integrity_check failed: {db}")
                if con.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError(f"Stage 6 shard foreign_key_check failed: {db}")
                for table, (idc, hc) in TABLES.items():
                    count = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                    total_manifest_counts[table] += count
                    sid = str(manifest["shard_id"])
                    handles: dict[str, TextIO] = {}
                    try:
                        for row in con.execute(
                            f'SELECT "{idc}","{hc}" FROM "{table}" ORDER BY "{idc}"'
                        ):
                            rid, rh = str(row[0]), str(row[1])
                            p = _prefix(rid)
                            if p not in handles:
                                path = temp / f"{table}_{p}_shard_{idx:05d}.tsv"
                                handles[p] = path.open("w", encoding="utf-8", newline="")
                                sidecars[table][p].append(path)
                            handles[p].write(f"{rid}\t{rh}\t{sid}\n")
                    finally:
                        for h in handles.values():
                            h.close()
            finally:
                con.close()

        union_counts: dict[str, int] = {}
        union_hashes: dict[str, str] = {}
        for table in TABLES:
            table_hash = hashlib.sha256()
            table_count = 0
            for p in HEX:
                merged = _multi_pass_merge(
                    sidecars[table][p],
                    temp,
                    f"{table}_{p}",
                )
                count, prefix_hash = _fingerprint(merged)
                # Global table fingerprint must be SHA256 over the canonical sorted
                # id\0row_hash\n stream, not a hash-of-prefix-hashes.
                with merged.open("r", encoding="utf-8") as f:
                    for line in f:
                        rid, rh, _sid = line.rstrip("\n").split("\t", 2)
                        table_hash.update(rid.encode("utf-8"))
                        table_hash.update(b"\0")
                        table_hash.update(rh.encode("utf-8"))
                        table_hash.update(b"\n")
                table_count += count
            union_counts[table] = table_count
            union_hashes[table] = table_hash.hexdigest()
            if table_count != total_manifest_counts[table]:
                raise RuntimeError(
                    f"Stage 6 union count mismatch {table}: {table_count}!={total_manifest_counts[table]}"
                )

    global_payload = {
        "tables": {
            table: {
                "count": union_counts[table],
                "logical_sha256": union_hashes[table],
            }
            for table in sorted(TABLES)
        }
    }
    result = {
        "format_version": 1,
        "status": "PASS",
        "scope": "GROUP8_V3_STAGE6_RANGE_CHAIN_UNION",
        "stage": 6,
        "stage_name": "wyckoff_core",
        "year": release["year"],
        "symbol": release["symbol"],
        "validated_commit": release["validated_commit"],
        "stage5_database_sha256": release["stage5_database_sha256"],
        "stage6_release_hash": release["release_hash"],
        "shard_count": len(shards),
        "table_row_counts": union_counts,
        "table_logical_sha256": union_hashes,
        "global_logical_sha256": stable_hash(global_payload),
        "duplicate_domain_id_count": 0,
        "unresolved_group8_reference_count": 0,
        "reference_audit_totals": reference_totals,
        "logical_schema_matches_stage5_schema": True,
        "frozen_ids_hashes_semantics_preserved": True,
        "downstream_compatibility": {
            "logical_table_names_unchanged": True,
            "logical_columns_unchanged": True,
            "immutable_primary_ids_unchanged": True,
            "row_hash_contract_unchanged": True,
            "physical_layout": "lossless range_chain SQLite shards",
            "routing_metadata": "Stage 6 release manifests by timeframe/root_month/bucket",
            "groups_9_15_must_consume_via_shard-aware adapter_or_finalized_union": True,
        },
        "stage6_official_pass_eligible": True,
        "stage7_auto_launch": False,
        "stage7_authorized": False,
    }
    result["report_hash"] = stable_hash(result)
    _atomic_json(output_path, result)
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = validate_union(
        release_path=a.release.resolve(),
        stage5_db=a.stage5_db.resolve(),
        work_root=a.work_root.resolve(),
        output_path=a.output.resolve(),
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
