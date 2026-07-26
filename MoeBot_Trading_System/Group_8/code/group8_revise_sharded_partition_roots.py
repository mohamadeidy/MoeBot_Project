#!/usr/bin/env python3
"""Revise only the frozen physical shard-placement rule to causal partition roots.

The first free-storage amendment is already committed. This revision makes the
physical bucket key usable for compute sharding: PA7 work is bucketed by exact
boundary identity and all descendants inherit that bucket. Logical records,
IDs, definitions, thresholds, schema semantics, Groups1-7 and 2024 remain
unchanged.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

OLD_FREEZE='42364211a43b26df07dfc1dd6a841930ca985959af61dfeffa1691b65bef42d7'
OLD_ENGINE='bb4b4bcaf8882aad41e2456a25d10941b455c53ad77cba2bd2e6170ed284a255'
OLD_CONTRACT='5840ac5a7c6ef0c7b80c12a1e524b8d9bf35d477a27d18e52e9a37707f754e37'
REGISTRY='70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9'
GAP='G8-FREE-STORAGE-CAPACITY-009'

def canonical(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def stable(v:Any)->str:return hashlib.sha256(canonical(v).encode()).hexdigest()
def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(16*1024*1024),b''):h.update(c)
    return h.hexdigest()
def write_hashed(p:Path,v:dict[str,Any])->dict[str,Any]:
    x=dict(v);x['report_hash']=stable(x);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');return x

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--group8-root',type=Path,required=True);a=ap.parse_args();r=a.group8_root.resolve()
    ep=r/'code/moebot_group8_engine_v0_8_0.py';fp=r/'DESIGN_FREEZE_MANIFEST.json';cp=r/'SHARDED_STORAGE_CONTRACT.json';sp=r/'STATUS.json';lp=r/'00_DESIGN_LOCK.md'
    if sha(ep)!=OLD_ENGINE:raise SystemExit('unexpected amended engine identity')
    freeze=json.loads(fp.read_text());contract=json.loads(cp.read_text());status=json.loads(sp.read_text());reg=json.loads((r/'01_DEFINITION_REGISTRY.json').read_text())
    if freeze.get('design_freeze_hash')!=OLD_FREEZE or freeze.get('storage_contract_hash')!=OLD_CONTRACT or contract.get('storage_contract_hash')!=OLD_CONTRACT:raise SystemExit('storage amendment lineage mismatch')
    if reg.get('registry_hash')!=REGISTRY:raise SystemExit('definition registry drift')
    if status.get('annual_execution_2023_authorized') is not False or status.get('annual_execution_2024_authorized') is not False:raise SystemExit('annual execution must remain fail-closed')

    part=contract['partitioning']
    part['primary_dimensions']=['year','family','timeframe','causal_root_window','bucket_index']
    part['causal_root_window']='calendar month of the immutable causal partition root or source bar, never a future outcome/descendant time'
    part['partition_root_rules']={
      'bar_local':'source_bar_id',
      'pa7_chain':'immutable PA7 boundary identity = source_group:source_type:boundary_id; all Exact/Point/ATR transitions and descendants for that boundary inherit the same root',
      'range_chain':'pa_bounded_range_context candidate_id; all range descendants inherit it',
      'school_core':'first mandatory immutable upstream evidence identity under the frozen definition',
      'relations':'canonical ordered tuple of referenced Group8 subject IDs',
    }
    part['adaptive_bucket_rule']={
      'bucket_count':'positive power of two chosen and frozen before shard execution from 2023-only cardinality/size evidence',
      'assignment':'int(sha256(partition_root_id)[0:16],16) % bucket_count',
      'descendant_locality':'every record causally descended from a partition root inherits that root bucket even when its own primary ID hashes elsewhere',
      'semantics':'physical placement only; never changes, merges or drops a logical record',
      'future_resize':'increase bucket_count before execution when a shard is projected to exceed the soft target; never rebucket an already frozen release silently',
    }
    contract['manifest_requirements']=['shard_id','family','year','symbol','timeframe','causal_root_window','partition_root_rule','bucket_index','bucket_count','file_size_bytes','sha256','compressed_sha256','table_row_counts','table_logical_sha256','min_event_time','max_event_time','min_availability_time','max_availability_time','definition_coverage','upstream_lineage_id','engine_sha256','design_freeze_hash','storage_contract_hash']
    inv=contract['global_union_invariants']
    add='all descendants inherit the causal partition root solely for physical locality; their own immutable IDs/hashes remain unchanged'
    if add not in inv:inv.insert(-1,add)
    contract['contract_revision']=2;contract['previous_storage_contract_hash']=OLD_CONTRACT;contract.pop('storage_contract_hash',None);new_contract=stable(contract);contract['storage_contract_hash']=new_contract;cp.write_text(json.dumps(contract,indent=2,sort_keys=True)+'\n')

    freeze['storage_contract_hash']=new_contract;sa=freeze['storage_amendment'];sa['amendment_version']=2;sa['previous_storage_contract_hash']=OLD_CONTRACT;sa['storage_contract_hash']=new_contract;sa['partition_root_revision']='CAUSAL_ROOT_BUCKETING';sa['previous_revision_design_freeze_hash']=OLD_FREEZE
    freeze.pop('design_freeze_hash',None);new_freeze=stable(freeze);freeze['design_freeze_hash']=new_freeze;fp.write_text(json.dumps(freeze,indent=2,sort_keys=True)+'\n')

    text=ep.read_text();old=f'EXPECTED_DESIGN_FREEZE_HASH = "{OLD_FREEZE}"';new=f'EXPECTED_DESIGN_FREEZE_HASH = "{new_freeze}"'
    if old not in text:raise SystemExit('old amended freeze constant missing')
    ep.write_text(text.replace(old,new,1));new_engine=sha(ep)

    lock=lp.read_text();extra=f'''\n### 18.1 Causal partition-root revision\n\nPhysical bucket assignment is frozen on the family causal partition root, not each descendant primary ID. For `pa7_chain`, the root is the exact immutable boundary identity and all PA7 variants plus PA8/PA9/root-linked descendants inherit that root bucket. This revision changes physical locality only; logical IDs, hashes, definitions, thresholds and causal timestamps are unchanged. Storage contract: `{new_contract}`.\n'''
    if '### 18.1 Causal partition-root revision' not in lock:lp.write_text(lock.rstrip()+extra+'\n')

    rep=write_hashed(r/'reports/45_CAUSAL_PARTITION_ROOT_STORAGE_REVISION.json',{
      'format_version':1,'status':'PASS','gap_id':GAP,'revision':'CAUSAL_ROOT_BUCKETING','previous_storage_contract_hash':OLD_CONTRACT,'storage_contract_hash':new_contract,'previous_design_freeze_hash':OLD_FREEZE,'design_freeze_hash':new_freeze,'previous_engine_sha256':OLD_ENGINE,'engine_sha256':new_engine,'definition_registry_hash':REGISTRY,'logical_semantics_changed':False,'schema_sql_changed':False,'thresholds_changed':False,'groups_1_7_changed':False,'oos_2024_accessed':False,'paid_cost_authorized':False,
    })
    bg=status['blocking_gap'];bg['status']='APPROVED_SHARDED_IMPLEMENTATION_PENDING_TECHNICAL_REFREEZE';bg['storage_contract_hash']=new_contract;bg['design_freeze_hash']=new_freeze;bg['amended_engine_sha256']=new_engine;bg['partition_root_revision_report_hash']=rep['report_hash'];status['storage_contract_hash']=new_contract;status['engine_build']['engine_sha256']=new_engine;status['engine_build']['status']='TECHNICAL_CANDIDATE_PENDING_SHARDED_STORAGE_REFREEZE';status['design_amendment_hash']=rep['report_hash'];status['status']='FREE_ONLY_CAUSAL_ROOT_SHARDING_APPLIED_TECHNICAL_REFREEZE_REQUIRED';status['annual_execution_2023_authorized']=False;status['annual_execution_2024_authorized']=False;status['annual_execution_authorized']=False;status['engine_build_authorized']=False;status['officially_closed']=False;sp.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'PASS','storage_contract_hash':new_contract,'design_freeze_hash':new_freeze,'engine_sha256':new_engine,'report_hash':rep['report_hash']},indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
