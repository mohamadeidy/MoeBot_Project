#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_relevant_catalog import init_catalog,append_pass1,append_pass2,finalize,stable
from group8_pa7_distributed_relevant_catalog import project_bundle,merge_pass1,project_pass2,merge_pass2
from test_group8_engine_v0_8_0 import ART,make_stage

class DistributedRelevantCatalogTest(unittest.TestCase):
 def test_distributed_two_pass_projection_matches_centralized_exactly(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';core=t/'core.sqlite';make_stage(stage)
   e=AnnualCoreEngine(staging_db=stage,output_db=core,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(e.run_core()['status'],'PASS')
   finally:e.close()
   shards=[]
   for tf in ('M15','H1'):
    for scope in ('upstream','group8_range'):
     for b in range(4):
      db=t/f's_{tf}_{scope}_{b}.sqlite';mp=t/f'm_{tf}_{scope}_{b}.json';m=run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=mp);shards.append((m['shard_id'],db,m))
   release={'format_version':3,'status':'PASS','year':2023,'complete_once_only_coverage':True,'shards':[{'shard_id':sid} for sid,_,_ in shards],'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False};release['report_hash']=stable(release);releasep=t/'release.json';releasep.write_text(json.dumps(release,indent=2,sort_keys=True)+'\n')

   central=t/'central.sqlite';init_catalog(core,central)
   for sid,db,_ in shards:self.assertEqual(append_pass1(central,db,sid)['status'],'PASS')
   for sid,db,_ in shards:self.assertEqual(append_pass2(central,db,sid)['status'],'PASS')
   central_report=finalize(central,t/'central.json')

   bundles=[shards[i:i+4] for i in range(0,len(shards),4)];partials=[];exacts=[];projection_reports=[]
   for i,bundle in enumerate(bundles):
    p=t/f'pass1_{i}.sqlite';x=t/f'exact_{i}.sqlite';rp=t/f'projection_{i}.json';r=project_bundle(core_db=core,shards=[(sid,db) for sid,db,_ in bundle],pass1_db=p,exact_db=x,report_path=rp,group8_root=ART,year=2023);self.assertEqual(r['status'],'PASS');partials.append(p);exacts.append(x);projection_reports.append(rp)
   seed=t/'seed.sqlite';seed_report=t/'seed.json';m1=merge_pass1(core_db=core,pa7_release_report=releasep,partial_dbs=partials,projection_report_paths=projection_reports,output_catalog=seed,report_path=seed_report,year=2023);self.assertEqual(m1['status'],'PASS');self.assertEqual(m1['processed_pass1_count'],len(shards))
   deltas=[];delta_reports=[]
   for i,(x,pr) in enumerate(zip(exacts,projection_reports)):
    d=t/f'delta_{i}.sqlite';dr=t/f'delta_{i}.json';r=project_pass2(seed_catalog=seed,exact_db=x,projection_report_path=pr,delta_db=d,report_path=dr,year=2023);self.assertEqual(r['status'],'PASS');deltas.append(d);delta_reports.append(dr)
   distributed=t/'distributed.sqlite';distributed_report=merge_pass2(seed_catalog=seed,pa7_release_report=releasep,delta_dbs=deltas,delta_report_paths=delta_reports,output_catalog=distributed,final_report_path=t/'distributed.json',year=2023)
   for key in ('candidate_rows','definition_counts','target_range_level_count','exhaustion_level_count','pass1_shard_count','pass2_shard_count','logical_candidate_sha256'):
    self.assertEqual(distributed_report[key],central_report[key],key)

   with self.assertRaisesRegex(RuntimeError,'pass1 shard coverage mismatch'):
    merge_pass1(core_db=core,pa7_release_report=releasep,partial_dbs=partials[:-1],projection_report_paths=projection_reports[:-1],output_catalog=t/'badseed.sqlite',report_path=t/'badseed.json',year=2023)

if __name__=='__main__':unittest.main()
