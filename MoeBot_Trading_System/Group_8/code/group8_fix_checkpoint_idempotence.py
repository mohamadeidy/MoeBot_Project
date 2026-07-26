#!/usr/bin/env python3
"""Fix the proven Group 8 processing-checkpoint rerun instability, fail closed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DIAGNOSTIC_REPORT_HASH = "5dff59af4b0e3456348296c7b08c8e5624a0270bc2e5252b20d02831d808ee77"
GAP_ID = "G8-ENGINE-CHECKPOINT-IDEMPOTENCE-004"


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group8-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.group8_root.resolve()
    post = root / "code/group8_postprocess_v0_8_0.py"
    diagnostic = json.loads((root / "reports/25_LIFECYCLE_FIX2_FAILURE_DIAGNOSTIC.json").read_text())

    if diagnostic.get("report_hash") != DIAGNOSTIC_REPORT_HASH:
        raise SystemExit("checkpoint diagnostic identity mismatch")
    headers = diagnostic.get("failure_headers", [])
    if len(headers) != 1 or "test_extended_idempotence_includes_state_lifecycle_invalidation_audit_checkpoint" not in headers[0]:
        raise SystemExit("diagnostic does not prove expected checkpoint idempotence failure")
    tail = "\n".join(diagnostic.get("output_tail", []))
    if "self.assertEqual(checkpoints_before, checkpoints_after)" not in tail:
        raise SystemExit("diagnostic does not bind failure to exact checkpoint equality")

    old = '''def checkpoint(engine: Any, stage: str, status: str = "PASS") -> None:\n    count_tables = [\n        "price_action_pattern_candidate",\n        "price_action_pattern_state",\n        "school_interpretation",\n        "narrative_hypothesis",\n        "hypothesis_lifecycle_event",\n        "invalidation_record",\n        "shared_evidence",\n        "conflicting_evidence",\n        "multi_timeframe_context_relation",\n        "evidence_chain",\n    ]\n    counts = {table: int(engine.out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in count_tables}\n    for (symbol, timeframe), bars in sorted(engine.bars_by_tf.items()):\n        last = bars[-1] if bars else None\n        last_bar_id = int(last.id) if last is not None else None\n        last_time = int(last.available_at) if last is not None else int(engine.annual_end_time or 0)\n        snapshot = {\n            "stage": stage,\n            "symbol": symbol,\n            "timeframe": timeframe,\n            "last_bar_id": last_bar_id,\n            "last_time": last_time,\n            "counts": counts,\n            "engine_version": engine.config["engine_version"],\n            "schema_version": engine.config["schema_version"],\n            "config_id": engine.config["config_id"],\n        }\n        snapshot_hash = stable_hash(snapshot)\n        engine.out.execute(\n            """INSERT INTO processing_checkpoint(symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at)\n               VALUES(?,?,?,?,?,?,?,?)\n               ON CONFLICT(symbol,timeframe,stage) DO UPDATE SET\n                   status=excluded.status,last_bar_id=excluded.last_bar_id,last_time=excluded.last_time,\n                   snapshot_hash=excluded.snapshot_hash,updated_at=excluded.updated_at""",\n            (symbol, timeframe, stage, status, last_bar_id, last_time, snapshot_hash, last_time),\n        )\n    engine.out.commit()\n'''
    new = '''def checkpoint(engine: Any, stage: str, status: str = "PASS") -> None:\n    for (symbol, timeframe), bars in sorted(engine.bars_by_tf.items()):\n        first = bars[0] if bars else None\n        last = bars[-1] if bars else None\n        first_bar_id = int(first.id) if first is not None else None\n        first_time = int(first.available_at) if first is not None else None\n        last_bar_id = int(last.id) if last is not None else None\n        last_time = int(last.available_at) if last is not None else int(engine.annual_end_time or 0)\n        snapshot = {\n            "stage": stage,\n            "symbol": symbol,\n            "timeframe": timeframe,\n            "input_bar_count": len(bars),\n            "first_bar_id": first_bar_id,\n            "first_time": first_time,\n            "last_bar_id": last_bar_id,\n            "last_time": last_time,\n            "engine_version": engine.config["engine_version"],\n            "schema_version": engine.config["schema_version"],\n            "config_id": engine.config["config_id"],\n        }\n        snapshot_hash = stable_hash(snapshot)\n        engine.out.execute(\n            """INSERT INTO processing_checkpoint(symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at)\n               VALUES(?,?,?,?,?,?,?,?)\n               ON CONFLICT(symbol,timeframe,stage) DO UPDATE SET\n                   status=excluded.status,last_bar_id=excluded.last_bar_id,last_time=excluded.last_time,\n                   snapshot_hash=excluded.snapshot_hash,updated_at=excluded.updated_at""",\n            (symbol, timeframe, stage, status, last_bar_id, last_time, snapshot_hash, last_time),\n        )\n    engine.out.commit()\n'''
    text = post.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"checkpoint patch anchor count={text.count(old)}")
    post.write_text(text.replace(old, new, 1))

    report = {
        "format_version": 1,
        "status": "BLOCKING_GAP_FIXED_PENDING_RETEST",
        "phase": "ENGINE_BUILD_REVIEW_GAP_ANALYSIS",
        "gap_id": GAP_ID,
        "parent_gap_id": "G8-ENGINE-LIFECYCLE-002",
        "severity": "BLOCKING",
        "root_cause": "processing_checkpoint snapshot hashes included cumulative output-table counts. On an identical rerun, lifecycle outputs from the previous completed run already existed before early stages, so checkpoint hashes changed even though the input processing frontier was identical.",
        "evidence_report_hash": DIAGNOSTIC_REPORT_HASH,
        "minimal_correct_fix": "Define checkpoint snapshot identity from immutable input frontier and frozen engine/schema/config identity only: input bar count, first/last bar IDs and availability times, stage, symbol and timeframe.",
        "regression": "Existing extended idempotence requires exact checkpoint rows to remain byte-for-byte stable across identical reruns; missing-bar fixtures retain distinct input-frontier identity through input_bar_count.",
        "design_changed": False,
        "thresholds_changed": False,
        "upstream_changed": False,
        "annual_authorization_changed_by_this_fix": False,
    }
    report["report_hash"] = stable_hash(report)
    (root / "reports/26_CHECKPOINT_IDEMPOTENCE_GAP_ANALYSIS.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
