#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, shutil
from pathlib import Path

COUNT=54_413_814
FIXED_BYTES=401
ENGINE_SHA='44e0c1bd9dc0e32bcb00a0ee0363754d45282fcee3d81a2170f9fa6ed6cb441b'

def stable(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def sha(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(16*1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve()
    engine=root/'code/moebot_group8_engine_v0_8_0.py';status=json.loads((root/'STATUS.json').read_text());schema=(root/'02_SCHEMA.sql').read_text();post=(root/'code/group8_postprocess_v0_8_0.py').read_text();et=engine.read_text()
    checks={
      'engine_sha':sha(engine)==ENGINE_SHA,
      '2023_authorized':status.get('annual_execution_2023_authorized') is True,
      '2024_forbidden':status.get('annual_execution_2024_authorized') is False,
      'candidate_table':'CREATE TABLE IF NOT EXISTS price_action_pattern_candidate' in schema,
      'state_table':'CREATE TABLE IF NOT EXISTS price_action_pattern_state' in schema,
      'candidate_hashes':all(x in schema for x in ('candidate_id TEXT PRIMARY KEY','feature_hash TEXT NOT NULL','candidate_hash TEXT NOT NULL')),
      'state_hashes':all(x in schema for x in ('state_event_id TEXT PRIMARY KEY','candidate_id TEXT NOT NULL','state_hash TEXT NOT NULL')),
      'creation_state_call':'ensure_pattern_creation_state(self, cid)' in et,
      'creation_state_id':'deterministic_id("g8pstate"' in post,
      'single_output_sqlite':'self.out = sqlite3.connect(self.output_db)' in et,
    }
    if not all(checks.values()): raise SystemExit(f'preflight failed:{checks}')
    fixed={
      'candidate_id':68,'candidate_feature_hash':64,'candidate_hash':64,
      'state_event_id':73,'state_candidate_id':68,'state_hash':64,
    }
    per=sum(fixed.values())
    if per!=FIXED_BYTES: raise SystemExit(per)
    structural=COUNT*per
    disk=shutil.disk_usage(root)
    report={
      'format_version':1,'status':'PASS','scope':'FREE_ONLY_RUNNER_CAPACITY_PROBE','engine_sha256':ENGINE_SHA,
      'partial_transition_count':COUNT,'partial_scope_excludes':['Group5 PA7 boundaries','Group7 PA7 boundaries'],
      'checks':checks,'fixed_text_bytes':fixed,'fixed_text_bytes_per_transition':per,
      'structural_lower_bound_bytes':structural,'structural_lower_bound_decimal_gb':structural/1e9,
      'runner_filesystem_total_bytes':disk.total,'runner_filesystem_used_bytes':disk.used,'runner_filesystem_free_bytes':disk.free,
      'structural_bound_fits_current_free_space':structural<disk.free,
      'remaining_free_bytes_after_structural_bound':disk.free-structural,
      'important_exclusions':['JSON payloads','numeric fields','SQLite row/page overhead','indexes','other Group8 outputs','staging database','Group5/Group7 PA7 transitions'],
      'policy':{'paid_runner_allowed':False,'paid_service_allowed':False,'free_only':True},
      'oos_2024_accessed':False,
    }
    report['report_hash']=stable(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0
if __name__=='__main__': raise SystemExit(main())
