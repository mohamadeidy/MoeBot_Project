#!/usr/bin/env python3
"""Re-freeze Group 8 technical candidate after G8-ICT-LOCKED-CONTEXT-005.

This is fail-closed and may only run from the specific fixed-pending-refreeze
state. It preserves the frozen design/config/schema/upstream lineage and creates
new exact technical identities, including the strengthened annual validator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from moebot_group8_engine_v0_8_0 import ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, stable_hash, sha256_file

GAP_ID="G8-ICT-LOCKED-CONTEXT-005"
DIAGNOSTIC_HASH="78ff7696f1140a7dc60b7f495db8898eba341201c1ae5036c37b771039915e81"


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--manifest-output',type=Path,required=True);a=p.parse_args()
    root=a.group8_root.resolve();audit=json.loads(a.audit.read_text());status_path=root/'STATUS.json';status=json.loads(status_path.read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text());gap=json.loads((root/'reports/28_LOCKED_CONTEXT_GAP_ANALYSIS.json').read_text())
    if audit.get('status')!='PASS':raise SystemExit('technical audit is not PASS')
    if status.get('design_frozen') is not True:raise SystemExit('design is not frozen')
    if status.get('status')!='BLOCKING_GAP_G8_ICT_LOCKED_CONTEXT_FIXED_PENDING_TECHNICAL_REFREEZE':raise SystemExit('wrong refreeze phase')
    b=status.get('blocking_gap',{})
    if b.get('gap_id')!=GAP_ID or b.get('status')!='FIXED_PENDING_REFREEZE' or b.get('diagnostic_report_hash')!=DIAGNOSTIC_HASH:raise SystemExit('blocking gap identity/state mismatch')
    if gap.get('gap_id')!=GAP_ID or gap.get('status')!='BLOCKING_GAP_FIXED_PENDING_TECHNICAL_REFREEZE' or gap.get('diagnostic_report_hash')!=DIAGNOSTIC_HASH:raise SystemExit('gap analysis identity/state mismatch')
    for k in ('definitions_changed','thresholds_changed','schema_changed','upstream_changed'):
        if gap.get(k) is not False or b.get(k) is not False:raise SystemExit(f'frozen semantics mutation flag:{k}')
    if status.get('annual_execution_authorized') or status.get('annual_execution_2023_authorized') or status.get('annual_execution_2024_authorized'):raise SystemExit('annual execution must remain revoked during refreeze')
    if status.get('annual_execution_2024_authorized') is True:raise SystemExit('2024 OOS was prematurely authorized')

    files={
        'engine':'code/moebot_group8_engine_v0_8_0.py',
        'materializer':'code/group8_materialize_inputs.py',
        'postprocessor':'code/group8_postprocess_v0_8_0.py',
        'annual_validator':'code/group8_annual_validation.py',
        'tests':'tests/test_group8_engine_v0_8_0.py',
        'lifecycle_tests':'tests/test_group8_lifecycle_persistence_v0_8_0.py',
        'technical_audit':'reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json',
        'locked_context_gap_analysis':'reports/28_LOCKED_CONTEXT_GAP_ANALYSIS.json',
        'locked_context_gap_diagnostic':'reports/27_LOCKED_CONTEXT_GAP_DIAGNOSTIC.json',
        'schema':'02_SCHEMA.sql',
        'definitions':'01_DEFINITION_REGISTRY.json',
        'config':'FROZEN_CONFIG.json',
        'upstream_contract':'contracts/UPSTREAM_INPUT_CONTRACT.json',
    }
    identities={k:{'path':v,'sha256':sha256_file(root/v),'size_bytes':(root/v).stat().st_size} for k,v in files.items()}
    previous=b.get('previous_engine_sha256')
    if identities['engine']['sha256']==previous:raise SystemExit('corrected engine identity did not change from blocked candidate')
    if audit.get('hashes',{}).get('engine_sha256')!=identities['engine']['sha256']:raise SystemExit('audit engine identity mismatch')
    if audit.get('hashes',{}).get('postprocessor_sha256')!=identities['postprocessor']['sha256']:raise SystemExit('audit postprocessor identity mismatch')
    if audit.get('hashes',{}).get('annual_validator_sha256')!=identities['annual_validator']['sha256']:raise SystemExit('audit annual-validator identity mismatch')
    if audit.get('checks',{}).get('locked_context_hardening_present') is not True:raise SystemExit('locked-context hardening audit did not pass')
    if audit.get('checks',{}).get('locked_context_gap_identity_valid') is not True:raise SystemExit('locked-context gap identity audit did not pass')

    manifest={
        'format_version':2,'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,
        'design_freeze_hash':freeze['design_freeze_hash'],'definition_registry_hash':freeze['definition_registry_hash'],'upstream_contract_hash':freeze['upstream_contract_hash'],
        'technical_audit_hash':audit['report_hash'],'identities':identities,
        'closed_blocking_gap':{'gap_id':GAP_ID,'diagnostic_report_hash':DIAGNOSTIC_HASH,'gap_analysis_report_hash':gap['report_hash'],'previous_engine_sha256':previous,'corrected_engine_sha256':identities['engine']['sha256']},
        'annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,
        'policy':'2023 in-sample engineering validation re-authorized only after the locked-context blocking gap was fixed and exact technical identities re-frozen; 2024 remains forbidden until post-2023 OOS freeze.',
    }
    manifest['manifest_hash']=stable_hash(manifest);a.manifest_output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    status['engine_build']={'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'engine_sha256':identities['engine']['sha256'],'materializer_sha256':identities['materializer']['sha256'],'postprocessor_sha256':identities['postprocessor']['sha256'],'annual_validator_sha256':identities['annual_validator']['sha256'],'technical_audit_hash':audit['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash'],'closed_gap_id':GAP_ID}
    status['blocking_gap']={**b,'status':'CLOSED_BY_TECHNICAL_REFREEZE','corrected_engine_sha256':identities['engine']['sha256'],'technical_audit_hash':audit['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash']}
    status['engine_build_authorized']=True;status['annual_execution_authorized']=True;status['annual_execution_2023_authorized']=True;status['annual_execution_2024_authorized']=False;status['status']='ENGINE_TECHNICAL_CANDIDATE_PASS_2023_AUTHORIZED';status['officially_closed']=False
    status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'PASS','manifest_hash':manifest['manifest_hash'],'engine_sha256':identities['engine']['sha256'],'annual_validator_sha256':identities['annual_validator']['sha256'],'closed_gap_id':GAP_ID,'2023_authorized':True,'2024_authorized':False},indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
