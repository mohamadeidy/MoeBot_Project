#!/usr/bin/env python3
"""Run one year of the real Group 8 design intake from the frozen coherent registry.

The helper verifies the public Groups 2-7 pack sequentially, leaves only tiny
categorical proxy SQLite files, restores only the canonical source database,
and emits compact schema/category evidence for Design Freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2023, 2024), required=True)
    parser.add_argument("--group8-root", type=Path, required=True)
    parser.add_argument("--data-vault-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    year = str(args.year)
    group8 = args.group8_root.resolve()
    data_vault = args.data_vault_root.resolve()
    work = args.work_dir.resolve()
    evidence = args.evidence_dir.resolve()
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(evidence, ignore_errors=True)
    work.mkdir(parents=True)
    evidence.mkdir(parents=True)

    registry_path = group8 / "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("status") != "PASS":
        raise RuntimeError("Annual dependency registry is not PASS")
    if set(registry.get("years", {})) != {"2023", "2024"}:
        raise RuntimeError("Annual dependency registry year set is invalid")

    annual = registry["years"][year]
    manifest = annual["manifest"]
    if manifest.get("status") != "PASS_PACKAGED" or int(manifest.get("year", 0)) != args.year:
        raise RuntimeError(f"Invalid coherent annual manifest for {year}")
    manifest_path = work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cleanroom_path = work / f"COHERENT_CLEANROOM_{year}.json"
    coherent_dir = work / "coherent"
    run([
        sys.executable,
        str(group8 / "code/group8_verify_coherent_v3_pack.py"),
        "--manifest", str(manifest_path),
        "--work-dir", str(coherent_dir),
        "--output", str(cleanroom_path),
    ])
    cleanroom = json.loads(cleanroom_path.read_text(encoding="utf-8"))
    expected_cleanroom_hash = annual["clean_room"]["report_hash"]
    if cleanroom.get("status") != "PASS" or cleanroom.get("report_hash") != expected_cleanroom_hash:
        raise RuntimeError(f"Coherent clean-room identity mismatch for {year}")

    source_entry = registry["source_databases"][year]
    data_vault_module = load_module(data_vault / "download_and_restore_databases.py", "group8_data_vault_restore")
    source_db = data_vault_module.restore(
        source_entry,
        work / "source-download",
        work / "source",
    )
    if source_db.name != source_entry["database_filename"]:
        raise RuntimeError(f"Restored source filename mismatch for {year}: {source_db.name}")

    source_schema_path = work / f"SOURCE_SCHEMA_{year}.json"
    run([
        sys.executable,
        str(group8 / "code/group8_real_schema_intake.py"),
        "--database", str(source_db),
        "--expected-sha256", source_entry["database_sha256"],
        "--expected-size", str(source_entry["database_size_bytes"]),
        "--year", year,
        "--output", str(source_schema_path),
    ])
    source_schema = json.loads(source_schema_path.read_text(encoding="utf-8"))
    if source_schema.get("status") != "pass":
        raise RuntimeError(f"Source schema intake failed for {year}")

    categorical_script = group8 / "code/group8_categorical_intake.py"
    categorical_reports: dict[str, str] = {}
    categorical_paths: list[Path] = []

    source_categories = work / f"CATEGORICAL_SOURCE_{year}.json"
    run([
        sys.executable, str(categorical_script),
        "--database", str(source_db),
        "--group", "source",
        "--year", year,
        "--output", str(source_categories),
    ])
    categorical_paths.append(source_categories)

    for group in ("group2", "group3", "group4", "group5", "group6", "group7"):
        proxy_db = coherent_dir / manifest["packages"][group]["database_filename"]
        if not proxy_db.is_file():
            raise FileNotFoundError(f"Missing verified categorical proxy for {group} {year}: {proxy_db}")
        output = work / f"CATEGORICAL_{group.upper()}_{year}.json"
        run([
            sys.executable, str(categorical_script),
            "--database", str(proxy_db),
            "--group", group,
            "--year", year,
            "--output", str(output),
        ])
        categorical_paths.append(output)

    for path in categorical_paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "PASS":
            raise RuntimeError(f"Categorical intake failed: {path}")
        categorical_reports[report["group"]] = report["report_hash"]
    if set(categorical_reports) != {"source", "group2", "group3", "group4", "group5", "group6", "group7"}:
        raise RuntimeError(f"Categorical report set incomplete for {year}: {sorted(categorical_reports)}")

    intake = {
        "format_version": 2,
        "status": "PASS",
        "year": args.year,
        "lineage": cleanroom["lineage"],
        "registry_hash": registry["registry_hash"],
        "coherent_cleanroom_hash": cleanroom["report_hash"],
        "source_schema_hash": source_schema["report_hash"],
        "categorical_report_hashes": dict(sorted(categorical_reports.items())),
        "source_only_restore": True,
        "disk_safe_categorical_proxies": True,
    }
    intake["report_hash"] = hashlib.sha256(canonical_json(intake).encode()).hexdigest()
    intake_path = work / f"REAL_DEPENDENCY_INTAKE_{year}.json"
    intake_path.write_text(json.dumps(intake, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    shutil.copy2(cleanroom_path, evidence / cleanroom_path.name)
    shutil.copy2(source_schema_path, evidence / source_schema_path.name)
    shutil.copy2(intake_path, evidence / intake_path.name)
    for path in categorical_paths:
        shutil.copy2(path, evidence / path.name)

    print(json.dumps({
        "status": "PASS",
        "year": args.year,
        "report_hash": intake["report_hash"],
        "categorical_groups": sorted(categorical_reports),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
