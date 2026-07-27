#!/usr/bin/env python3
"""Finalize frozen Group 8 2024 OOS under the FREE lossless-sharded contract."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
from typing import Any
from group8_finalize_annual_2023_sharded import stable,verify_self_hash

def load(p:Path)->dict[str,Any]:return json.loads(p.read_text())
def shaf(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
def require_2024(r:dict[str,Any],label:str):
 verify_self_hash(r,label)
 if int(r.get('year',0))!=2024:raise RuntimeError(f'{label}:wrong_year')
 if r.get('free_only') is not True or r.get('paid_runner_used') is True or r.get('paid_service_used') is True:raise RuntimeError(f'{label}:not_free_only')
 if r.get('oos_2024_accessed') is not True:raise RuntimeError(f'{label}:oos_access_not_recorded')

def finalize(*,group8_root:Path,core_release_report:Path,pa7_release_report:Path,reconstruction_reports:list[Path],union_reports:list[Path],manifest_output:Path)->dict[str,Any]:
 root=group8_root.resolve();sp=root/'STATUS.json';s=load(sp);build=load(root/'ENGINE_BUILD_MANIFEST.json');freeze=load(root/'OOS_FREEZE_MANIFEST.json');a23=load(root/'ANNUAL_2023_VALIDATION_MANIFEST.json');contract=load(root/'SHARDED_STORAGE_CONTRACT.json');core=load(core_release_report);pa7=load(pa7_release_report);recs=[load(x) for x in reconstruction_reports];unions=[load(x) for x in union_reports];fail=[]
 if s.get('officially_closed') is not False:fail.append('group8_already_closed')
 if s.get('status')!='OOS_2024_FROZEN_AND_AUTHORIZED_FREE_SHARDED':fail.append('wrong_oos_phase')
 if s.get('annual_execution_2024_authorized') is not True or s.get('annual_execution_2023_authorized') is not False:fail.append('oos_authorization_invalid')
 if freeze.get('status')!='FROZEN_FOR_2024_OOS_FREE_SHARDED' or int(freeze.get('format_version',0))<3:fail.append('sharded_oos_freeze_missing')
 if freeze.get('annual_2023_manifest_hash')!=a23.get('manifest_hash'):fail.append('freeze_2023_binding_mismatch')
 if freeze.get('engine_build_manifest_hash')!=build.get('manifest_hash'):fail.append('freeze_build_binding_mismatch')
 if freeze.get('storage_contract_hash')!=contract.get('storage_contract_hash'):fail.append('freeze_storage_contract_mismatch')
 for rel,ident in freeze.get('identities',{}).items():
  p=root/rel
  if not p.is_file() or p.stat().st_size!=int(ident['size_bytes']) or shaf(p)!=ident['sha256']:fail.append(f'frozen_identity_drift:{rel}')
 for label,r in (('core',core),('pa7',pa7)):
  try:require_2024(r,label)
  except RuntimeError as e:fail.append(str(e))
 if core.get('status')!='PASS' or core.get('artifact_kind')!='GROUP8_ANNUAL_CORE':fail.append('core_release_not_pass')
 if pa7.get('status')!='PASS' or pa7.get('artifact_kind')!='GROUP8_PA7_ANNUAL_2024_OOS_SHARDED_RELEASE' or pa7.get('complete_once_only_coverage') is not True:fail.append('pa7_release_not_pass')
 frozen_buckets=freeze.get('pa7_partition_policy',{}).get('bucket_counts')
 if pa7.get('bucket_plan')!=frozen_buckets:fail.append('2024_bucket_plan_drift_from_pre_oos_freeze')
 if len(recs)!=3 or len(unions)!=3:fail.append('three_reconstructions_and_unions_required')
 recsha=[];unionsha=[]
 for i,r in enumerate(recs):
  try:require_2024(r,f'reconstruction_{i}')
  except RuntimeError as e:fail.append(str(e))
  if r.get('status')!='PASS' or r.get('no_trading_outputs') is not True or r.get('causality') not in ('PASS',True) or int(r.get('unresolved_group8_reference_count',-1))!=0:fail.append(f'reconstruction_{i}:integrity')
  recsha.append(r.get('logical_sha256'))
 for i,r in enumerate(unions):
  try:require_2024(r,f'union_{i}')
  except RuntimeError as e:fail.append(str(e))
  if r.get('status')!='PASS' or r.get('full_annual_union') is not True or int(r.get('unresolved_group8_reference_count',-1))!=0 or int(r.get('duplicate_domain_id_count',-1))!=0 or int(r.get('registry_conflict_count',-1))!=0:fail.append(f'union_{i}:integrity')
  unionsha.append(r.get('global_logical_sha256'))
 if None in recsha or len(set(recsha))!=1:fail.append('oos_reconstruction_drift')
 if None in unionsha or len(set(unionsha))!=1:fail.append('oos_full_union_drift')
 if fail:raise RuntimeError(';'.join(fail))
 m={'format_version':3,'status':'ANNUAL_2024_OOS_PASS','group':8,'year':2024,'oos':True,'physical_storage_mode':'FREE_LOSSLESS_SHARDED','engine_version':build['engine_version'],'schema_version':build['schema_version'],'config_id':build['config_id'],'oos_freeze_manifest_hash':freeze['manifest_hash'],'annual_2023_manifest_hash':a23['manifest_hash'],'engine_build_manifest_hash':build['manifest_hash'],'engine_sha256':freeze['engine_sha256'],'postprocessor_sha256':freeze['postprocessor_sha256'],'materializer_sha256':freeze['materializer_sha256'],'design_freeze_hash':freeze['design_freeze_hash'],'storage_contract_hash':freeze['storage_contract_hash'],'core_release':{'report_hash':core['report_hash'],'release_tag':core.get('release_tag'),'logical_sha256':core.get('logical_sha256'),'definition_coverage':core.get('definition_coverage')},'pa7_release':{'report_hash':pa7['report_hash'],'release_tag':pa7.get('release_tag'),'shard_count':pa7.get('shard_count'),'candidate_rows':pa7.get('candidate_rows'),'state_rows':pa7.get('state_rows'),'definition_coverage':pa7.get('definition_coverage'),'complete_once_only_coverage':True},'reconstruction':{'logical_sha256':recsha[0],'report_hashes':[r['report_hash'] for r in recs],'idempotence':'PASS','clean_reconstruction':'PASS'},'full_union':{'global_logical_sha256':unionsha[0],'report_hashes':[r['report_hash'] for r in unions],'table_row_counts':unions[0].get('table_row_counts',{}),'table_logical_sha256':unions[0].get('table_logical_sha256',{}),'unresolved_group8_reference_count':0,'duplicate_domain_id_count':0,'registry_conflict_count':0},'logical_fingerprint':unionsha[0],'causality':'PASS','no_lookahead':'PASS','no_backdating':'PASS','duplicate_prevention':'PASS','upstream_reference_integrity':'PASS','no_trading_outputs':True,'frozen_identity_drift':False,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':True,'policy':'Frozen 2024 OOS passed under the exact pre-OOS FREE lossless-sharded identities. No result-conditioned mutation is permitted.'};m['manifest_hash']=stable(m);manifest_output.parent.mkdir(parents=True,exist_ok=True);manifest_output.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
 s['annual_validation_2024_oos']={'status':'PASS','manifest_hash':m['manifest_hash'],'logical_fingerprint':m['logical_fingerprint'],'oos_freeze_manifest_hash':freeze['manifest_hash'],'engine_sha256':m['engine_sha256'],'storage_contract_hash':m['storage_contract_hash'],'config_id':m['config_id']};s['annual_execution_authorized']=False;s['annual_execution_2023_authorized']=False;s['annual_execution_2024_authorized']=False;s['status']='ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED';sp.write_text(json.dumps(s,indent=2,sort_keys=True)+'\n');return m

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--core-release-report',type=Path,required=True);p.add_argument('--pa7-release-report',type=Path,required=True);p.add_argument('--reconstruction-report',type=Path,action='append',required=True);p.add_argument('--union-report',type=Path,action='append',required=True);p.add_argument('--manifest-output',type=Path,required=True);a=p.parse_args();m=finalize(group8_root=a.group8_root,core_release_report=a.core_release_report,pa7_release_report=a.pa7_release_report,reconstruction_reports=a.reconstruction_report,union_reports=a.union_report,manifest_output=a.manifest_output);print(json.dumps({'status':m['status'],'manifest_hash':m['manifest_hash'],'logical_fingerprint':m['logical_fingerprint']},indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
