#!/usr/bin/env python3
"""Build a diagnostic-only Group 8 staging DB from exact relevant annual slices.

Only source, Group4 and Group6 payloads are restored from the frozen registry,
because load_bars, process_bounded_ranges and the Group6 breakout-cardinality
measurement do not read Groups2/3/5/7. Unused adapter tables are created as empty
schema stubs so the frozen Group8Engine contract check can initialize; they are
never read by the selected diagnostic stages. Every restored dependency is still
verified by exact filename/size/SHA and SQLite checks using the canonical
materializer helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_empty_adapter_table(dst: sqlite3.Connection, table: str, columns: list[str]) -> None:
    dst.execute(f"DROP TABLE IF EXISTS {q(table)}")
    dst.execute(f"CREATE TABLE {q(table)} ({', '.join(q(c) + ' TEXT' for c in columns)})")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    if a.year != 2023:
        raise SystemExit("partial diagnostic staging is intentionally 2023-only")

    root = a.group8_root.resolve()
    import sys
    sys.path.insert(0, str(root / "code"))
    import group8_materialize_inputs as canonical

    reg = json.loads((root / "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json").read_text())
    adapter = json.loads((root / "UPSTREAM_ADAPTER_MAP.json").read_text())
    freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text())
    year = str(a.year)
    if reg.get("status") != "PASS" or adapter.get("adapter_map_hash") != freeze.get("adapter_map_hash"):
        raise SystemExit("frozen registry/adapter identity invalid")

    records = {"source": reg["source_databases"][year]}
    records.update(reg["years"][year]["manifest"]["packages"])
    relevant = {"source", "group4", "group6"}
    identities = {
        group: {
            "filename": rec["database_filename"],
            "size_bytes": int(rec["database_size_bytes"]),
            "sha256": rec["database_sha256"],
            "engine_version": rec.get("engine_version"),
            "schema_version": rec.get("schema_version"),
            "config_id": rec.get("config_id"),
        }
        for group, rec in records.items()
    }

    a.work_dir.mkdir(parents=True, exist_ok=True)
    a.output_db.parent.mkdir(parents=True, exist_ok=True)
    a.output_db.unlink(missing_ok=True)
    dst = sqlite3.connect(a.output_db)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA synchronous=NORMAL")
    canonical.create_manifest(dst, {
        "status": "BUILDING",
        "year": year,
        "engine_version": canonical.ENGINE_VERSION,
        "schema_version": canonical.SCHEMA_VERSION,
        "config_id": canonical.CONFIG_ID,
        "logical_dependency_lineage_id": canonical.LOGICAL_LINEAGE,
        "adapter_map_hash": adapter["adapter_map_hash"],
    })

    table_counts: dict[str, int] = {}
    failures: list[str] = []
    try:
        for group in ["source", "group2", "group3", "group4", "group5", "group6", "group7"]:
            if group not in relevant:
                for logical, arec in adapter["adapters"][group].items():
                    dest = f"{group}__{logical}"
                    create_empty_adapter_table(dst, dest, list(arec["required_columns"]))
                    table_counts[dest] = 0
                dst.commit()
                continue

            rec = records[group]
            gw = a.work_dir / group
            gw.mkdir(parents=True, exist_ok=True)
            db = canonical.restore_record(rec, gw)
            src = canonical.verify_sqlite(db)
            try:
                for logical, arec in adapter["adapters"][group].items():
                    dest = f"{group}__{logical}"
                    table_counts[dest] = canonical.copy_table(src, dst, arec["table"], dest, list(arec["required_columns"]))
                if group == "source":
                    for key, value in canonical.metadata_increment_candidates(src).items():
                        dst.execute("INSERT OR REPLACE INTO staging_metadata(key,value) VALUES(?,?)", (key, value))
                    symbols = [r[0] for r in src.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol")]
                    if len(symbols) == 1:
                        dst.execute("INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)", ("symbol", symbols[0]))
            finally:
                src.close()
                db.unlink(missing_ok=True)
                shutil.rmtree(gw, ignore_errors=True)
            dst.commit()

        for key, value in {
            "status": "PASS",
            "database_identities_json": json.dumps(identities, sort_keys=True, separators=(",", ":")),
            "table_counts_json": json.dumps(table_counts, sort_keys=True, separators=(",", ":")),
        }.items():
            dst.execute("INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)", (key, value))
        dst.commit()
        qc = dst.execute("PRAGMA quick_check").fetchone()[0]
        ic = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if qc != "ok" or ic != "ok":
            failures.append(f"staging_sqlite:{qc}:{ic}")
    except Exception as exc:
        failures.append(f"{type(exc).__name__}:{exc}")
        dst.execute("INSERT OR REPLACE INTO stage_manifest(key,value) VALUES('status','FAIL')")
        dst.commit()
        qc = ic = "not_run"
    finally:
        dst.close()

    report = {
        "format_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "year": 2023,
        "scope": "DIAGNOSTIC_RELEVANT_SLICE_ONLY",
        "restored_exact_groups": sorted(relevant),
        "empty_schema_stub_groups": sorted(set(records) - relevant),
        "database_identities": identities,
        "table_counts": table_counts,
        "read_only_upstream": True,
        "restored_identity_verification": "canonical filename+size+sha256+quick_check+integrity_check+foreign_key_check",
        "quick_check": qc,
        "integrity_check": ic,
        "failures": failures,
    }
    report["report_hash"] = stable_hash(report)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
