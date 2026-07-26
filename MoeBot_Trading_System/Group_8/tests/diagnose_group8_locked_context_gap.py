#!/usr/bin/env python3
"""Reproduce the frozen locked-context enumeration gap without mutating engine code."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import test_group8_engine_v0_8_0 as base
from moebot_group8_engine_v0_8_0 import Group8Engine

ART = base.ART


def stable(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);stage=root/"stage.sqlite";output=root/"out.sqlite";base.make_stage(stage)
        con=sqlite3.connect(stage)
        cols=[r[1] for r in con.execute("PRAGMA table_info('group4__zone_transitions')")]
        row={c:None for c in cols}
        invalidation_time=1700000000+22*900
        row.update(transition_id="zlow_invalid_locked_context_diag",zone_id="zlow",bar_id=22,transition_time=invalidation_time,from_status="active",to_status="invalidated",role_after="support",reason="fixture_break",transition_hash="zlow-invalid-locked-context-diagnostic")
        con.execute(f"INSERT INTO group4__zone_transitions ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",[row[c] for c in cols]);con.commit();con.close()

        engine=Group8Engine(staging_db=stage,output_db=output,artifacts_root=ART,year=2023,symbol="XAUUSD_")
        report=engine.run();engine.close()
        if report.get("status")!="PASS": raise SystemExit(f"fixture engine audit failed unexpectedly: {report.get('failures')}")
        con=sqlite3.connect(output);con.row_factory=sqlite3.Row
        violations=con.execute("""
            SELECT i.interpretation_id,i.availability_time,inv.subject_id bounded_range_context_id,inv.availability_time invalidation_time
            FROM school_interpretation i
            JOIN invalidation_record inv
              ON inv.subject_type='price_action_pattern_candidate'
             AND inv.rule_id='pa_bounded_range_context.invalidation_rule'
             AND inv.subject_id=json_extract(i.upstream_refs_json,'$[0].source_id')
            WHERE i.definition_id='ict_premium_discount_context'
              AND i.availability_time>=inv.availability_time
            ORDER BY inv.subject_id,i.availability_time,i.interpretation_id
        """).fetchall()
        invalidated_ranges=con.execute("SELECT COUNT(DISTINCT subject_id) FROM invalidation_record WHERE rule_id='pa_bounded_range_context.invalidation_rule'").fetchone()[0]
        premium_total=con.execute("SELECT COUNT(*) FROM school_interpretation WHERE definition_id='ict_premium_discount_context'").fetchone()[0]
        con.close()
        evidence={
            "format_version":1,"status":"GAP_REPRODUCED" if violations else "NO_GAP_REPRODUCED",
            "gap_id":"G8-ICT-LOCKED-CONTEXT-005","severity":"BLOCKING",
            "frozen_definition":"ict_premium_discount_context requires closed_bar_within_same_locked_context; bounded range invalidates at first later locked-boundary invalidation.",
            "fixture_transition_id":"zlow_invalid_locked_context_diag","fixture_invalidation_time":invalidation_time,
            "engine_audit_status":report["status"],"invalidated_range_count":invalidated_ranges,"premium_discount_total":premium_total,
            "post_invalidation_violation_count":len(violations),
            "sample_violations":[dict(r) for r in violations[:25]],
            "acceptance_rule":"post_invalidation_violation_count must equal 0; interpretation availability must be strictly earlier than the bounded-range invalidation availability.",
            "engine_mutated":False,"design_mutated":False,"thresholds_mutated":False,
        }
        evidence["report_hash"]=stable(evidence)
        out=ART/"reports/27_LOCKED_CONTEXT_GAP_DIAGNOSTIC.json";out.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
        print(json.dumps(evidence,indent=2,sort_keys=True))
        if not violations: raise SystemExit("expected frozen implementation gap was not reproduced")
        return 0


if __name__=="__main__": raise SystemExit(main())
