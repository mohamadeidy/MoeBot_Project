#!/usr/bin/env python3
"""Fail-closed pre-official gate aggregation for canonical stage-4 execution."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from group8_context_rejection_fastpath import IndexedContextRejectionEngine, STAGE4_PARTITION_COUNT
from moebot_group8_engine_v0_8_0 import stable_hash


def head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, text=True, capture_output=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--parity-report", type=Path, required=True)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    current_head = head_sha()
    status = json.loads((args.artifacts_root / "STATUS.json").read_text())
    parity = json.loads(args.parity_report.read_text())
    plan = IndexedContextRejectionEngine.stage4_partition_plan()
    workflow_text = args.workflow.read_text()

    parity_pass = parity.get("status") == "PASS" and parity.get("parity", {}).get("status") == "PASS"
    negatives = parity.get("negative_regressions", {})
    required_negative_names = {
        "missing_partition", "repeated_partition", "conflicting_receipt", "modified_partition_output",
        "wrong_plan_hash", "wrong_execution_order", "finalize_before_complete", "idempotent_retry",
    }
    negative_pass = set(negatives) == required_negative_names and all(value == "PASS" for value in negatives.values())

    reports = []
    for path in sorted(args.benchmark_dir.rglob("stage4-benchmark-*.json")):
        reports.append(json.loads(path.read_text()))
    benchmark_indices = sorted(int(report["partition_index"]) for report in reports)
    benchmark_complete = benchmark_indices == list(range(STAGE4_PARTITION_COUNT))
    benchmark_identity = all(
        report.get("status") == "PASS"
        and report.get("mode") == "benchmark"
        and report.get("github_head_sha") == current_head
        and report.get("plan_hash") == plan["plan_hash"]
        and report.get("checkpoint_3_published") is False
        and report.get("free_only") is True
        and report.get("oos_2024_accessed") is False
        for report in reports
    )
    worst_wall = max((float(report["full_job_wall_seconds"]) for report in reports), default=float("inf"))
    runtime_safety_pass = benchmark_complete and benchmark_identity and worst_wall <= 14400

    workflow_validation_pass = all((
        "group8_stage4_full_job.py --mode official" in workflow_text,
        "group8_stage4_full_job.py --mode benchmark" in workflow_text,
        "--stage4-finalize" in workflow_text,
        "stage4_partition_chain_complete" in workflow_text,
        "annual_execution_2024_authorized" in workflow_text,
        "ubuntu-latest" in workflow_text,
        "group8_segmented_annual_core.py" in workflow_text,
        "--start 4 --end 4 --report" not in workflow_text,
        "runs-on: self-hosted" not in workflow_text,
    ))
    free_only_pass = (
        status["free_only_policy"]["paid_runner_allowed"] is False
        and status["free_only_policy"]["paid_service_allowed"] is False
    )
    lock_2024_pass = status["annual_execution_2024_authorized"] is False

    ranges = [
        {
            "range_identity": f"{plan['plan_id']}:range-{index:02d}-{index:02d}",
            "first_partition": index,
            "last_partition": index,
        }
        for index in range(STAGE4_PARTITION_COUNT)
    ]
    gates = {
        "PARITY_PASS": parity_pass,
        "NEGATIVE_REGRESSIONS_PASS": negative_pass,
        "FULL_DATA_BENCHMARK_PASS": benchmark_complete and benchmark_identity,
        "RUNTIME_SAFETY_PASS": runtime_safety_pass,
        "WORKFLOW_YAML_VALIDATION_PASS": workflow_validation_pass,
        "FREE_ONLY_PASS": free_only_pass,
        "2024_LOCK_CONFIRMED": lock_2024_pass,
    }
    payload = {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "github_head_sha": current_head,
        "gates": gates,
        "worst_full_job_wall_seconds": worst_wall,
        "safety_limit_seconds": 14400,
        "selected_partition_count": STAGE4_PARTITION_COUNT,
        "frozen_job_ranges": ranges,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "benchmark_report_count": len(reports),
        "official_execution_authorized": all(gates.values()),
        "oos_2024_accessed": False,
        "free_only": True,
    }
    payload["report_hash"] = stable_hash(payload)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["status"] != "PASS":
        raise RuntimeError(f"pre-official gate failure:{gates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
