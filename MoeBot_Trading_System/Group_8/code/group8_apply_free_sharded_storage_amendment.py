#!/usr/bin/env python3
"""Apply the approved free-only lossless sharded storage/handoff amendment.

Logical Group8 definitions, thresholds, IDs, causal timestamps, Groups1-7 and
2024 OOS remain unchanged. Only physical annual materialization and handoff are
amended so the project can continue on standard zero-cost GitHub-hosted jobs.
"""
from __future__ import annotations

import argparse, hashlib, json, re
from pathlib import Path
from typing import Any

GAP_ID='G8-FREE-STORAGE-CAPACITY-009'
OLD_FREEZE='7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4'
ENGINE_SHA='44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b'
REGISTRY_HASH='70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9'


def canonical(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def stable(v:Any)->str:
    return hashlib.sha256(canonical(v).encode()).hexdigest()

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for c in iter(lambda:f.read(16*1024*1024),b''):h.update(c)
    return h.hexdigest()

def write_hashed(path:Path,payload:dict[str,Any],field='report_hash')->dict[str,Any]:
    rec=dict(payload);rec[field]=stable(rec);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--group8-root',type=Path,required=True);args=ap.parse_args();root=args.group8_root.resolve()
    engine=root/'code/moebot_group8_engine_v0_8_0.py';freeze_path=root/'DESIGN_FREEZE_MANIFEST.json';status_path=root/'STATUS.json';lock_path=root/'00_DESIGN_LOCK.md';cap_path=root/'reports/43B_FREE_RUNNER_CAPACITY_PROBE.json'
    if sha(engine)!=ENGINE_SHA:raise SystemExit('engine identity drift before storage amendment')
    freeze=json.loads(freeze_path.read_text());status=json.loads(status_path.read_text());registry=json.loads((root/'01_DEFINITION_REGISTRY.json').read_text())
    if freeze.get('design_freeze_hash')!=OLD_FREEZE or registry.get('registry_hash')!=REGISTRY_HASH:raise SystemExit('frozen design identity mismatch')
    if status.get('annual_execution_2023_authorized') is not True or status.get('annual_execution_2024_authorized') is not False or status.get('officially_closed') is not False:raise SystemExit('unexpected authorization boundary')
    cap=None
    if cap_path.is_file():
        cap=json.loads(cap_path.read_text());q=dict(cap);saved=q.pop('report_hash',None)
        if saved!=stable(q) or cap.get('status')!='PASS' or cap.get('policy',{}).get('free_only') is not True:raise SystemExit('invalid free capacity evidence')

    contract={
      'format_version':1,
      'contract_id':'g8_lossless_sharded_sqlite_v1',
      'status':'FROZEN',
      'purpose':'zero-cost scalable physical materialization and downstream handoff',
      'free_only_policy':{'paid_runner_allowed':False,'paid_service_allowed':False,'standard_github_hosted_jobs_preferred':True},
      'logical_contract':{
        'definitions_unchanged':True,'thresholds_unchanged':True,'schema_semantics_unchanged':True,'immutable_ids_unchanged':True,
        'event_time_unchanged':True,'confirmation_time_unchanged':True,'availability_time_unchanged':True,'no_lookahead':True,'no_backdating':True,
        'groups_1_7_read_only':True,'oos_2024_untouched':True,
      },
      'physical_format':{
        'primary':'SQLite shards compressed with zstd for transport',
        'logical_schema_version':'8.0.0',
        'registries_may_repeat_only_if_byte/logical-hash identical':True,
        'domain_primary_ids_must_be_globally_unique':True,
        'cross_shard_references':'verified through global manifest/catalog; no semantic weakening of references',
      },
      'partitioning':{
        'primary_dimensions':['year','family','timeframe','causal_root_window'],
        'causal_root_window':'calendar month of the immutable causal root object or source bar, never future outcome time',
        'families':{
          'bar_local':'bar-rooted PA1-PA6 and context-rejection records',
          'pa7_chain':'PA7 exact/point/ATR transitions plus PA8 failed-breakout, PA9 retest and root-linked exhaustion descendants',
          'range_chain':'bounded-range-rooted contexts, premium/discount lifecycle observations and range-rooted Wyckoff descendants',
          'school_core':'direct Dow/Wyckoff/ICT hypotheses and interpretations not assigned to high-cardinality root chains',
          'relations':'shared/conflicting/MTF/evidence/invalidation/lifecycle relation records',
        },
        'adaptive_bucket_rule':{
          'bucket_count':'positive power of two chosen before shard execution from 2023-only cardinality/size evidence',
          'assignment':'int(sha256(global_primary_id)[0:16],16) % bucket_count',
          'semantics':'physical placement only; never changes, merges or drops a logical record',
          'future_resize':'increase bucket_count before execution when a shard is projected to exceed the soft target; never rebucket an already frozen release silently',
        },
        'soft_target_uncompressed_bytes':1500000000,
        'runtime_hard_guard_bytes':2500000000,
      },
      'manifest_requirements':['shard_id','family','year','symbol','timeframe','causal_root_window','bucket_index','bucket_count','file_size_bytes','sha256','compressed_sha256','table_row_counts','table_logical_sha256','min_event_time','max_event_time','min_availability_time','max_availability_time','definition_coverage','upstream_lineage_id','engine_sha256','design_freeze_hash','storage_contract_hash'],
      'global_union_invariants':[
        'set union of all domain rows by immutable primary ID equals the complete logical annual dataset',
        'duplicate domain primary IDs across shards are forbidden unless row canonical hash is identical and duplicate is explicitly registry-only',
        'global table logical fingerprints are computed streaming from sorted (primary_id,row_hash) pairs and do not require a monolithic database',
        'every cross-shard Group8 reference resolves to exactly one immutable subject ID in the global catalog',
        'annual idempotence and clean reconstruction compare global manifests/fingerprints rather than file-layout byte identity',
      ],
      'handoff_policy':{
        'later_groups_download_only_required_shards':True,
        'full historical monolithic SQLite_not_required':True,
        'release_assets_may_be_split_into_multiple_verified_parts':True,
        'all parts_sha256_bound_by_manifest':True,
      },
    }
    contract['storage_contract_hash']=stable(contract)
    (root/'SHARDED_STORAGE_CONTRACT.json').write_text(json.dumps(contract,indent=2,sort_keys=True)+'\n')

    old_freeze=dict(freeze)
    freeze['format_version']=6
    freeze['storage_contract_hash']=contract['storage_contract_hash']
    freeze['storage_amendment']={
      'amendment_id':'G8-FREE-LOSSLESS-SHARDED-STORAGE-AMENDMENT-001','amendment_version':1,'gap_id':GAP_ID,
      'approved_execution_policy':'FREE_ONLY','approved_storage':'LOSSLESS_SHARDED_STORAGE_ARCHITECTURE',
      'previous_design_freeze_hash':OLD_FREEZE,'logical_semantics_changed':False,'definition_registry_changed':False,'thresholds_changed':False,
      'logical_schema_changed':False,'physical_storage_handoff_changed':True,'groups_1_7_changed':False,'upstream_lineage_changed':False,'oos_2024_accessed':False,
      'storage_contract_hash':contract['storage_contract_hash'],
    }
    freeze.pop('design_freeze_hash',None);new_freeze_hash=stable(freeze);freeze['design_freeze_hash']=new_freeze_hash;freeze_path.write_text(json.dumps(freeze,indent=2,sort_keys=True)+'\n')

    text=engine.read_text()
    old_line=f'EXPECTED_DESIGN_FREEZE_HASH = "{OLD_FREEZE}"'
    new_line=f'EXPECTED_DESIGN_FREEZE_HASH = "{new_freeze_hash}"'
    if old_line not in text:raise SystemExit('engine frozen hash constant not found exactly')
    engine.write_text(text.replace(old_line,new_line,1))
    new_engine_sha=sha(engine)

    section=f'''\n\n## 18. Free-only lossless sharded storage/handoff amendment\n\n**Approved for Gap `{GAP_ID}`.** Group 8 logical semantics remain unchanged. Annual materialization and all later handoffs use frozen storage contract `{contract['contract_id']}` / `{contract['storage_contract_hash']}`.\n\n- No paid runner or paid service may be required by the official execution path.\n- No valid record may be dropped, sampled, merged across PA7 variants, or excluded by timeframe to fit capacity.\n- Sharding is deterministic physical placement only; immutable IDs, hashes, definitions, thresholds, event/confirmation/availability times and causal rules remain unchanged.\n- Adaptive hash buckets may increase before a frozen run when a projected shard exceeds the frozen size target.\n- Global annual identity is the verified set-union manifest and streaming logical fingerprint across all shards; a monolithic SQLite file is no longer required for closure or Group 9 handoff.\n- 2024 OOS remains forbidden until complete 2023 sharded validation and OOS freeze.\n'''
    lock=lock_path.read_text()
    if '## 18. Free-only lossless sharded storage/handoff amendment' not in lock:lock_path.write_text(lock.rstrip()+section+'\n')

    report=write_hashed(root/'reports/44_FREE_ONLY_SHARDED_STORAGE_DESIGN_AMENDMENT.json',{
      'format_version':1,'status':'PASS','gap_id':GAP_ID,'classification':'PHYSICAL_STORAGE_HANDOFF_CAPACITY','approval':'FREE_ONLY_LOSSLESS_SHARDED_STORAGE',
      'previous_design_freeze_hash':OLD_FREEZE,'amended_design_freeze_hash':new_freeze_hash,'definition_registry_hash':REGISTRY_HASH,
      'previous_engine_sha256':ENGINE_SHA,'amended_engine_sha256':new_engine_sha,'storage_contract_hash':contract['storage_contract_hash'],
      'capacity_probe_hash':cap.get('report_hash') if cap else None,'logical_semantics_changed':False,'schema_sql_changed':False,'thresholds_changed':False,
      'groups_1_7_changed':False,'upstream_lineage_changed':False,'oos_2024_accessed':False,'paid_cost_authorized':False,
    })

    previous=status.get('blocking_gap')
    status['previous_closed_blocking_gap']=previous
    status['blocking_gap']={
      'gap_id':GAP_ID,'classification':'PHYSICAL_STORAGE_HANDOFF_CAPACITY','severity':'BLOCKING','status':'APPROVED_SHARDED_IMPLEMENTATION_PENDING_TECHNICAL_REFREEZE',
      'decision_required':False,'design_change_required':True,'approved_resolution':'FREE_ONLY_LOSSLESS_SHARDED_STORAGE','report_hash':report['report_hash'],
      'storage_contract_hash':contract['storage_contract_hash'],'design_freeze_hash':new_freeze_hash,'amended_engine_sha256':new_engine_sha,'oos_2024_accessed':False,
    }
    status['design_amendment_hash']=report['report_hash'];status['storage_contract_hash']=contract['storage_contract_hash'];status['engine_build_authorized']=False;status['annual_execution_authorized']=False;status['annual_execution_2023_authorized']=False;status['annual_execution_2024_authorized']=False
    status['engine_build']['status']='TECHNICAL_CANDIDATE_PENDING_SHARDED_STORAGE_REFREEZE';status['engine_build']['engine_sha256']=new_engine_sha;status['status']='FREE_ONLY_SHARDED_STORAGE_AMENDMENT_APPLIED_TECHNICAL_REFREEZE_REQUIRED';status['officially_closed']=False
    status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'PASS','gap_id':GAP_ID,'new_design_freeze_hash':new_freeze_hash,'new_engine_sha256':new_engine_sha,'storage_contract_hash':contract['storage_contract_hash'],'2023_authorized':False,'2024_authorized':False},indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
