#!/usr/bin/env python3
"""Exact technical re-freeze after PA7 lifecycle-retirement Gap008 fix."""
from __future__ import annotations

import argparse, json
from pathlib import Path
from moebot_group8_engine_v0_8_0 import ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, sha256_file, stable_hash

GAP_ID='G8-PA7-LIFECYCLE-RETIREMENT-008'
ENGINE_SHA='44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b'
REGISTRY_HASH='70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9'
FREEZE_HASH='7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4'
GAP_REPORT_HASH='cdd862c7d725858be54c326300404811deee6245ddcb0da3d32a4be68b4122a8'
FIX_REPORT_HASH='b35cee4b2f1500ab5a20e8a1bfb8e0a928047d2875e6c5c2c627e8383af0fc8d'


def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--base-technical-audit',type=Path,required=True);p.add_argument('--lifecycle-technical-audit',type=Path,required=True);p.add_argument('--manifest-output',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve()
 status_path=root/'STATUS.json';status=json.loads(status_path.read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text());reg=json.loads((root/'01_DEFINITION_REGISTRY.json').read_text());old=json.loads(a.manifest_output.read_text());base=json.loads(a.base_technical_audit.read_text());life=json.loads(a.lifecycle_technical_audit.read_text());gap=json.loads((root/'reports/40_PA7_LIFECYCLE_RETIREMENT_GAP.json').read_text());fix=json.loads((root/'reports/41_PA7_LIFECYCLE_RETIREMENT_FIX.json').read_text())
 if sha256_file(root/'code/moebot_group8_engine_v0_8_0.py')!=ENGINE_SHA:raise SystemExit('fixed engine identity mismatch')
 if freeze.get('design_freeze_hash')!=FREEZE_HASH or freeze.get('definition_registry_hash')!=REGISTRY_HASH or reg.get('registry_hash')!=REGISTRY_HASH:raise SystemExit('frozen identity mismatch')
 g=status.get('blocking_gap',{})
 if status.get('status')!='PA7_LIFECYCLE_GAP008_FIXED_PENDING_TECHNICAL_REFREEZE' or g.get('gap_id')!=GAP_ID or g.get('status')!='FIXED_PENDING_TECHNICAL_REFREEZE':raise SystemExit('wrong refreeze phase')
 if any(status.get(k) for k in ('engine_build_authorized','annual_execution_authorized','annual_execution_2023_authorized','annual_execution_2024_authorized')):raise SystemExit('must remain fail-closed before refreeze')
 if gap.get('report_hash')!=GAP_REPORT_HASH or fix.get('report_hash')!=FIX_REPORT_HASH or fix.get('fixed_engine_sha256')!=ENGINE_SHA:raise SystemExit('Gap008 evidence identity mismatch')
 if base.get('status')!='PASS' or base.get('phase')!='ENGINE_TECHNICAL_CANDIDATE_AUDIT' or base.get('hashes',{}).get('engine_sha256')!=ENGINE_SHA:raise SystemExit('base technical audit not PASS on fixed engine')
 if life.get('status')!='PASS' or life.get('phase')!='PA7_LIFECYCLE_RETIREMENT_TECHNICAL_AUDIT' or life.get('engine_sha256')!=ENGINE_SHA or life.get('gap_id')!=GAP_ID:raise SystemExit('lifecycle technical audit not PASS')
 if life.get('base_technical_audit_hash')!=base.get('report_hash') or life.get('gap_report_hash')!=GAP_REPORT_HASH or life.get('fix_report_hash')!=FIX_REPORT_HASH:raise SystemExit('audit evidence lineage mismatch')
 if fix.get('oos_2024_accessed') is not False or life.get('2024_accessed') is not False:raise SystemExit('2024 access declared')

 files={
  'engine':'code/moebot_group8_engine_v0_8_0.py','materializer':'code/group8_materialize_inputs.py','postprocessor':'code/group8_postprocess_v0_8_0.py','annual_validator':'code/group8_annual_validation.py','tests':'tests/test_group8_engine_v0_8_0.py','lifecycle_tests':'tests/test_group8_lifecycle_persistence_v0_8_0.py','pa7_timeframe_tests':'tests/test_group8_breakout_timeframe_isolation_v0_8_0.py','pa7_transition_tests':'tests/test_group8_pa7_transition_event_v0_8_0.py','pa7_lifecycle_retirement_tests':'tests/test_group8_pa7_lifecycle_retirement_v0_8_0.py','technical_audit':'reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json','pa7_lifecycle_technical_audit':'reports/42_PA7_LIFECYCLE_RETIREMENT_TECHNICAL_AUDIT.json','pa7_lifecycle_gap':'reports/40_PA7_LIFECYCLE_RETIREMENT_GAP.json','pa7_lifecycle_fix':'reports/41_PA7_LIFECYCLE_RETIREMENT_FIX.json','pa7_design_amendment':'reports/37_PA7_TRANSITION_EVENT_DESIGN_AMENDMENT.json','pa7_enumeration_blocker':'reports/36_PA7_ENUMERATION_DESIGN_BLOCKER.json','transition_count_diagnostic':'reports/39A_PA7_TRANSITION_COUNTONLY_DIAGNOSTIC.json','schema':'02_SCHEMA.sql','definitions':'01_DEFINITION_REGISTRY.json','design_freeze':'DESIGN_FREEZE_MANIFEST.json','config':'FROZEN_CONFIG.json','upstream_contract':'contracts/UPSTREAM_INPUT_CONTRACT.json'}
 identities={name:{'path':rel,'sha256':sha256_file(root/rel),'size_bytes':(root/rel).stat().st_size} for name,rel in files.items()}
 if identities['engine']['sha256']!=ENGINE_SHA:raise SystemExit('engine drift')
 previous_closed=old.get('closed_blocking_gap')
 if not isinstance(previous_closed,dict) or previous_closed.get('gap_id')!='G8-PA7-ENUMERATION-EXPLOSION-007':raise SystemExit('Gap007 closure lineage missing')
 manifest={'format_version':5,'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'design_freeze_hash':FREEZE_HASH,'definition_registry_hash':REGISTRY_HASH,'upstream_contract_hash':freeze['upstream_contract_hash'],'technical_audit_hash':base['report_hash'],'supplemental_technical_audit_hash':life['report_hash'],'design_amendment_report_hash':'591fff2d535cd27326f37a97ae4278c2a20505101ad8a032804dc657f1866996','identities':identities,'previous_closed_blocking_gap':previous_closed,'closed_blocking_gap':{'gap_id':GAP_ID,'classification':'FROZEN_IMPLEMENTATION_SEMANTIC_VIOLATION','resolution':'CAUSAL_BOUNDARY_LIFECYCLE_RETIREMENT','gap_report_hash':GAP_REPORT_HASH,'fix_report_hash':FIX_REPORT_HASH,'fixed_engine_sha256':ENGINE_SHA,'base_technical_audit_hash':base['report_hash'],'supplemental_technical_audit_hash':life['report_hash']},'annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,'policy':'2023 engineering validation is re-authorized only after Gap008 causal lifecycle retirement fix, complete regression matrices, independent base audit, independent PA7 lifecycle audit, and exact identity refreeze. 2024 remains forbidden until successful 2023 validation and explicit OOS freeze.'}
 manifest['manifest_hash']=stable_hash(manifest);a.manifest_output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
 status['engine_build']={'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'engine_sha256':ENGINE_SHA,'materializer_sha256':identities['materializer']['sha256'],'postprocessor_sha256':identities['postprocessor']['sha256'],'annual_validator_sha256':identities['annual_validator']['sha256'],'technical_audit_hash':base['report_hash'],'supplemental_technical_audit_hash':life['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash'],'closed_gap_id':GAP_ID}
 status['blocking_gap']={**g,'status':'CLOSED_BY_TECHNICAL_REFREEZE','technical_audit_hash':base['report_hash'],'supplemental_technical_audit_hash':life['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash']}
 status['engine_build_authorized']=True;status['annual_execution_authorized']=True;status['annual_execution_2023_authorized']=True;status['annual_execution_2024_authorized']=False;status['status']='ENGINE_TECHNICAL_CANDIDATE_PASS_2023_AUTHORIZED';status['officially_closed']=False
 status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':'PASS','closed_gap_id':GAP_ID,'engine_sha256':ENGINE_SHA,'manifest_hash':manifest['manifest_hash'],'2023_authorized':True,'2024_authorized':False},indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
