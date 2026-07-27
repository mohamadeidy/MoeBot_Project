#!/usr/bin/env python3
"""Inventory every causal PA7 root month present in an annual staging database.

This is a completeness gate for the physical sharding plan. It never emits or
changes domain records. Official annual workers must iterate the observed windows
rather than assume roots are confined to January-December of the target year.
"""
from __future__ import annotations
import argparse,hashlib,json
from collections import Counter
from pathlib import Path
from typing import Any

from group8_pa7_shard_executor import ShardSpec,epoch_month
from group8_pa7_scoped_shard_executor import ScopedPA7ShardEngine

SCOPES=('upstream','group8_range')

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def inventory(*,staging_db:Path,artifacts_root:Path,year:int,symbol:str,timeframes:list[str])->dict[str,Any]:
    if year==2024:
        s=json.loads((artifacts_root/'STATUS.json').read_text())
        if s.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')
    result={};all_windows=set()
    for tf in timeframes:
        result[tf]={}
        for scope in SCOPES:
            work=staging_db.parent/f'.root_inventory_{tf}_{scope}.sqlite';work.unlink(missing_ok=True)
            spec=ShardSpec(year,symbol,tf,None,1,0)
            e=ScopedPA7ShardEngine(staging_db=staging_db,output_db=work,artifacts_root=artifacts_root,year=year,symbol=symbol,spec=spec,boundary_scope=scope)
            try:
                e.load_bars();e.retain_target_timeframe()
                if scope=='group8_range':e.process_bounded_ranges()
                rows=e._pa7_boundary_catalog(symbol,tf)
                counts=Counter(epoch_month(int(r['event'])) for r in rows)
                windows=sorted(counts)
                all_windows.update(windows)
                result[tf][scope]={'boundary_root_count':len(rows),'root_windows':windows,'root_window_counts':dict(sorted(counts.items())),'min_root_window':windows[0] if windows else None,'max_root_window':windows[-1] if windows else None}
            finally:e.close();work.unlink(missing_ok=True)
    rec={'format_version':1,'status':'PASS','year':year,'symbol':symbol,'timeframes':timeframes,'scopes':list(SCOPES),'inventory':result,'all_observed_root_windows':sorted(all_windows),'worker_rule':'official PA7 annual execution must process every root_window listed for each timeframe/scope exactly once per bucket','free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable(rec);return rec

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol',required=True);p.add_argument('--timeframes',nargs='+',required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();r=inventory(staging_db=a.staging_db.resolve(),artifacts_root=a.artifacts_root.resolve(),year=a.year,symbol=a.symbol,timeframes=a.timeframes);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
