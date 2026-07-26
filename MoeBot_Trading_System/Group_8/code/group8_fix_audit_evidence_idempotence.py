#!/usr/bin/env python3
"""Fix the proven Group 8 lifecycle audit-evidence duplicate gap, fail closed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DIAGNOSTIC_REPORT_HASH = "3e398fbbbfc72db1545a44e5a88ec449535541348cccf537731d31052a90e6df"
GAP_ID = "G8-ENGINE-LIFECYCLE-AUDIT-IDEMPOTENCE-003"


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group8-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.group8_root.resolve()
    post = root / "code/group8_postprocess_v0_8_0.py"
    test = root / "tests/test_group8_lifecycle_persistence_v0_8_0.py"
    diagnostic_path = root / "reports/23_LIFECYCLE_HARDENING_V2_FAILURE_DIAGNOSTIC.json"

    diagnostic = json.loads(diagnostic_path.read_text())
    if diagnostic.get("report_hash") != DIAGNOSTIC_REPORT_HASH:
        raise SystemExit("lifecycle v2 diagnostic identity mismatch")
    headers = diagnostic.get("failure_headers", [])
    if len(headers) != 1 or "test_extended_idempotence_includes_state_lifecycle_invalidation_audit_checkpoint" not in headers[0]:
        raise SystemExit("diagnostic does not prove the expected single idempotence failure")
    tail = "\n".join(diagnostic.get("output_tail", []))
    if "'group8_audit_evidence': 4" not in tail or "'group8_audit_evidence': 7" not in tail:
        raise SystemExit("diagnostic does not prove audit evidence 4->7 growth")

    old = '''def persist_audit_evidence(engine: Any, engine_audit: Mapping[str, Any], persistence_report: Mapping[str, Any]) -> None:\n    checked_at = int(engine.annual_end_time or 0)\n    checks = [\n        ("engine_core_audit", str(engine_audit.get("status", "UNKNOWN")), dict(engine_audit)),\n        ("lifecycle_persistence", str(persistence_report.get("status", "UNKNOWN")), dict(persistence_report)),\n        ("checkpoint_persistence", "PASS" if engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0] else "FAIL", {\n            "checkpoint_count": int(engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0])\n        }),\n        ("prohibited_output_audit", "PASS" if not engine_audit.get("failures") else str(engine_audit.get("status", "FAIL")), {\n            "engine_audit_hash": engine_audit.get("report_hash"), "failures": engine_audit.get("failures", [])\n        }),\n    ]\n    for check_name, status, details in checks:\n        payload = {"check_name": check_name, "status": status, "scope": f"group8-year-{engine.year}", "details": details, "checked_at": checked_at}\n        audit_id = deterministic_id("g8audit", payload)\n        audit_hash = stable_hash(payload)\n        row = {\n            "audit_id": audit_id, "check_name": check_name, "status": status, "scope": payload["scope"],\n            "details_json": canonical_json(details), "checked_at": checked_at, "audit_hash": audit_hash,\n        }\n        engine._insert_immutable("group8_audit_evidence", "audit_id", audit_id, row, hash_column="audit_hash", expected_hash=audit_hash)\n    engine.out.commit()\n'''
    new = '''def persist_audit_evidence(engine: Any, engine_audit: Mapping[str, Any], persistence_report: Mapping[str, Any]) -> None:\n    checked_at = int(engine.annual_end_time or 0)\n    scope = f"group8-year-{engine.year}"\n    checks = [\n        ("engine_core_audit", str(engine_audit.get("status", "UNKNOWN")), dict(engine_audit)),\n        ("lifecycle_persistence", str(persistence_report.get("status", "UNKNOWN")), dict(persistence_report)),\n        ("checkpoint_persistence", "PASS" if engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0] else "FAIL", {\n            "checkpoint_count": int(engine.out.execute("SELECT COUNT(*) FROM processing_checkpoint").fetchone()[0])\n        }),\n        ("prohibited_output_audit", "PASS" if not engine_audit.get("failures") else str(engine_audit.get("status", "FAIL")), {\n            "engine_audit_hash": engine_audit.get("report_hash"), "failures": engine_audit.get("failures", [])\n        }),\n    ]\n    for check_name, status, details in checks:\n        existing = engine.out.execute(\n            "SELECT audit_id,status,audit_hash FROM group8_audit_evidence WHERE check_name=? AND scope=? AND checked_at=? ORDER BY audit_id",\n            (check_name, scope, checked_at),\n        ).fetchall()\n        if len(existing) > 1:\n            raise RuntimeError(f"duplicate audit evidence identity already present: {check_name}:{scope}:{checked_at}")\n        if existing:\n            if str(existing[0]["status"]) != status:\n                raise RuntimeError(f"conflicting audit status on deterministic rerun: {check_name}:{scope}:{checked_at}")\n            continue\n        payload = {"check_name": check_name, "status": status, "scope": scope, "details": details, "checked_at": checked_at}\n        audit_id = deterministic_id("g8audit", payload)\n        audit_hash = stable_hash(payload)\n        row = {\n            "audit_id": audit_id, "check_name": check_name, "status": status, "scope": scope,\n            "details_json": canonical_json(details), "checked_at": checked_at, "audit_hash": audit_hash,\n        }\n        engine._insert_immutable("group8_audit_evidence", "audit_id", audit_id, row, hash_column="audit_hash", expected_hash=audit_hash)\n    engine.out.commit()\n'''
    text = post.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"audit persistence patch anchor count={text.count(old)}")
    post.write_text(text.replace(old, new, 1))

    old_test = '''            con = sqlite3.connect(output)\n            before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}\n            checkpoints_before = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()\n            con.close()\n            self._run(stage, output)\n            con = sqlite3.connect(output)\n            after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}\n            checkpoints_after = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()\n            con.close()\n            self.assertEqual(before, after)\n            self.assertEqual(checkpoints_before, checkpoints_after)\n'''
    new_test = '''            con = sqlite3.connect(output)\n            before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}\n            audit_before = con.execute("SELECT check_name,scope,checked_at,status,audit_id,audit_hash FROM group8_audit_evidence ORDER BY check_name,scope,checked_at,audit_id").fetchall()\n            checkpoints_before = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()\n            con.close()\n            self._run(stage, output)\n            con = sqlite3.connect(output)\n            after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}\n            audit_after = con.execute("SELECT check_name,scope,checked_at,status,audit_id,audit_hash FROM group8_audit_evidence ORDER BY check_name,scope,checked_at,audit_id").fetchall()\n            duplicate_audit_keys = con.execute("SELECT check_name,scope,checked_at,COUNT(*) FROM group8_audit_evidence GROUP BY check_name,scope,checked_at HAVING COUNT(*)>1").fetchall()\n            checkpoints_after = con.execute("SELECT symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at FROM processing_checkpoint ORDER BY symbol,timeframe,stage").fetchall()\n            con.close()\n            self.assertEqual(before, after)\n            self.assertEqual(audit_before, audit_after)\n            self.assertEqual(duplicate_audit_keys, [])\n            self.assertEqual(checkpoints_before, checkpoints_after)\n'''
    ttext = test.read_text()
    if ttext.count(old_test) != 1:
        raise SystemExit(f"idempotence regression anchor count={ttext.count(old_test)}")
    test.write_text(ttext.replace(old_test, new_test, 1))

    report = {
        "format_version": 1,
        "status": "BLOCKING_GAP_FIXED_PENDING_RETEST",
        "phase": "ENGINE_BUILD_REVIEW_GAP_ANALYSIS",
        "gap_id": GAP_ID,
        "parent_gap_id": "G8-ENGINE-LIFECYCLE-002",
        "severity": "BLOCKING",
        "root_cause": "group8_audit_evidence deterministic IDs included mutable rerun audit details; identical annual reruns therefore appended new audit rows instead of preserving one immutable identity per check/scope/checked_at.",
        "evidence_report_hash": DIAGNOSTIC_REPORT_HASH,
        "observed_before_count": 4,
        "observed_after_rerun_count": 7,
        "minimal_correct_fix": "Fail closed on multiple pre-existing audit identities, preserve the first immutable row for the same check_name/scope/checked_at when status is unchanged, and reject conflicting rerun status.",
        "regression": "Extended idempotence now compares exact audit rows and asserts no duplicate check_name/scope/checked_at keys.",
        "design_changed": False,
        "thresholds_changed": False,
        "upstream_changed": False,
        "annual_authorization_changed_by_this_fix": False,
    }
    report["report_hash"] = stable_hash(report)
    (root / "reports/24_LIFECYCLE_AUDIT_IDEMPOTENCE_GAP_ANALYSIS.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
