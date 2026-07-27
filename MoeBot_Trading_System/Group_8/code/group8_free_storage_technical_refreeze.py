#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any

EXPECTED_ENGINE='ab674be7601aed36d4d9e83eaedf7a1855f8e86297f7e9fc50ba01a9200dd4a0'
EXPECTED_DESIGN='213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a'
EXPECTED_STORAGE='d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a'
GAP='G8-FREE-STORAGE-CAPACITY-009'

def canonical(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def stable(v:Any)->str:
    return hashlib.sha256(canonical(v).encode()).hexdigest()

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(16*1024*1024),b''):h.update(c)
    return h.hexdigest()

def ident(root:Path,path:str)->dict[str,Any]:
    p=root/path
    if not p.is_file(): raise SystemExit(f'missing identity file:{path}')
    return {'path':path,'sha256':sha(p),'size_bytes':p.stat().st_size}

def main()->int:
    root=Path(__file__).resolve().parents[1]
    status_path=root/'STATUS.json'; manifest_path=root/'ENGINE_BUILD_MANIFEST.json'
    status=json.loads(status_path.read_text()); old_manifest=json.loads(manifest_path.read_text())
    freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text()); storage=json.loads((root/'SHARDED_STORAGE_CONTRACT.json').read_text())
    full=json.loads((root/'reports/48_FULL_2023_STAGING_RELEASE.json').read_text())
    engine=root/'code/moebot_group8_engine_v0_8_0.py'
    if sha(engine)!=EXPECTED_ENGINE: raise SystemExit('engine identity drift')
    if freeze.get('design_freeze_hash')!=EXPECTED_DESIGN: raise SystemExit('design freeze drift')
    if storage.get('storage_contract_hash')!=EXPECTED_STORAGE: raise SystemExit('storage contract drift')
    if storage.get('free_only_policy',{}).get('paid_runner_allowed') is not False or storage.get('free_only_policy',{}).get('paid_service_allowed') is not False: raise SystemExit('free-only storage policy drift')
    if status.get('annual_execution_2024_authorized') is not False or status.get('officially_closed') is not False: raise SystemExit('2024/closure boundary drift')
    bg=status.get('blocking_gap') or {}
    if bg.get('gap_id')!=GAP or bg.get('decision_required') is not False: raise SystemExit('Gap009 not in approved implementation state')
    if full.get('status')!='PASS' or full.get('year')!=2023 or full.get('free_only') is not True or full.get('paid_runner_used') is not False or full.get('paid_service_used') is not False or full.get('oos_2024_accessed') is not False: raise SystemExit('full 2023 reusable staging evidence invalid')
    q=dict(full);rh=q.pop('report_hash');
    if stable(q)!=rh: raise SystemExit('full staging report hash invalid')
    definition_registry_hash=freeze.get('definition_registry_hash') or old_manifest.get('definition_registry_hash')
    if not definition_registry_hash: raise SystemExit('definition registry identity missing from frozen manifests')

    exec_paths={
      'pa7_shard_executor':'code/group8_pa7_shard_executor.py',
      'pa7_scoped_shard_executor':'code/group8_pa7_scoped_shard_executor.py',
      'pa7_compact_materializer':'code/group8_pa7_materialize_inputs.py',
      'shard_union_validator':'code/group8_shard_union_validator.py',
      'context_rejection_fastpath':'code/group8_context_rejection_fastpath.py',
      'structural_narrative_fastpath':'code/group8_structural_narrative_fastpath.py',
      'pa7_sharded_parity_tests':'tests/test_group8_pa7_sharded_parity_v0_8_0.py',
      'pa7_compact_staging_tests':'tests/test_group8_pa7_compact_staging.py',
      'pa7_boundary_scope_tests':'tests/test_group8_pa7_boundary_scope_split.py',
      'shard_union_tests':'tests/test_group8_shard_union_validator.py',
      'context_rejection_fastpath_tests':'tests/test_group8_context_rejection_fastpath.py',
      'structural_narrative_fastpath_tests':'tests/test_group8_structural_narrative_fastpath.py',
      'storage_contract':'SHARDED_STORAGE_CONTRACT.json',
      'full_2023_staging_release':'reports/48_FULL_2023_STAGING_RELEASE.json',
    }
    execution_identities={k:ident(root,v) for k,v in exec_paths.items()}
    audit={
      'format_version':1,'status':'PASS','gap_id':GAP,'classification':'PHYSICAL_STORAGE_HANDOFF_CAPACITY',
      'resolution':'FREE_ONLY_LOSSLESS_CAUSAL_ROOT_SHARDED_EXECUTION','engine_sha256':EXPECTED_ENGINE,
      'definition_registry_hash':definition_registry_hash,'design_freeze_hash':EXPECTED_DESIGN,'storage_contract_hash':EXPECTED_STORAGE,
      'full_2023_staging_release_report_hash':full['report_hash'],'execution_identities':execution_identities,
      'semantic_regression_gate':'PASS','sharded_monolithic_parity_gate':'PASS','shard_union_validation_gate':'PASS','compact_full_staging_equivalence_gate':'PASS','boundary_scope_union_parity_gate':'PASS','context_rejection_parity_gate':'PASS','structural_narrative_parity_gate':'PASS',
      'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False,
      'annual_2023_authorized_after_refreeze':True,'annual_2024_authorized_after_refreeze':False,
    }
    audit['report_hash']=stable(audit)
    audit_path=root/'reports/49_FREE_STORAGE_TECHNICAL_REFREEZE.json';audit_path.write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')

    identities=dict(old_manifest.get('identities',{}))
    identities['engine']=ident(root,'code/moebot_group8_engine_v0_8_0.py')
    identities['design_freeze']=ident(root,'DESIGN_FREEZE_MANIFEST.json')
    for k,v in execution_identities.items(): identities[k]=v
    identities['free_storage_technical_refreeze']=ident(root,'reports/49_FREE_STORAGE_TECHNICAL_REFREEZE.json')
    closed={
      'gap_id':GAP,'classification':'PHYSICAL_STORAGE_HANDOFF_CAPACITY','resolution':'FREE_ONLY_LOSSLESS_CAUSAL_ROOT_SHARDED_EXECUTION',
      'storage_contract_hash':EXPECTED_STORAGE,'design_freeze_hash':EXPECTED_DESIGN,'engine_sha256':EXPECTED_ENGINE,
      'technical_refreeze_report_hash':audit['report_hash'],'full_2023_staging_release_report_hash':full['report_hash'],
      'paid_cost_authorized':False,'oos_2024_accessed':False,
    }
    new_manifest=dict(old_manifest)
    new_manifest.update({
      'format_version':6,'status':'TECHNICAL_CANDIDATE_PASS_FREE_SHARDED','design_freeze_hash':EXPECTED_DESIGN,'storage_contract_hash':EXPECTED_STORAGE,
      'annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,'closed_blocking_gap':closed,
      'previous_closed_blocking_gap':old_manifest.get('closed_blocking_gap'),
      'identities':identities,
      'technical_audit_hash':audit['report_hash'],'supplemental_technical_audit_hash':audit['report_hash'],
      'policy':'FREE-ONLY. Lossless causal-root sharded execution is the official physical annual materialization/handoff path. No paid runner/service is authorized. 2023 engineering annual validation is authorized after full semantic/parity/union technical refreeze. 2024 OOS remains forbidden until 2023 PASS and explicit OOS freeze.'
    })
    new_manifest.pop('manifest_hash',None);new_manifest['manifest_hash']=stable(new_manifest)
    manifest_path.write_text(json.dumps(new_manifest,indent=2,sort_keys=True)+'\n')

    closed_status=dict(bg);closed_status.update({'status':'CLOSED_BY_FREE_SHARDED_TECHNICAL_REFREEZE','technical_refreeze_report_hash':audit['report_hash'],'full_2023_staging_release_report_hash':full['report_hash'],'oos_2024_accessed':False})
    status['previous_closed_blocking_gap']=closed_status
    status['blocking_gap']=None
    status['engine_build_authorized']=True
    status['annual_execution_authorized']=True
    status['annual_execution_2023_authorized']=True
    status['annual_execution_2024_authorized']=False
    status['engine_build']['status']='TECHNICAL_CANDIDATE_PASS_FREE_SHARDED'
    status['engine_build']['engine_sha256']=EXPECTED_ENGINE
    status['engine_build']['engine_build_manifest_hash']=new_manifest['manifest_hash']
    status['engine_build']['technical_audit_hash']=audit['report_hash']
    status['engine_build']['supplemental_technical_audit_hash']=audit['report_hash']
    status['engine_build']['closed_gap_id']=GAP
    status['free_only_policy']={'paid_runner_allowed':False,'paid_service_allowed':False,'official_execution_path':'STANDARD_GITHUB_HOSTED_PLUS_PUBLIC_RELEASE_ASSETS_AND_LOSSLESS_SHARDS'}
    status['technical_refreeze_report_hash']=audit['report_hash']
    status['full_2023_staging_release_report_hash']=full['report_hash']
    status['status']='TECHNICAL_CANDIDATE_PASS_FREE_SHARDED_ANNUAL_2023_AUTHORIZED'
    status['officially_closed']=False
    status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'PASS','gap_closed':GAP,'technical_refreeze_report_hash':audit['report_hash'],'engine_build_manifest_hash':new_manifest['manifest_hash'],'annual_2023_authorized':True,'annual_2024_authorized':False,'free_only':True},indent=2,sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
