#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path

from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_relevant_catalog import init_catalog,append_pass1,append_pass2,finalize as finalize_catalog
from group8_pa7_derived_executor import PA7DerivedEngine
from group8_global_finalizer import Group8GlobalFinalizer
from group8_logical_sidecars import HEX,create_sidecars,merge_prefix,stable as sidecar_stable
from group8_distributed_union_validator import audit_pa7_shard,finalize_distributed_union
from group8_distributed_union_worker_aggregate import finalize_worker_aggregate
from group8_shard_union_validator import validate,stable_hash,sha256_file,EXPECTED_CONTRACT,EXPECTED_FREEZE,EXPECTED_ENGINE
from test_group8_engine_v0_8_0 import ART,make_stage


def _merge_sidecars(t:Path,side_dirs:list[Path],label:str):
 prefixes={'candidate':{},'state':{}};merge_reports={'candidate':{},'state':{}}
 for short in ('candidate','state'):
  for pfx in HEX:
   out=t/f'{label}_{short}_{pfx}.canonical';mr=merge_prefix([sd/f'{short}_{pfx}.pairs' for sd in side_dirs],out);mr['report_hash']=sidecar_stable(mr);rp=t/f'{label}_{short}_{pfx}.merge.json';rp.write_text(json.dumps(mr,indent=2,sort_keys=True)+'\n');prefixes[short][pfx]=out;merge_reports[short][pfx]=rp
 return prefixes,merge_reports


