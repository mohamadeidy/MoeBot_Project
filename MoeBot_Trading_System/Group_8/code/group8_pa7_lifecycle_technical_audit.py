#!/usr/bin/env python3
"""Independent technical audit for the Gap008 PA7 lifecycle correctness fix."""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-LIFECYCLE-RETIREMENT-008"
ENGINE_SHA = "44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"
FIX_REPORT_HASH = "b35cee4b2f1500ab5a20e8a1bfb8e0a928047d2875e6c5c2c627e8383af0fc8d"
GAP_REPORT_HASH = "cdd862c7d725858be54c326300404811deee6245ddcb0da3d32a4be68b4122a8"


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''): h.update(b)
    return h.hexdigest()

def stable(x: object) -> str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def selfhash(x: dict[str,Any], field: str) -> str:
    y=dict(x);y.pop(field,None);return stable(y)


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--base-technical-audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve()
    engine_path=root/'code/moebot_group8_engine_v0_8_0.py';test_path=root/'tests/test_group8_pa7_lifecycle_retirement_v0_8_0.py';fix_path=root/'reports/41_PA7_LIFECYCLE_RETIREMENT_FIX.json';gap_path=root/'reports/40_PA7_LIFECYCLE_RETIREMENT_GAP.json'
    status=json.loads((root/'STATUS.json').read_text());reg=json.loads((root/'01_DEFINITION_REGISTRY.json').read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text());fix=json.loads(fix_path.read_text());gap=json.loads(gap_path.read_text());base=json.loads(a.base_technical_audit.read_text());text=engine_path.read_text();tests=test_path.read_text()
    checks:dict[str,bool]={}
    checks['engine_identity']=sha(engine_path)==ENGINE_SHA
    checks['frozen_identity']=reg.get('registry_hash')==REGISTRY_HASH and selfhash(reg,'registry_hash')==REGISTRY_HASH and freeze.get('design_freeze_hash')==FREEZE_HASH and freeze.get('definition_registry_hash')==REGISTRY_HASH
    checks['gap_evidence_identity']=gap.get('report_hash')==GAP_REPORT_HASH and selfhash(gap,'report_hash')==GAP_REPORT_HASH and gap.get('decision_required') is False and gap.get('design_change_required') is False
    checks['fix_evidence_identity']=fix.get('report_hash')==FIX_REPORT_HASH and selfhash(fix,'report_hash')==FIX_REPORT_HASH and fix.get('fixed_engine_sha256')==ENGINE_SHA and fix.get('oos_2024_accessed') is False
    checks['base_audit_pass']=base.get('status')=='PASS' and base.get('phase')=='ENGINE_TECHNICAL_CANDIDATE_AUDIT' and base.get('hashes',{}).get('engine_sha256')==ENGINE_SHA
    checks['fvg_causal_retirement_present']="fvg_terminal=" in text and "group6__fvg_state_transitions" in text and "lower(event_type)='traversed'" in text and "lower(directional_validity)='invalidated'" in text
    checks['range_causal_retirement_present']='zone_invalidations' in text and 'features.get("lower_zone_id")' in text and 'features.get("upper_zone_id")' in text and 'bisect.bisect_right(times,start)' in text
    checks['active_predicate_retirement_present']='if inactive is not None and int(availability) >= int(inactive): return False' in text
    checks['right_censoring_preserved']='inactive=fvg_terminal.get(str(r["id"])) if t=="fvg_events" else None' in text
    checks['regression_suite_present']=all(x in tests for x in ['test_group6_fvg_retires_at_first_traversed_invalidated_transition','test_group8_bounded_range_retires_at_locked_zone_invalidation','test_nonterminal_group6_objects_remain_right_censored'])
    g=status.get('blocking_gap',{})
    checks['fail_closed_pre_refreeze']=status.get('status')=='PA7_LIFECYCLE_GAP008_FIXED_PENDING_TECHNICAL_REFREEZE' and g.get('gap_id')==GAP_ID and g.get('status')=='FIXED_PENDING_TECHNICAL_REFREEZE' and g.get('fixed_engine_sha256')==ENGINE_SHA and not status.get('engine_build_authorized') and not status.get('annual_execution_2023_authorized') and not status.get('annual_execution_2024_authorized') and status.get('officially_closed') is False
    checks['no_oos_logic_added']=fix.get('oos_2024_accessed') is False and 'year == 2024' not in text and 'year==2024' not in text
    failures=[k for k,v in checks.items() if not v]
    report:dict[str,Any]={'format_version':1,'phase':'PA7_LIFECYCLE_RETIREMENT_TECHNICAL_AUDIT','status':'PASS' if not failures else 'FAIL','gap_id':GAP_ID,'engine_sha256':sha(engine_path),'definition_registry_hash':reg.get('registry_hash'),'design_freeze_hash':freeze.get('design_freeze_hash'),'gap_report_hash':gap.get('report_hash'),'fix_report_hash':fix.get('report_hash'),'base_technical_audit_hash':base.get('report_hash'),'checks':checks,'hashes':{'engine_sha256':sha(engine_path),'regression_sha256':sha(test_path),'frozen_config_sha256':sha(root/'FROZEN_CONFIG.json'),'schema_sha256':sha(root/'02_SCHEMA.sql'),'upstream_contract_sha256':sha(root/'contracts/UPSTREAM_INPUT_CONTRACT.json')},'2024_accessed':False,'failures':failures}
    report['report_hash']=stable(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if not failures else 1
if __name__=='__main__':raise SystemExit(main())
