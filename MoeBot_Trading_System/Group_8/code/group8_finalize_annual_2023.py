#!/usr/bin/env python3
"""Finalize a fully validated Group 8 2023 annual candidate and revoke execution pending OOS freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def shaf(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def semantic_annual(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "year": report.get("year"),
        "engine_version": report.get("engine_version"),
        "schema_version": report.get("schema_version"),
        "config_id": report.get("config_id"),
        "engine_build_manifest_hash": report.get("engine_build_manifest_hash"),
        "engine_sha256": report.get("engine_sha256"),
        "postprocessor_sha256": report.get("postprocessor_sha256"),
        "causality_errors": report.get("causality_errors"),
        "upstream_reference_integrity": report.get("upstream_reference_integrity"),
        "lifecycle": report.get("lifecycle"),
        "counts": report.get("counts"),
        "distributions": report.get("distributions"),
        "no_trading_outputs": report.get("no_trading_outputs"),
        "read_only_upstream": report.get("read_only_upstream"),
        "failures": report.get("failures"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--materializer-report", type=Path, required=True)
    p.add_argument("--engine-audit", type=Path, required=True)
    p.add_argument("--annual-initial", type=Path, required=True)
    p.add_argument("--annual-rerun", type=Path, required=True)
    p.add_argument("--annual-clean", type=Path, required=True)
    p.add_argument("--fingerprint-initial", type=Path, required=True)
    p.add_argument("--fingerprint-rerun", type=Path, required=True)
    p.add_argument("--fingerprint-clean", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--compressed-output", type=Path, required=True)
    p.add_argument("--validation-run-id", required=True)
    p.add_argument("--artifact-name", required=True)
    p.add_argument("--manifest-output", type=Path, required=True)
    a = p.parse_args()

    root = a.group8_root.resolve()
    status_path = root / "STATUS.json"
    status = load(status_path)
    build = load(root / "ENGINE_BUILD_MANIFEST.json")
    material = load(a.materializer_report)
    engine_audit = load(a.engine_audit)
    annuals = [load(a.annual_initial), load(a.annual_rerun), load(a.annual_clean)]
    fps = [load(a.fingerprint_initial), load(a.fingerprint_rerun), load(a.fingerprint_clean)]
    failures: list[str] = []

    if status.get("officially_closed") is not False: failures.append("group8_already_closed")
    if status.get("annual_execution_2023_authorized") is not True: failures.append("2023_not_authorized_before_validation")
    if status.get("annual_execution_2024_authorized") is not False: failures.append("2024_prematurely_authorized")
    if build.get("status") != "TECHNICAL_CANDIDATE_PASS" or build.get("annual_execution_2023_authorized") is not True or build.get("annual_execution_2024_authorized") is not False: failures.append("engine_build_authorization_invalid")
    if status.get("engine_build", {}).get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("status_build_manifest_mismatch")
    if material.get("status") != "PASS" or int(material.get("year", 0)) != 2023: failures.append("materializer_not_pass_2023")
    if engine_audit.get("status") != "PASS" or int(engine_audit.get("year", 0)) != 2023: failures.append("engine_audit_not_pass_2023")
    for idx, report in enumerate(annuals):
        if report.get("status") != "PASS" or int(report.get("year", 0)) != 2023 or report.get("failures"):
            failures.append(f"annual_validation_not_pass:{idx}")
    if not (semantic_annual(annuals[0]) == semantic_annual(annuals[1]) == semantic_annual(annuals[2])):
        failures.append("annual_semantic_reconstruction_drift")
    logical = [fp.get("logical_sha256") for fp in fps]
    table_hashes = [{k: v.get("logical_sha256") for k, v in fp.get("tables", {}).items()} for fp in fps]
    if len(set(logical)) != 1 or None in logical: failures.append("logical_fingerprint_drift")
    if not (table_hashes[0] == table_hashes[1] == table_hashes[2]): failures.append("table_fingerprint_drift")
    for idx, fp in enumerate(fps):
        if fp.get("status") != "PASS" or fp.get("quick_check") != "ok" or fp.get("integrity_check") != "ok" or fp.get("foreign_key_errors") != 0:
            failures.append(f"fingerprint_integrity:{idx}")
    if not a.output_db.is_file() or not a.compressed_output.is_file(): failures.append("annual_output_asset_missing")

    if failures:
        raise SystemExit(";".join(failures))

    database = {
        "filename": a.output_db.name,
        "size_bytes": a.output_db.stat().st_size,
        "sha256": shaf(a.output_db),
        "logical_sha256": logical[1],
    }
    compressed = {
        "filename": a.compressed_output.name,
        "size_bytes": a.compressed_output.stat().st_size,
        "sha256": shaf(a.compressed_output),
        "compression": "zstd -19 --long=31",
    }
    manifest = {
        "format_version": 1,
        "status": "ANNUAL_2023_PASS",
        "group": 8,
        "year": 2023,
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": build["config_id"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "engine_sha256": build["identities"]["engine"]["sha256"],
        "postprocessor_sha256": build["identities"]["postprocessor"]["sha256"],
        "materializer_sha256": build["identities"]["materializer"]["sha256"],
        "materializer_report_hash": material["report_hash"],
        "engine_audit_hash": engine_audit["report_hash"],
        "annual_validation_hash": annuals[1]["report_hash"],
        "clean_reconstruction_validation_hash": annuals[2]["report_hash"],
        "logical_fingerprint": logical[1],
        "fingerprint_report_hashes": [fp["report_hash"] for fp in fps],
        "database": database,
        "compressed_asset": compressed,
        "validation_run_id": str(a.validation_run_id),
        "artifact_name": a.artifact_name,
        "idempotence": "PASS",
        "clean_reconstruction": "PASS",
        "causality": "PASS",
        "no_lookahead": "PASS",
        "no_backdating": "PASS",
        "duplicate_prevention": "PASS",
        "upstream_reference_integrity": "PASS",
        "no_trading_outputs": True,
        "policy": "2023 engineering validation passed. Annual execution revoked until immutable pre-2024 OOS freeze binds this exact engine/config/2023 report identity.",
    }
    manifest["manifest_hash"] = hashlib.sha256(canonical(manifest)).hexdigest()
    a.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    a.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["annual_validation_2023"] = {
        "status": "PASS",
        "manifest_hash": manifest["manifest_hash"],
        "annual_validation_hash": manifest["annual_validation_hash"],
        "logical_fingerprint": manifest["logical_fingerprint"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "engine_sha256": manifest["engine_sha256"],
        "config_id": build["config_id"],
    }
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["status"] = "ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": manifest["status"], "manifest_hash": manifest["manifest_hash"], "logical_fingerprint": manifest["logical_fingerprint"], "database": database, "compressed_asset": compressed}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
