#!/usr/bin/env python3
"""Deterministically reconstruct the finalized non-PA7 Group 8 annual core.

Starts from an immutable Annual Core copy, applies the exact PA7-dependent derived
layer and catalog-aware global finalizer, audits cross-shard references, checks
causality/output prohibitions, and emits the logical SQLite fingerprint used by
annual idempotence/clean-reconstruction gates.
"""
from __future__ import annotations
import argparse,hashlib,json,re,shutil,sqlite3
from pathlib import Path
from typing import Any
from group8_pa7_derived_executor import PA7DerivedEngine
from group8_global_finalizer import Group8GlobalFinalizer
from group8_cross_shard_reference_audit import audit as ref_audit
from group8_sqlite_fingerprint import fingerprint
from group8_annual_validation import FORBIDDEN,GENERATED_TEXT_COLUMNS


def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def reconstruct(*,staging_db:Path,base_core_db:Path,output_db:Path,pa7_catalog:Path,artifacts_root:Path,year:int,symbol:str,report_path:Path)->dict[str,Any]:
 if year==2024:
  s=json.loads((artifacts_root/'STATUS.json').read_text())
  if s.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
 output_db.unlink(missing_ok=True);shutil.copy2(base_core_db,output_db)
 d=PA7DerivedEngine(staging_db=staging_db,output_db=output_db,pa7_catalog=pa7_catalog,artifacts_root=artifacts_root,year=year,symbol=symbol)
 try:derived=d.run_derived()
 finally:d.close()
 if derived['status']!='PASS':raise RuntimeError('derived layer failed')
 g=Group8GlobalFinalizer(staging_db=staging_db,output_db=output_db,pa7_catalog=pa7_catalog,artifacts_root=artifacts_root,year=year,symbol=symbol)
 try:glob=g.run_global_finalizer()
 finally:g.close()
 if glob['status']!='PASS':raise RuntimeError('global finalizer failed')
 refs=ref_audit(output_db,pa7_catalog,report_path.with_suffix('.refs.json'))
 c=sqlite3.connect(output_db);c.row_factory=sqlite3.Row
 try:
  causal={'price_action_pattern_candidate':'availability_time<confirmation_time OR confirmation_time<event_time','school_interpretation':'availability_time<confirmation_time OR confirmation_time<event_time','narrative_hypothesis':'availability_time<confirmation_time OR confirmation_time<event_time','invalidation_record':'availability_time<confirmation_time OR confirmation_time<event_time','price_action_pattern_state':'availability_time<event_time','hypothesis_lifecycle_event':'availability_time<event_time','conflicting_evidence':'availability_time<event_time','multi_timeframe_context_relation':'availability_time<event_time','evidence_chain':'event_time IS NOT NULL AND availability_time<event_time'}
  causal_errors={t:int(c.execute(f'SELECT COUNT(*) FROM {t} WHERE {where}').fetchone()[0]) for t,where in causal.items()};prohibited=[]
  for t,cols in GENERATED_TEXT_COLUMNS.items():
   for col in cols:
    for rowid,value in c.execute(f'SELECT rowid,"{col}" FROM "{t}"'):
     hit=sorted(set(re.findall(r'[a-z_]+',str(value).lower()))&FORBIDDEN)
     if hit:
      prohibited.append(f'{t}:{rowid}:{col}:{hit}')
      if len(prohibited)>=20:break
    if prohibited:break
   if prohibited:break
 finally:c.close()
 if any(causal_errors.values()):raise RuntimeError(f'causality violations:{causal_errors}')
 if prohibited:raise RuntimeError(f'prohibited generated trading outputs:{prohibited}')
 fp=fingerprint(output_db)
 rec={'format_version':1,'status':'PASS','year':year,'physical_role':'FINAL_NON_PA7_RECONSTRUCTION','derived_report':derived,'global_report':glob,'cross_shard_reference_report_hash':refs['report_hash'],'unresolved_group8_reference_count':refs['unresolved_group8_reference_count'],'causality':'PASS','causal_error_counts':causal_errors,'no_trading_outputs':True,'logical_sha256':fp['logical_sha256'],'database_sha256':fp['database_sha256'],'database_size_bytes':fp['database_size_bytes'],'fingerprint_report_hash':fp['report_hash'],'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable(rec);report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec


def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--base-core-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--pa7-catalog',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();r=reconstruct(staging_db=a.staging_db.resolve(),base_core_db=a.base_core_db.resolve(),output_db=a.output_db.resolve(),pa7_catalog=a.pa7_catalog.resolve(),artifacts_root=a.artifacts_root.resolve(),year=a.year,symbol=a.symbol,report_path=a.report.resolve());print(json.dumps({'status':r['status'],'logical_sha256':r['logical_sha256'],'report_hash':r['report_hash']},indent=2,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
