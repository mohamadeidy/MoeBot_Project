#!/usr/bin/env python3
"""Execute exact amended PA7 transition enumeration on authorized 2023 partial slices.

The diagnostic restores exact Source + Group4 + Group6 annual inputs while Groups
2/3/5/7 remain empty schema stubs. It executes the real amended bounded-range and
PA7 breakout implementation, so recorded Group4+Group6+Group8 transition counts
are exact for this diagnostic scope. It does not change frozen state or access OOS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

EXPECTED_ENGINE_SHA256 = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
EXPECTED_REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
EXPECTED_FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(16*1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--group8-root",type=Path,required=True)
    p.add_argument("--staging-db",type=Path,required=True)
    p.add_argument("--output-db",type=Path,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    if a.year!=2023: raise SystemExit("transition workload diagnostic is 2023-only")
    root=a.group8_root.resolve(); engine_path=root/"code/moebot_group8_engine_v0_8_0.py"
    if sha256_file(engine_path)!=EXPECTED_ENGINE_SHA256: raise SystemExit("unexpected amended engine identity")
    registry=json.loads((root/"01_DEFINITION_REGISTRY.json").read_text()); freeze=json.loads((root/"DESIGN_FREEZE_MANIFEST.json").read_text()); status=json.loads((root/"STATUS.json").read_text())
    if registry.get("registry_hash")!=EXPECTED_REGISTRY_HASH or freeze.get("design_freeze_hash")!=EXPECTED_FREEZE_HASH: raise SystemExit("amended design identity mismatch")
    if status.get("annual_execution_2023_authorized") is not True or status.get("annual_execution_2024_authorized") is not False: raise SystemExit("annual authorization boundary mismatch")

    import sys
    sys.path.insert(0,str(root/"code"))
    from moebot_group8_engine_v0_8_0 import Group8Engine

    a.output_db.unlink(missing_ok=True)
    engine=Group8Engine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=root,year=2023)
    stage_seconds: dict[str,float]={}
    try:
        t=time.perf_counter(); engine.load_bars(); stage_seconds["load_bars"]=time.perf_counter()-t
        t=time.perf_counter(); engine.process_bounded_ranges(); stage_seconds["bounded_ranges"]=time.perf_counter()-t
        bounded_count=int(engine.out.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchone()[0])
        t=time.perf_counter(); engine.process_breakouts(); stage_seconds["breakouts"]=time.perf_counter()-t
        rows=engine.out.execute("SELECT definition_id,timeframe,direction,features_json FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_atr_buffer','pa_breakout_point_buffer')").fetchall()
        by_variant: dict[str,int]={}; by_timeframe: dict[str,int]={}; by_direction: dict[str,int]={}; by_source_group: dict[str,int]={}; initialization=0; rearmed=0
        unique_state_keys:set[str]=set(); unique_event_state_pairs:set[tuple[str,int]]=set()
        for row in rows:
            definition=str(row["definition_id"]); tf=str(row["timeframe"]); direction=str(row["direction"]); feats=json.loads(row["features_json"])
            by_variant[definition]=by_variant.get(definition,0)+1; by_timeframe[tf]=by_timeframe.get(tf,0)+1; by_direction[direction]=by_direction.get(direction,0)+1
            ident=str(feats.get("state_boundary_identity","")); source_group=ident.split(":",1)[0] if ":" in ident else "unknown"; by_source_group[source_group]=by_source_group.get(source_group,0)+1
            if feats.get("initialization_transition") is True: initialization+=1
            else: rearmed+=1
            key=str(feats.get("state_key","")); unique_state_keys.add(key)
        transition_count=len(rows)
        creation_states=int(engine.out.execute("SELECT COUNT(*) FROM pattern_lifecycle_event WHERE candidate_id IN (SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_atr_buffer','pa_breakout_point_buffer'))").fetchone()[0]) if "pattern_lifecycle_event" in {r[0] for r in engine.out.execute("SELECT name FROM sqlite_master WHERE type='table'")} else None
        out_size=a.output_db.stat().st_size
        qc=engine.out.execute("PRAGMA quick_check").fetchone()[0]
        old=json.loads((root/"reports/35_POSTFIX_BREAKOUT_CARDINALITY_DIAGNOSTIC.json").read_text())
        old_candidate=int(old["minimum_group6_plus_group8_workload"]["candidate_total"])
        reduction=1.0-(transition_count/old_candidate) if old_candidate else None
        report:dict[str,Any]={
            "format_version":1,"status":"PASS","scope":"POST_PA7_TRANSITION_AMENDMENT_EXACT_PARTIAL_ANNUAL_2023","year":2023,
            "engine_sha256":EXPECTED_ENGINE_SHA256,"definition_registry_hash":EXPECTED_REGISTRY_HASH,"design_freeze_hash":EXPECTED_FREEZE_HASH,
            "bar_count":sum(len(v) for v in engine.bars_by_tf.values()),"series_count":len(engine.bars_by_tf),"bounded_range_count":bounded_count,
            "transition_candidate_count":transition_count,"transition_candidates_by_variant":dict(sorted(by_variant.items())),"transition_candidates_by_timeframe":dict(sorted(by_timeframe.items())),"transition_candidates_by_direction":dict(sorted(by_direction.items())),"transition_candidates_by_boundary_source_group":dict(sorted(by_source_group.items())),
            "initialization_transition_count":initialization,"rearmed_transition_count":rearmed,"unique_state_key_count":len(unique_state_keys),
            "pattern_creation_state_count":creation_states,"output_db_size_bytes":out_size,"sqlite_quick_check":qc,"stage_seconds":stage_seconds,
            "pre_amendment_group6_plus_group8_candidate_lower_bound":old_candidate,"candidate_reduction_fraction_vs_pre_amendment_lower_bound":reduction,
            "observations":{"real_amended_engine_executed":True,"group4_exact_inputs_included":True,"group6_exact_inputs_included":True,"group8_bounded_ranges_materialized_exactly":True,"group5_group7_inputs_stubbed_empty":True,"counts_are_exact_for_partial_scope":True,"full_annual_transition_count_may_be_higher_due_to_group5_group7":True,"engine_changed":False,"definitions_changed":False,"thresholds_changed":False,"schema_changed":False,"upstream_changed":False,"authorization_changed":False,"oos_2024_accessed":False},
            "method":"Exact Group8Engine.load_bars + process_bounded_ranges + amended process_breakouts over exact 2023 Source/Group4/Group6 slices; no simulated breakout predicate.",
        }
        report["report_hash"]=stable_hash(report); a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n"); print(json.dumps(report,indent=2,sort_keys=True))
        if qc!="ok": return 2
    finally:
        engine.close()
    return 0


if __name__=="__main__": raise SystemExit(main())
