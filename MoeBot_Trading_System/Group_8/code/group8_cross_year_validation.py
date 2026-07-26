#!/usr/bin/env python3
"""Independent cross-year validation for MoeBot Group 8 after frozen 2024 OOS.

This is descriptive validation, not calibration: distribution differences are
recorded but never used to retune thresholds or prefer schools/setups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def ratio(a: int, b: int) -> float | None:
    return None if a == 0 else b / a


def flatten_counts(d: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in d.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            pass
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group8-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.group8_root.resolve()
    status = load(root / "STATUS.json")
    build = load(root / "ENGINE_BUILD_MANIFEST.json")
    freeze = load(root / "OOS_FREEZE_MANIFEST.json")
    a23 = load(root / "ANNUAL_2023_VALIDATION_MANIFEST.json")
    a24 = load(root / "ANNUAL_2024_OOS_VALIDATION_MANIFEST.json")
    v23 = load(root / "reports/32_ANNUAL_2023_VALIDATION.json")
    v24 = load(root / "reports/42_ANNUAL_2024_OOS_VALIDATION.json")
    failures: list[str] = []

    if status.get("status") != "ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED": failures.append("wrong_cross_year_phase")
    if status.get("annual_execution_authorized") or status.get("annual_execution_2023_authorized") or status.get("annual_execution_2024_authorized"):
        failures.append("annual_execution_not_revoked")
    if a23.get("status") != "ANNUAL_2023_PASS": failures.append("2023_not_pass")
    if a24.get("status") != "ANNUAL_2024_OOS_PASS": failures.append("2024_oos_not_pass")
    if freeze.get("status") != "FROZEN_FOR_2024_OOS": failures.append("oos_freeze_not_frozen")
    if a24.get("oos_freeze_manifest_hash") != freeze.get("manifest_hash"): failures.append("2024_oos_freeze_hash_mismatch")
    if freeze.get("annual_2023_manifest_hash") != a23.get("manifest_hash"): failures.append("freeze_2023_manifest_hash_mismatch")

    identity_keys = ["engine_version", "schema_version", "config_id", "engine_build_manifest_hash", "engine_sha256", "postprocessor_sha256", "materializer_sha256"]
    identity_comparison: dict[str, Any] = {}
    for k in identity_keys:
        left, right = a23.get(k), a24.get(k)
        identity_comparison[k] = {"2023": left, "2024": right, "equal": left == right}
        if left != right: failures.append(f"cross_year_identity_drift:{k}")
    if a23.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("2023_build_hash_drift")
    if a24.get("engine_build_manifest_hash") != build.get("manifest_hash"): failures.append("2024_build_hash_drift")

    for label, report in (("2023", v23), ("2024", v24)):
        if report.get("status") != "PASS" or report.get("failures"): failures.append(f"{label}_annual_report_not_pass")
        if report.get("no_trading_outputs") is not True: failures.append(f"{label}_trading_output_violation")
        if report.get("read_only_upstream") is not True: failures.append(f"{label}_upstream_not_read_only")
        if any(int(x) != 0 for x in report.get("causality_errors", {}).values()): failures.append(f"{label}_causality_errors")
        refs = report.get("upstream_reference_integrity", {})
        if int(refs.get("unresolved_group8", 0)) or int(refs.get("unresolved_upstream", 0)) or refs.get("unknown_source_types"):
            failures.append(f"{label}_reference_integrity")
        life = report.get("lifecycle", {})
        if int(life.get("hypotheses", 0)) != int(life.get("initial", -1)) or int(life.get("hypotheses", 0)) != int(life.get("terminal", -1)) or int(life.get("before_creation", 0)) != 0:
            failures.append(f"{label}_lifecycle_integrity")

    c23 = flatten_counts(v23.get("counts", {})); c24 = flatten_counts(v24.get("counts", {}))
    tables = sorted(set(c23) | set(c24))
    count_comparison = {t: {"2023": c23.get(t, 0), "2024": c24.get(t, 0), "ratio_2024_to_2023": ratio(c23.get(t, 0), c24.get(t, 0))} for t in tables}

    distribution_comparison: dict[str, Any] = {}
    d23 = v23.get("distributions", {}); d24 = v24.get("distributions", {})
    for name in sorted(set(d23) | set(d24)):
        left = flatten_counts(d23.get(name, {})); right = flatten_counts(d24.get(name, {})); keys = sorted(set(left) | set(right))
        distribution_comparison[name] = {
            k: {"2023": left.get(k, 0), "2024": right.get(k, 0), "ratio_2024_to_2023": ratio(left.get(k, 0), right.get(k, 0))}
            for k in keys
        }

    report = {
        "format_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "group": 8,
        "phase": "CROSS_YEAR_VALIDATION",
        "years": [2023, 2024],
        "2024_is_frozen_oos": True,
        "engine_build_manifest_hash": build.get("manifest_hash"),
        "oos_freeze_manifest_hash": freeze.get("manifest_hash"),
        "annual_2023_manifest_hash": a23.get("manifest_hash"),
        "annual_2024_oos_manifest_hash": a24.get("manifest_hash"),
        "identity_comparison": identity_comparison,
        "counts": count_comparison,
        "distributions": distribution_comparison,
        "distribution_policy": "Observed descriptively only. No pass/fail threshold, calibration, retuning, preferred school, or trading preference is derived from cross-year frequency differences.",
        "no_trading_outputs_both_years": v23.get("no_trading_outputs") is True and v24.get("no_trading_outputs") is True,
        "read_only_upstream_both_years": v23.get("read_only_upstream") is True and v24.get("read_only_upstream") is True,
        "identity_stable_across_oos_boundary": all(x["equal"] for x in identity_comparison.values()),
        "failures": failures,
    }
    report["report_hash"] = hashlib.sha256(canonical(report)).hexdigest()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "report_hash": report["report_hash"], "identity_stable": report["identity_stable_across_oos_boundary"], "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
