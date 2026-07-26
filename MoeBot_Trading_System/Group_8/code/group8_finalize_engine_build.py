#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

from moebot_group8_engine_v0_8_0 import ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, stable_hash, sha256_file

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--manifest-output',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve();audit=json.loads(a.audit.read_text());status_path=root/'STATUS.json';status=json.loads(status_path.read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text())
    if audit.get('status')!='PASS':raise SystemExit('technical audit is not PASS')
    if status.get('design_frozen') is not True or status.get('engine_build_authorized') is not True:raise SystemExit('design freeze does not authorize engine build')
    if status.get('annual_execution_2024_authorized') is True:raise SystemExit('2024 OOS was prematurely authorized')
    files={'engine':'code/moebot_group8_engine_v0_8_0.py','materializer':'code/group8_materialize_inputs.py','tests':'tests/test_group8_engine_v0_8_0.py','technical_audit':'reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json','schema':'02_SCHEMA.sql','definitions':'01_DEFINITION_REGISTRY.json','config':'FROZEN_CONFIG.json','upstream_contract':'contracts/UPSTREAM_INPUT_CONTRACT.json'}
    identities={k:{'path':v,'sha256':sha256_file(root/v),'size_bytes':(root/v).stat().st_size} for k,v in files.items()}
    manifest={'format_version':1,'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'design_freeze_hash':freeze['design_freeze_hash'],'definition_registry_hash':freeze['definition_registry_hash'],'upstream_contract_hash':freeze['upstream_contract_hash'],'technical_audit_hash':audit['report_hash'],'identities':identities,'annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,'policy':'2023 in-sample engineering validation authorized; 2024 remains forbidden until post-2023 engine/config freeze'}
    manifest['manifest_hash']=stable_hash(manifest);a.manifest_output.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    status['engine_build']={'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'engine_sha256':identities['engine']['sha256'],'materializer_sha256':identities['materializer']['sha256'],'technical_audit_hash':audit['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash']}
    status['annual_execution_authorized']=True;status['annual_execution_2023_authorized']=True;status['annual_execution_2024_authorized']=False;status['status']='ENGINE_TECHNICAL_CANDIDATE_PASS_2023_AUTHORIZED';status['officially_closed']=False
    status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':'PASS','manifest_hash':manifest['manifest_hash'],'engine_sha256':identities['engine']['sha256'],'2023_authorized':True,'2024_authorized':False},indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
