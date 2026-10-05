#!/usr/bin/env python3
"""Publish Group 8 Checkpoint 3 from final V3 closure evidence.

Checkpoint 3 is a post-closure authorization gate for Group 9. It does not
recompute or alter Group 8 semantics. It verifies the final closure/handoff
chain, both annual manifests, cross-year validation, and Stage 6/7 union
evidence for 2023 and 2024, then emits a compact self-hashed PASS artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def load_hashed(path: Path, field: str) -> dict[str, Any]:
    rec = json.loads(path.read_text())
    if field not in rec:
        raise RuntimeError(f"{path.name}:missing_{field}")
    check = dict(rec)
    saved = str(check.pop(field))
    if stable(check) != saved:
        raise RuntimeError(f"{path.name}:{field}_mismatch")
    return rec


def publish(
    *,
    closure_path: Path,
    handoff_path: Path,
    annual23_path: Path,
    annual24_path: Path,
    cross_path: Path,
    stage6_2023_union_path: Path,
    stage7_2023_union_path: Path,
    stage6_2024_union_path: Path,
    stage7_2024_union_path: Path,
    explicit_approval: bool,
    output: Path,
) -> dict[str, Any]:
    if not explicit_approval:
        raise RuntimeError("explicit user approval required to publish Checkpoint 3")

    closure = load_hashed(closure_path, "closure_hash")
    handoff = load_hashed(handoff_path, "manifest_hash")
    annual23 = load_hashed(annual23_path, "manifest_hash")
    annual24 = load_hashed(annual24_path, "manifest_hash")
    cross = load_hashed(cross_path, "report_hash")
    s6_23 = load_hashed(stage6_2023_union_path, "report_hash")
    s7_23 = load_hashed(stage7_2023_union_path, "report_hash")
    s6_24 = load_hashed(stage6_2024_union_path, "report_hash")
    s7_24 = load_hashed(stage7_2024_union_path, "report_hash")

    failures: list[str] = []

    if closure.get("status") != "OFFICIALLY_CLOSED_V3" or closure.get("officially_closed") is not True:
        failures.append("group8_not_officially_closed_v3")
    if closure.get("group9_authorized") is not True:
        failures.append("group9_not_authorized_by_group8_closure")

    if handoff.get("status") != "FROZEN_HANDOFF":
        failures.append("group8_handoff_not_frozen")
    if handoff.get("source_group") != 8 or int(handoff.get("target_group", -1)) != 9:
        failures.append("group8_handoff_wrong_route")
    if handoff.get("closure_hash") != closure.get("closure_hash"):
        failures.append("handoff_closure_hash_mismatch")
    if handoff.get("consumption_policy", {}).get("read_only") is not True:
        failures.append("handoff_not_read_only")

    if annual23.get("status") != "ANNUAL_2023_PASS":
        failures.append("annual_2023_not_pass")
    if annual24.get("status") != "ANNUAL_2024_OOS_PASS":
        failures.append("annual_2024_oos_not_pass")
    if cross.get("status") != "PASS":
        failures.append("cross_year_not_pass")
    if cross.get("identity_stable_across_oos_boundary") is not True:
        failures.append("cross_year_identity_not_stable")
    if cross.get("frozen_semantics_stable") is not True:
        failures.append("cross_year_semantics_not_stable")

    if closure.get("annual_2023_manifest_hash") != annual23.get("manifest_hash"):
        failures.append("closure_annual_2023_hash_mismatch")
    if closure.get("annual_2024_oos_manifest_hash") != annual24.get("manifest_hash"):
        failures.append("closure_annual_2024_hash_mismatch")
    if closure.get("cross_year_report_hash") != cross.get("report_hash"):
        failures.append("closure_cross_year_hash_mismatch")
    if handoff.get("annual_2023_manifest_hash") != annual23.get("manifest_hash"):
        failures.append("handoff_annual_2023_hash_mismatch")
    if handoff.get("annual_2024_oos_manifest_hash") != annual24.get("manifest_hash"):
        failures.append("handoff_annual_2024_hash_mismatch")
    if handoff.get("cross_year_report_hash") != cross.get("report_hash"):
        failures.append("handoff_cross_year_hash_mismatch")

    unions = {
        "stage6_2023": s6_23,
        "stage7_2023": s7_23,
        "stage6_2024": s6_24,
        "stage7_2024": s7_24,
    }
    for label, rec in unions.items():
        if rec.get("status") != "PASS":
            failures.append(f"{label}_union_not_pass")
        if int(rec.get("duplicate_domain_id_count", -1)) != 0:
            failures.append(f"{label}_duplicate_ids")
        if int(rec.get("unresolved_local_evidence_subject_count", 0)) != 0:
            failures.append(f"{label}_unresolved_local_evidence")

    if closure.get("validated_commit") != handoff.get("validated_commit"):
        failures.append("validated_commit_drift")
    if closure.get("oos_tooling_commit") != handoff.get("oos_tooling_commit"):
        failures.append("oos_tooling_commit_drift")

    result = {
        "format_version": 1,
        "checkpoint": 3,
        "status": "PASS" if not failures else "BLOCKED",
        "group": 8,
        "next_group": 9,
        "explicit_publication_approval": True,
        "officially_closed": closure.get("officially_closed") is True,
        "group9_authorized": closure.get("group9_authorized") is True,
        "validated_commit": closure.get("validated_commit"),
        "oos_tooling_commit": closure.get("oos_tooling_commit"),
        "group8_closure_hash": closure.get("closure_hash"),
        "group8_handoff_manifest_hash": handoff.get("manifest_hash"),
        "annual_2023_manifest_hash": annual23.get("manifest_hash"),
        "annual_2024_oos_manifest_hash": annual24.get("manifest_hash"),
        "cross_year_report_hash": cross.get("report_hash"),
        "union_report_hashes": {k: v.get("report_hash") for k, v in unions.items()},
        "post_freeze_physical_tooling_amendment": bool(
            closure.get("post_freeze_physical_tooling_amendment")
        ),
        "prior_pre_oos_freeze_manifest_hash": closure.get(
            "prior_pre_oos_freeze_manifest_hash"
        ),
        "failures": sorted(set(failures)),
        "real_group9_dependency_intake_authorized": not failures,
        "semantic_freeze_still_required": True,
        "policy": (
            "Checkpoint 3 certifies final Group 8 evidence closure and authorizes "
            "Group 9 dependency intake/sizing only. Group 9 real annual materialization "
            "remains blocked until its own semantic freeze and real sizing/resource gates pass."
        ),
    }
    result["report_hash"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--closure", type=Path, required=True)
    p.add_argument("--handoff", type=Path, required=True)
    p.add_argument("--annual-2023", type=Path, required=True)
    p.add_argument("--annual-2024", type=Path, required=True)
    p.add_argument("--cross-year", type=Path, required=True)
    p.add_argument("--stage6-2023-union", type=Path, required=True)
    p.add_argument("--stage7-2023-union", type=Path, required=True)
    p.add_argument("--stage6-2024-union", type=Path, required=True)
    p.add_argument("--stage7-2024-union", type=Path, required=True)
    p.add_argument("--explicit-approval", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = publish(
        closure_path=a.closure.resolve(),
        handoff_path=a.handoff.resolve(),
        annual23_path=a.annual_2023.resolve(),
        annual24_path=a.annual_2024.resolve(),
        cross_path=a.cross_year.resolve(),
        stage6_2023_union_path=a.stage6_2023_union.resolve(),
        stage7_2023_union_path=a.stage7_2023_union.resolve(),
        stage6_2024_union_path=a.stage6_2024_union.resolve(),
        stage7_2024_union_path=a.stage7_2024_union.resolve(),
        explicit_approval=a.explicit_approval,
        output=a.output.resolve(),
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0 if r["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
