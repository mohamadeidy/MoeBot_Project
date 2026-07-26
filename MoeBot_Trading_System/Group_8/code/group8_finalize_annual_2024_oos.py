#!/usr/bin/env python3
"""Finalize the frozen Group 8 2024 OOS annual candidate.

Requires the immutable pre-2024 OOS freeze, proves no frozen identity changed,
requires deterministic rerun/clean reconstruction, and revokes all annual
execution after OOS completion pending cross-year/final closure.
"""
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


def semantic(report: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status", "year", "engine_version", "schema_version", "config_id",
        "engine_build_manifest_hash", "engine_sha256", "postprocessor_sha256",
        "causality_errors", "upstream_reference_integrity", "lifecycle",
        "counts", "distributions", "no_trading_outputs", "read_only_upstream", "failures",
    ]
    return {k: report.get(k) for k in keys}


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
    freeze = load(root / "OOS_FREEZE_MANIFEST.json")
    annual23 = load(root / "ANNUAL_2023_VALIDATION_MANIFEST.json")
    material = load(a.materializer_report)
    engine_audit = load(a.engine_audit)
    annuals = [load(a.annual_initial), load(a.annual_rerun), load(a.annual_clean)]
    fps = [load(a.fingerprint_initial), load(a.fingerprint_rerun), load(a.fingerprint_clean)]
    failures: list[str] = []

    if status.get("officially_closed") is not False: failures.append("group8_already_closed")
    if status.get("status") != "OOS_2024_FROZEN_AND_AUTHORIZED": failures.append("wrong_oos_phase")
    if status.get("annual_execution_2024_authorized") is not True: failures.append("2024_oos_not_authorized")
    if status.get("annual_execution_2023_authorized") is not False: failures.append("2023_reauthorized_illegally")
    if freeze.get("status") != "FROZEN_FOR_2024_OOS": failures.append("oos_freeze_not_frozen")
    if freeze.get("annual_2023_manifest_hash") != annual23.get("manifest_hash"): failures.append("oos_2023_identity_mismatch")
    if freeze.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("oos_build_identity_mismatch")
    if freeze.get("engine_sha256") != build.get("identities", {}).get("engine", {}).get("sha256"): failures.append("oos_engine_identity_mismatch")
    if freeze.get("config_id") != build.get("config_id"): failures.append("oos_config_identity_mismatch")
    if material.get("status") != "PASS" or int(material.get("year", 0)) != 2024: failures.append("materializer_not_pass_2024")
    if engine_audit.get("status") != "PASS" or int(engine_audit.get("year", 0)) != 2024: failures.append("engine_audit_not_pass_2024")
    if material.get("config_id") != freeze.get("config_id") or engine_audit.get("config_id") != freeze.get("config_id"): failures.append("2024_config_drift")

    for rel, rec in freeze.get("identities", {}).items():
        pth = root / rel
        if not pth.is_file(): failures.append(f"frozen_identity_missing:{rel}"); continue
        if pth.stat().st_size != int(rec["size_bytes"]): failures.append(f"frozen_identity_size_drift:{rel}")
        if shaf(pth) != rec["sha256"]: failures.append(f"frozen_identity_sha_drift:{rel}")

    for idx, report in enumerate(annuals):
        if report.get("status") != "PASS" or int(report.get("year", 0)) != 2024 or report.get("failures"):
            failures.append(f"annual_oos_validation_not_pass:{idx}")
        if report.get("engine_build_manifest_hash") != build.get("manifest_hash"):
            failures.append(f"annual_oos_build_drift:{idx}")
        if report.get("engine_sha256") != freeze.get("engine_sha256"):
            failures.append(f"annual_oos_engine_drift:{idx}")
        if report.get("config_id") != freeze.get("config_id"):
            failures.append(f"annual_oos_config_drift:{idx}")
    if not (semantic(annuals[0]) == semantic(annuals[1]) == semantic(annuals[2])):
        failures.append("oos_semantic_reconstruction_drift")

    logical = [fp.get("logical_sha256") for fp in fps]
    table_hashes = [{k: v.get("logical_sha256") for k, v in fp.get("tables", {}).items()} for fp in fps]
    if len(set(logical)) != 1 or None in logical: failures.append("oos_logical_fingerprint_drift")
    if not (table_hashes[0] == table_hashes[1] == table_hashes[2]): failures.append("oos_table_fingerprint_drift")
    for idx, fp in enumerate(fps):
        if fp.get("status") != "PASS" or fp.get("quick_check") != "ok" or fp.get("integrity_check") != "ok" or fp.get("foreign_key_errors") != 0:
            failures.append(f"oos_fingerprint_integrity:{idx}")
    if not a.output_db.is_file() or not a.compressed_output.is_file(): failures.append("oos_output_asset_missing")

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
        "status": "ANNUAL_2024_OOS_PASS",
        "group": 8,
        "year": 2024,
        "oos": True,
        "engine_version": build["engine_version"],
        "schema_version": build["schema_version"],
        "config_id": build["config_id"],
        "oos_freeze_manifest_hash": freeze["manifest_hash"],
        "engine_build_manifest_hash": build["manifest_hash"],
        "annual_2023_manifest_hash": annual23["manifest_hash"],
        "engine_sha256": freeze["engine_sha256"],
        "postprocessor_sha256": freeze["postprocessor_sha256"],
        "materializer_sha256": freeze["materializer_sha256"],
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
        "frozen_identity_drift": False,
        "policy": "2024 frozen OOS evaluation passed with no post-2023 identity mutation. All annual execution revoked pending cross-year and final closure verification.",
    }
    manifest["manifest_hash"] = hashlib.sha256(canonical(manifest)).hexdigest()
    a.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    a.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    status["annual_validation_2024_oos"] = {
        "status": "PASS",
        "manifest_hash": manifest["manifest_hash"],
        "annual_validation_hash": manifest["annual_validation_hash"],
        "logical_fingerprint": manifest["logical_fingerprint"],
        "oos_freeze_manifest_hash": freeze["manifest_hash"],
        "engine_sha256": manifest["engine_sha256"],
        "config_id": build["config_id"],
    }
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["status"] = "ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": manifest["status"], "manifest_hash": manifest["manifest_hash"], "logical_fingerprint": manifest["logical_fingerprint"], "frozen_identity_drift": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
