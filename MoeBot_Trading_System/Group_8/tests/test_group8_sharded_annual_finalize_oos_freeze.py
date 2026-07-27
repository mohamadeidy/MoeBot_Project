#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path

import group8_finalize_annual_2023_sharded as fin
import group8_freeze_oos_2024_sharded as frz


def writej(p:Path,v:dict):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def hashed(v:dict)->dict:
    q=dict(v);q['report_hash']=fin.stable(q);return q

class ShardedAnnualFreezeTest(unittest.TestCase):
    def fixture(self,root:Path):
        engine='e'*64;buildhash='b'*64;designhash='d'*64;storage='s'*64
        status={'officially_closed':False,'annual_execution_authorized':True,'annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,'logical_dependency_lineage_id':'lineage','annual_dependency_registry_hash':'areg','free_only_policy':{'paid_runner_allowed':False,'paid_service_allowed':False},'status':'TECHNICAL_CANDIDATE_PASS_FREE_SHARDED_ANNUAL_2023_AUTHORIZED'}
        build={'format_version':6,'status':'TECHNICAL_CANDIDATE_PASS_FREE_SHARDED','annual_execution_2023_authorized':True,'annual_execution_2024_authorized':False,'engine_version':'0.8.0','schema_version':'8.0.0','config_id':'cfg','manifest_hash':buildhash,'design_freeze_hash':designhash,'storage_contract_hash':storage,'identities':{'engine':{'sha256':engine},'postprocessor':{'sha256':'p'*64},'materializer':{'sha256':'m'*64}},'closed_blocking_gap':{'gap_id':'G8-FREE-STORAGE-CAPACITY-009'}}
        writej(root/'STATUS.json',status);writej(root/'ENGINE_BUILD_MANIFEST.json',build);writej(root/'DESIGN_FREEZE_MANIFEST.json',{'design_freeze_hash':designhash});writej(root/'SHARDED_STORAGE_CONTRACT.json',{'storage_contract_hash':storage})
        plan=hashed({'status':'PASS','year':2023,'free_only':True,'oos_2024_accessed':False,'frozen_bucket_plan':{'M1':{'upstream':128,'group8_range':8}}});writej(root/'reports/51_PA7_2023_REAL_SIZING_AND_BUCKET_PLAN.json',plan)
        core=hashed({'status':'PASS','artifact_kind':'GROUP8_ANNUAL_CORE','year':2023,'release_tag':'core','logical_sha256':'c'*64,'raw_sha256':'r'*64,'storage_contract_hash':storage,'engine_sha256':engine,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False});writej(root/'core.json',core)
        pa7=hashed({'status':'PASS','artifact_kind':'GROUP8_PA7_ANNUAL_2023_SHARDED_RELEASE','year':2023,'release_tag':'pa7','shard_count':10,'candidate_rows':100,'state_rows':200,'complete_once_only_coverage':True,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False});writej(root/'pa7.json',pa7)
        for i in range(3):
            rec=hashed({'status':'PASS','year':2023,'logical_sha256':'n'*64,'no_trading_outputs':True,'causality':'PASS','free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False});writej(root/f'rec{i}.json',rec)
            union=hashed({'status':'PASS','year':2023,'full_annual_union':True,'global_logical_sha256':'u'*64,'unresolved_group8_reference_count':0,'duplicate_domain_id_count':0,'registry_conflict_count':0,'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':False});writej(root/f'union{i}.json',union)
        return plan

    def test_finalize_then_freeze_without_2024_access(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root)
            annual=fin.finalize(group8_root=root,core_release_report=root/'core.json',pa7_release_report=root/'pa7.json',reconstruction_reports=[root/f'rec{i}.json' for i in range(3)],union_reports=[root/f'union{i}.json' for i in range(3)],manifest_output=root/'ANNUAL_2023_VALIDATION_MANIFEST.json')
            self.assertEqual(annual['status'],'ANNUAL_2023_PASS');self.assertFalse(annual['oos_2024_accessed'])
            s=json.loads((root/'STATUS.json').read_text());self.assertEqual(s['status'],'ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED');self.assertFalse(s['annual_execution_authorized'])
            # Freeze identity list is exercised with small synthetic immutable files.
            old=list(frz.FROZEN_TOOLING);oldopt=list(frz.OPTIONAL_FROZEN_TOOLING)
            try:
                frz.FROZEN_TOOLING=['ANNUAL_2023_VALIDATION_MANIFEST.json','ENGINE_BUILD_MANIFEST.json','SHARDED_STORAGE_CONTRACT.json','reports/51_PA7_2023_REAL_SIZING_AND_BUCKET_PLAN.json'];frz.OPTIONAL_FROZEN_TOOLING=[]
                o=frz.freeze(group8_root=root,output=root/'OOS_FREEZE_MANIFEST.json')
            finally:
                frz.FROZEN_TOOLING[:]=old;frz.OPTIONAL_FROZEN_TOOLING[:]=oldopt
            self.assertEqual(o['status'],'FROZEN_FOR_2024_OOS_FREE_SHARDED');self.assertFalse(o['oos_2024_accessed_during_freeze']);self.assertFalse(o['paid_runner_allowed']);self.assertFalse(o['paid_service_allowed'])
            s=json.loads((root/'STATUS.json').read_text());self.assertTrue(s['annual_execution_2024_authorized']);self.assertFalse(s['annual_execution_2023_authorized'])

    def test_finalize_rejects_union_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root);bad=json.loads((root/'union2.json').read_text());bad['global_logical_sha256']='x'*64;bad.pop('report_hash');writej(root/'union2.json',hashed(bad))
            with self.assertRaisesRegex(RuntimeError,'full_union_logical_drift'):
                fin.finalize(group8_root=root,core_release_report=root/'core.json',pa7_release_report=root/'pa7.json',reconstruction_reports=[root/f'rec{i}.json' for i in range(3)],union_reports=[root/f'union{i}.json' for i in range(3)],manifest_output=root/'ANNUAL_2023_VALIDATION_MANIFEST.json')

if __name__=='__main__':unittest.main()