class DistributedUnionValidatorTest(unittest.TestCase):
 def test_exact_full_union_matches_legacy_without_global_id_ledger(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';core=t/'core.sqlite';cat=t/'cat.sqlite';make_stage(stage)
   e=AnnualCoreEngine(staging_db=stage,output_db=core,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(e.run_core()['status'],'PASS')
   finally:e.close()
   self.assertEqual(init_catalog(core,cat)['status'],'PASS');shards=[]
   for tf in ('M15','H1'):
    for scope in ('upstream','group8_range'):
     for b in range(4):
      db=t/f's_{tf}_{scope}_{b}.sqlite';mp=t/f'm_{tf}_{scope}_{b}.json';m=run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=mp);shards.append((db,mp,m))
   for i,(db,_,_) in enumerate(shards):self.assertEqual(append_pass1(cat,db,f's{i}')['status'],'PASS')
   for i,(db,_,_) in enumerate(shards):self.assertEqual(append_pass2(cat,db,f's{i}')['status'],'PASS')
   self.assertEqual(finalize_catalog(cat,t/'cat.json')['status'],'PASS')
   d=PA7DerivedEngine(staging_db=stage,output_db=core,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(d.run_derived()['status'],'PASS')
   finally:d.close()
   g=Group8GlobalFinalizer(staging_db=stage,output_db=core,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(g.run_global_finalizer()['status'],'PASS')
   finally:g.close()

   core_payload={'shard_id':'fixture_final_core','year':2023,'symbol':'XAUUSD_','storage_contract_hash':EXPECTED_CONTRACT,'design_freeze_hash':EXPECTED_FREEZE,'engine_sha256':EXPECTED_ENGINE,'sha256':sha256_file(core),'file_size_bytes':core.stat().st_size};core_payload['manifest_hash']=stable_hash(core_payload);core_mp=t/'core.manifest.json';core_mp.write_text(json.dumps(core_payload,indent=2,sort_keys=True)+'\n')
   idx={'year':2023,'symbol':'XAUUSD_','full_annual_union':True,'shards':[{'database':str(core),'manifest':str(core_mp)}]+[{'database':str(db),'manifest':str(mp)} for db,mp,_ in shards]};idxp=t/'legacy-index.json';idxp.write_text(json.dumps(idx));legacy=validate(idxp,t/'legacy.json');self.assertEqual(legacy['status'],'PASS');self.assertEqual(legacy['unresolved_group8_reference_count'],0)

   release={'format_version':2,'status':'PASS','artifact_kind':'GROUP8_PA7_ANNUAL_2023_SHARDED_RELEASE','year':2023,'complete_once_only_coverage':True,'shard_count':len(shards),'shards':[{'shard_id':m['shard_id'],'manifest_hash':m['manifest_hash'],'sha256':m['sha256'],'file_size_bytes':m['file_size_bytes'],'table_row_counts':m['table_row_counts']} for _,_,m in shards],'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False};release['report_hash']=stable_hash(release);releasep=t/'release.json';releasep.write_text(json.dumps(release,indent=2,sort_keys=True)+'\n')
   audit_paths=[]
   for i,(db,mp,_) in enumerate(shards):
    r=audit_pa7_shard(database=db,manifest_path=mp,core_db=core,year=2023,symbol='XAUUSD_',group8_root=ART);p=t/f'audit{i}.json';p.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');audit_paths.append(p)
   refp=t/'refs.json';refp.write_text(json.dumps(legacy,indent=2,sort_keys=True)+'\n')

   # Reference distributed mode: one sidecar report per physical database.
   source_dbs=[core]+[db for db,_,_ in shards];side_dirs=[];side_reports=[]
   for i,db in enumerate(source_dbs):
    sd=t/f'side{i}';r=create_sidecars([db],sd);rp=t/f'side{i}.json';rp.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');side_dirs.append(sd);side_reports.append(rp)
   prefixes,merge_reports=_merge_sidecars(t,side_dirs,'single')
   got=finalize_distributed_union(core_db=core,pa7_release_report=releasep,core_reference_report=refp,shard_audit_paths=audit_paths,sidecar_report_paths=side_reports,candidate_prefixes=prefixes['candidate'],state_prefixes=prefixes['state'],candidate_merge_reports=merge_reports['candidate'],state_merge_reports=merge_reports['state'],year=2023,symbol='XAUUSD_',output=t/'distributed.json')
   self.assertEqual(got['status'],'PASS');self.assertEqual(got['table_row_counts'],legacy['table_row_counts']);self.assertEqual(got['table_logical_sha256'],legacy['table_logical_sha256']);self.assertEqual(got['global_logical_sha256'],legacy['global_logical_sha256']);self.assertEqual(got['duplicate_domain_id_count'],0);self.assertEqual(got['registry_conflict_count'],0);self.assertEqual(got['unresolved_group8_reference_count'],0)

   # Production mode: one core sidecar + worker-like sidecars each covering several DBs.
   groups=[[core]];pa7=[db for db,_,_ in shards]
   for i in range(0,len(pa7),4):groups.append(pa7[i:i+4])
   agg_dirs=[];agg_reports=[]
   for i,dbs in enumerate(groups):
    sd=t/f'aggside{i}';r=create_sidecars(dbs,sd);self.assertEqual(r['database_count'],len(dbs));rp=t/f'aggside{i}.json';rp.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');agg_dirs.append(sd);agg_reports.append(rp)
   aprefix,amerge=_merge_sidecars(t,agg_dirs,'aggregate')
   agg=finalize_worker_aggregate(core_db=core,pa7_release_report=releasep,core_reference_report=refp,shard_audit_paths=audit_paths,sidecar_report_paths=agg_reports,candidate_prefixes=aprefix['candidate'],state_prefixes=aprefix['state'],candidate_merge_reports=amerge['candidate'],state_merge_reports=amerge['state'],year=2023,symbol='XAUUSD_',output=t/'aggregate.json')
   self.assertEqual(agg['status'],'PASS');self.assertEqual(agg['source_database_count'],len(source_dbs));self.assertEqual(agg['table_row_counts'],legacy['table_row_counts']);self.assertEqual(agg['table_logical_sha256'],legacy['table_logical_sha256']);self.assertEqual(agg['global_logical_sha256'],legacy['global_logical_sha256'])

   with self.assertRaisesRegex(RuntimeError,'sidecar source database coverage mismatch'):
    finalize_worker_aggregate(core_db=core,pa7_release_report=releasep,core_reference_report=refp,shard_audit_paths=audit_paths,sidecar_report_paths=agg_reports[:-1],candidate_prefixes=aprefix['candidate'],state_prefixes=aprefix['state'],candidate_merge_reports=amerge['candidate'],state_merge_reports=amerge['state'],year=2023,symbol='XAUUSD_',output=t/'bad.json')

if __name__=='__main__':unittest.main()
