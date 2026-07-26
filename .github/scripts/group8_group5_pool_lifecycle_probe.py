#!/usr/bin/env python3
"""Inspect exact 2023 Group5 liquidity-pool lifecycle evidence used by PA7."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3,sys
from pathlib import Path
from typing import Any
ENGINE_SHA="a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"

def sha(p:Path)->str:
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
def stable(x:object)->str:return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def rows(con:sqlite3.Connection,sql:str)->list[dict[str,Any]]:
 c=con.execute(sql);names=[d[0] for d in c.description];return [dict(zip(names,r)) for r in c.fetchall()]
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve()
 if sha(root/'code/moebot_group8_engine_v0_8_0.py')!=ENGINE_SHA:raise SystemExit('engine identity mismatch')
 status=json.loads((root/'STATUS.json').read_text());reg=json.loads((root/'UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json').read_text())
 if status.get('annual_execution_2023_authorized') is not True or status.get('annual_execution_2024_authorized') is not False:raise SystemExit('authorization boundary mismatch')
 rec=reg['years']['2023']['manifest']['packages']['group5']
 sys.path.insert(0,str(root/'code'));from group8_materialize_inputs import restore_record,verify_sqlite
 a.work_dir.mkdir(parents=True,exist_ok=True);db=restore_record(rec,a.work_dir);con=verify_sqlite(db)
 try:
  status_dist=rows(con,"SELECT COALESCE(status,'<NULL>') status,COUNT(*) n,SUM(first_sweep_time IS NOT NULL) with_first_sweep,SUM(expires_at IS NOT NULL) with_expires,SUM(first_event_id IS NOT NULL) with_first_event,MIN(first_sweep_time) min_first_sweep,MAX(first_sweep_time) max_first_sweep FROM liquidity_pools GROUP BY status ORDER BY n DESC,status")
  by_tf=rows(con,"SELECT timeframe,COALESCE(status,'<NULL>') status,COUNT(*) n,SUM(first_sweep_time IS NOT NULL) with_first_sweep,SUM(expires_at IS NOT NULL) with_expires FROM liquidity_pools GROUP BY timeframe,status ORDER BY timeframe,n DESC,status")
  timing=rows(con,"SELECT COALESCE(status,'<NULL>') status,COUNT(*) n,SUM(CASE WHEN first_sweep_time IS NOT NULL AND first_sweep_time>=available_at THEN 1 ELSE 0 END) sweep_after_avail,SUM(CASE WHEN first_sweep_time IS NOT NULL AND expires_at IS NOT NULL AND first_sweep_time<=expires_at THEN 1 ELSE 0 END) sweep_before_or_at_expiry,SUM(CASE WHEN first_sweep_time IS NOT NULL AND expires_at IS NOT NULL AND first_sweep_time>expires_at THEN 1 ELSE 0 END) sweep_after_expiry FROM liquidity_pools GROUP BY status ORDER BY n DESC,status")
  event_dist=rows(con,"SELECT COALESCE(event_type,'<NULL>') event_type,COALESCE(resolution,'<NULL>') resolution,COUNT(*) n,SUM(resolved_time IS NOT NULL) resolved FROM liquidity_events GROUP BY event_type,resolution ORDER BY n DESC,event_type,resolution")
  qc=con.execute('PRAGMA quick_check').fetchone()[0]
 finally:
  con.close();db.unlink(missing_ok=True);shutil.rmtree(a.work_dir,ignore_errors=True)
 report={'format_version':1,'status':'PASS' if qc=='ok' else 'FAIL','scope':'GROUP5_POOL_LIFECYCLE_2023_ONLY','engine_sha256':ENGINE_SHA,'group5_database_sha256':rec['database_sha256'],'group5_database_size_bytes':rec['database_size_bytes'],'pool_status_distribution':status_dist,'pool_status_by_timeframe':by_tf,'pool_timing_consistency':timing,'liquidity_event_distribution':event_dist,'sqlite_quick_check':qc,'observations':{'diagnostic_only':True,'engine_changed':False,'definitions_changed':False,'thresholds_changed':False,'schema_changed':False,'upstream_changed':False,'authorization_changed':False,'oos_2024_accessed':False,'no_lifecycle_rule_inferred_by_probe':True}}
 report['report_hash']=stable(report);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if qc=='ok' else 2
if __name__=='__main__':raise SystemExit(main())
