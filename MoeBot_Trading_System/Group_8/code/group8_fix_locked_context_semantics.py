#!/usr/bin/env python3
"""Apply the proven Group 8 locked-context semantics fix, fail closed.

The patch changes implementation only. Frozen definitions, thresholds, schema,
upstream lineage, and data remain unchanged. It centralizes bounded-range
invalidation, restricts ICT premium/discount enumeration to the same locked
context, and makes both engine and annual audits reject post-invalidation rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

DIAGNOSTIC_HASH = "78ff7696f1140a7dc60b7f495db8898eba341201c1ae5036c37b771039915e81"
GAP_ID = "G8-ICT-LOCKED-CONTEXT-005"


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def stable(v: Any) -> str:
    return hashlib.sha256(canonical(v)).hexdigest()


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    if text.count(start_marker) != 1:
        raise SystemExit(f"{label} start marker count={text.count(start_marker)}")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--group8-root", type=Path, required=True); a=p.parse_args()
    root=a.group8_root.resolve()
    diag=json.loads((root/"reports/27_LOCKED_CONTEXT_GAP_DIAGNOSTIC.json").read_text())
    if diag.get("report_hash") != DIAGNOSTIC_HASH or diag.get("gap_id") != GAP_ID or diag.get("status") != "GAP_REPRODUCED":
        raise SystemExit("locked-context diagnostic identity/status mismatch")
    if int(diag.get("post_invalidation_violation_count",0)) <= 0:
        raise SystemExit("diagnostic does not prove post-invalidation rows")

    # 1) Centralize the exact frozen bounded-range invalidation rule.
    post_path=root/"code/group8_postprocess_v0_8_0.py"; post=post_path.read_text()
    start="def _finalize_bounded_ranges(engine: Any) -> None:\n"
    end="def _finalize_breakout_followups(engine: Any) -> None:\n"
    new_block='''def first_bounded_range_invalidator(engine: Any, candidate: Any) -> dict[str, Any] | None:\n    """Return the first causal invalidator for the candidate's two locked Group4 boundaries."""\n    features = json.loads(candidate["features_json"])\n    zone_ids = [features.get("lower_zone_id"), features.get("upper_zone_id")]\n    invalidators: list[dict[str, Any]] = []\n    for zone_id in [z for z in zone_ids if z]:\n        for tr in engine.input.execute(\n            "SELECT * FROM group4__zone_transitions WHERE zone_id=? AND transition_time>? ORDER BY transition_time,transition_id",\n            (zone_id, int(candidate["availability_time"])),\n        ):\n            if not engine._status_active(str(tr["to_status"])):\n                invalidators.append({\n                    "source_type": "group4_zone_transitions",\n                    "source_id": tr["transition_id"],\n                    "event_time": int(tr["transition_time"]),\n                    "confirmation_time": int(tr["transition_time"]),\n                    "availability_time": int(tr["transition_time"]),\n                    "source_bar_id": tr["bar_id"],\n                    "details": {"zone_id": zone_id, "from_status": tr["from_status"], "to_status": tr["to_status"], "reason": tr["reason"]},\n                })\n                break\n        for ev in engine.input.execute(\n            "SELECT * FROM group4__zone_interactions WHERE zone_id=? AND interaction_time>? ORDER BY interaction_time,interaction_id",\n            (zone_id, int(candidate["availability_time"])),\n        ):\n            if not engine._status_active(str(ev["status_after"])):\n                invalidators.append({\n                    "source_type": "group4_zone_interactions",\n                    "source_id": ev["interaction_id"],\n                    "event_time": int(ev["interaction_time"]),\n                    "confirmation_time": int(ev["interaction_time"]),\n                    "availability_time": int(ev["interaction_time"]),\n                    "source_bar_id": ev["bar_id"],\n                    "details": {"zone_id": zone_id, "event_type": ev["event_type"], "status_after": ev["status_after"]},\n                })\n                break\n    if not invalidators:\n        return None\n    return min(invalidators, key=lambda x: (x["availability_time"], x["source_type"], str(x["source_id"])))\n\n\ndef _finalize_bounded_ranges(engine: Any) -> None:\n    candidates = engine.out.execute(\n        "SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' ORDER BY availability_time,candidate_id"\n    ).fetchall()\n    for candidate in candidates:\n        inv = first_bounded_range_invalidator(engine, candidate)\n        if inv is not None:\n            _write_pattern_terminal_state(\n                engine, candidate, state="invalidated", source_bar_id=inv["source_bar_id"],\n                event_time=inv["event_time"], availability_time=inv["availability_time"], details=inv["details"],\n            )\n            write_invalidation(\n                engine,\n                subject_type="price_action_pattern_candidate",\n                subject_id=candidate["candidate_id"],\n                rule_id="pa_bounded_range_context.invalidation_rule",\n                source_type=inv["source_type"], source_id=inv["source_id"],\n                event_time=inv["event_time"], confirmation_time=inv["confirmation_time"], availability_time=inv["availability_time"],\n                reasons=["locked_group4_boundary_invalidated"], details=inv["details"],\n            )\n        else:\n            annual_end = int(engine.annual_end_time or candidate["availability_time"])\n            _write_pattern_terminal_state(\n                engine, candidate, state="right_censored", source_bar_id=None,\n                event_time=annual_end, availability_time=annual_end,\n                details={"rule": "annual_end_no_locked_boundary_invalidation"},\n            )\n\n\n'''
    post=replace_between(post,start,end,new_block,"postprocessor bounded-range invalidation")
    post_path.write_text(post)

    # 2) Restrict premium/discount bars to the exact same locked context.
    engine_path=root/"code/moebot_group8_engine_v0_8_0.py"; engine=engine_path.read_text()
    old_head='''    def process_ict(self) -> None:\n        symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"\n'''
    new_head='''    def process_ict(self) -> None:\n        from group8_postprocess_v0_8_0 import first_bounded_range_invalidator\n        symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"\n'''
    if engine.count(old_head)!=1: raise SystemExit(f"process_ict import anchor count={engine.count(old_head)}")
    engine=engine.replace(old_head,new_head,1)
    ict_start='''        for rg in self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchall():\n'''
    ict_end='''        fvg_by_id={str(r["fvg_id"]):dict(r) for r in self.input.execute("SELECT * FROM group6__fvg_events")}\n'''
    new_ict='''        for rg in self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchall():\n            midpoint=(float(rg["lower"])+float(rg["upper"]))/2; src=self._bar_by_id(rg["source_bar_id"])\n            if not src:continue\n            invalidator=first_bounded_range_invalidator(self,rg)\n            invalidation_availability=int(invalidator["availability_time"]) if invalidator is not None else None\n            key,idx=self.bar_pos[src.id]\n            for bar in self.bars_by_tf[key][idx:]:\n                if bar.available_at<rg["availability_time"]:continue\n                if invalidation_availability is not None and bar.available_at>=invalidation_availability:break\n                loc="discount" if bar.close<midpoint else "premium" if bar.close>midpoint else "equilibrium"; self._write_interpretation("ict_premium_discount_context",symbol=bar.symbol,timeframe=bar.timeframe,direction="neutral",event_time=bar.close_time,confirmation_time=bar.close_time,availability_time=max_time(bar.available_at,rg["availability_time"]),upstream_refs=[self._ref("group8","price_action_pattern_candidate",rg["candidate_id"],rg["availability_time"]),self._ref("source","bars",bar.id,bar.available_at,event_time=bar.close_time,timeframe=bar.timeframe)],reasons=[loc],evidence_strength={"location":loc,"midpoint":midpoint,"close":bar.close})\n'''
    engine=replace_between(engine,ict_start,ict_end,new_ict,"ICT locked-context enumeration")

    # 3) Make the engine's own post-lifecycle audit reject this exact violation.
    audit_anchor='''        n=self.out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0]\n'''
    audit_insert='''        locked_context_violations=self.out.execute("""SELECT COUNT(*) FROM school_interpretation i JOIN invalidation_record inv ON inv.subject_type='price_action_pattern_candidate' AND inv.rule_id='pa_bounded_range_context.invalidation_rule' AND inv.subject_id=json_extract(i.upstream_refs_json,'$[0].source_id') WHERE i.definition_id='ict_premium_discount_context' AND i.availability_time>=inv.availability_time""").fetchone()[0]\n        if locked_context_violations:failures.append(f"locked_context:ict_premium_discount_context:{locked_context_violations}")\n        n=self.out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0]\n'''
    if engine.count(audit_anchor)!=1: raise SystemExit(f"engine audit anchor count={engine.count(audit_anchor)}")
    engine=engine.replace(audit_anchor,audit_insert,1);engine_path.write_text(engine)

    # 4) Independent annual audit must reject the same condition.
    annual_path=root/"code/group8_annual_validation.py"; annual=annual_path.read_text()
    fail_anchor='''    failures: list[str] = []\n'''
    if annual.count(fail_anchor)!=1: raise SystemExit(f"annual failures anchor count={annual.count(fail_anchor)}")
    annual=annual.replace(fail_anchor,fail_anchor+'''    locked_context_violations = 0\n''',1)
    annual_anchor='''        before_creation = int(out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0])\n'''
    annual_insert='''        locked_context_violations = int(out.execute("""SELECT COUNT(*) FROM school_interpretation i JOIN invalidation_record inv ON inv.subject_type='price_action_pattern_candidate' AND inv.rule_id='pa_bounded_range_context.invalidation_rule' AND inv.subject_id=json_extract(i.upstream_refs_json,'$[0].source_id') WHERE i.definition_id='ict_premium_discount_context' AND i.availability_time>=inv.availability_time""").fetchone()[0])\n        if locked_context_violations: failures.append(f"locked_context:ict_premium_discount_context:{locked_context_violations}")\n        before_creation = int(out.execute("SELECT COUNT(*) FROM hypothesis_lifecycle_event l JOIN narrative_hypothesis h USING(hypothesis_id) WHERE l.availability_time<h.availability_time").fetchone()[0])\n'''
    if annual.count(annual_anchor)!=1: raise SystemExit(f"annual locked-context anchor count={annual.count(annual_anchor)}")
    annual=annual.replace(annual_anchor,annual_insert,1)
    report_anchor='''        "causality_errors": causal_errors,\n'''
    if annual.count(report_anchor)!=1: raise SystemExit(f"annual report anchor count={annual.count(report_anchor)}")
    annual=annual.replace(report_anchor,report_anchor+'''        "locked_context_violations": locked_context_violations,\n''',1);annual_path.write_text(annual)

    # 5) Permanent regression using the already-proven invalidation fixture.
    test_path=root/"tests/test_group8_lifecycle_persistence_v0_8_0.py"; test=test_path.read_text()
    test_anchor='''    def test_bounded_range_right_censors_without_invalidation(self):\n'''
    regression='''    def test_ict_premium_discount_never_survives_locked_range_invalidation(self):\n        with tempfile.TemporaryDirectory() as td:\n            root = Path(td); stage = root / "stage.sqlite"; output = root / "out.sqlite"\n            base.make_stage(stage)\n            con = sqlite3.connect(stage)\n            columns = [r[1] for r in con.execute("PRAGMA table_info('group4__zone_transitions')")]\n            row = {c: None for c in columns}\n            row.update(transition_id="zlow_invalid_locked_context_regression", zone_id="zlow", bar_id=22, transition_time=1700000000+22*900,\n                       from_status="active", to_status="invalidated", role_after="support", reason="fixture_break", transition_hash="zlow-invalid-locked-context-regression")\n            con.execute(f"INSERT INTO group4__zone_transitions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])\n            con.commit(); con.close()\n            self._run(stage, output)\n            con = sqlite3.connect(output)\n            violations = con.execute("""\n                SELECT COUNT(*)\n                FROM school_interpretation i\n                JOIN invalidation_record inv\n                  ON inv.subject_type='price_action_pattern_candidate'\n                 AND inv.rule_id='pa_bounded_range_context.invalidation_rule'\n                 AND inv.subject_id=json_extract(i.upstream_refs_json,'$[0].source_id')\n                WHERE i.definition_id='ict_premium_discount_context'\n                  AND i.availability_time>=inv.availability_time\n            """).fetchone()[0]\n            invalidated = con.execute("SELECT COUNT(DISTINCT subject_id) FROM invalidation_record WHERE rule_id='pa_bounded_range_context.invalidation_rule'").fetchone()[0]\n            self.assertGreater(invalidated, 0)\n            self.assertEqual(violations, 0)\n            con.close()\n\n'''
    if test.count(test_anchor)!=1: raise SystemExit(f"lifecycle regression anchor count={test.count(test_anchor)}")
    test=test.replace(test_anchor,regression+test_anchor,1);test_path.write_text(test)

    # 6) Revoke stale technical/annual authorization until exact identities are re-frozen.
    status_path=root/"STATUS.json"; status=json.loads(status_path.read_text())
    previous_engine=status.get("engine_build",{}).get("engine_sha256")
    status["annual_execution_authorized"]=False;status["annual_execution_2023_authorized"]=False;status["annual_execution_2024_authorized"]=False;status["engine_build_authorized"]=False
    status["status"]="BLOCKING_GAP_G8_ICT_LOCKED_CONTEXT_FIXED_PENDING_TECHNICAL_REFREEZE"
    status["blocking_gap"]={"gap_id":GAP_ID,"status":"FIXED_PENDING_REFREEZE","severity":"BLOCKING","diagnostic_report_hash":DIAGNOSTIC_HASH,"previous_engine_sha256":previous_engine,"definitions_changed":False,"thresholds_changed":False,"schema_changed":False,"upstream_changed":False}
    if isinstance(status.get("engine_build"),dict): status["engine_build"]["status"]="STALE_PENDING_TECHNICAL_REFREEZE"
    status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")

    gap={
        "format_version":1,"status":"BLOCKING_GAP_FIXED_PENDING_TECHNICAL_REFREEZE","phase":"ENGINE_REVIEW_GAP_ANALYSIS","gap_id":GAP_ID,"severity":"BLOCKING",
        "diagnostic_report_hash":DIAGNOSTIC_HASH,"diagnostic_violation_count":int(diag["post_invalidation_violation_count"]),
        "root_cause":"ict_premium_discount_context enumerated every later bar from the bounded-range source bar without applying the frozen bounded-range invalidation horizon; lifecycle finalization computed that horizon only after ICT enumeration.",
        "minimal_correct_fix":"Centralize the exact bounded-range invalidator, reuse it during ICT enumeration and lifecycle finalization, stop enumeration when bar availability reaches the invalidation availability, and independently audit zero post-invalidation interpretations.",
        "acceptance_rule":"For every ict_premium_discount_context linked to an invalidated pa_bounded_range_context, interpretation.availability_time < invalidation.availability_time.",
        "definitions_changed":False,"thresholds_changed":False,"schema_changed":False,"upstream_changed":False,"annual_authorization_revoked_pending_refreeze":True,
    }
    gap["report_hash"]=stable(gap);(root/"reports/28_LOCKED_CONTEXT_GAP_ANALYSIS.json").write_text(json.dumps(gap,indent=2,sort_keys=True)+"\n")
    print(json.dumps(gap,indent=2,sort_keys=True));return 0


if __name__=="__main__": raise SystemExit(main())
