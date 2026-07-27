#!/usr/bin/env python3
"""Create execution-only indexes for the explicit PA7_COMPACT_V1 staging scope."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

INDEX_SPECS=(
 ('ix_g8_pa7_source_bars_sym_tf_close','source__bars',('symbol','timeframe','close_time','id')),
 ('ix_g8_pa7_g4_zones_sym_tf_avail_expire','group4__zones',('symbol','timeframe','available_at','expires_at','zone_id')),
 ('ix_g8_pa7_g4_trans_zone_time','group4__zone_transitions',('zone_id','transition_time','transition_id')),
 ('ix_g8_pa7_g4_inter_zone_time','group4__zone_interactions',('zone_id','interaction_time','interaction_id')),
 ('ix_g8_pa7_g5_pools_sym_tf_avail_expire','group5__liquidity_pools',('symbol','timeframe','available_at','expires_at','pool_id')),
 ('ix_g8_pa7_g6_fvg_tf_avail','group6__fvg_events',('timeframe','availability_time','fvg_id')),
 ('ix_g8_pa7_g6_fvgtr_fvg_time','group6__fvg_state_transitions',('fvg_id','transition_time','transition_id')),
 ('ix_g8_pa7_g6_imb_tf_avail','group6__imbalance_variants',('timeframe','availability_time','variant_id')),
 ('ix_g8_pa7_g6_void_tf_avail','group6__liquidity_voids',('timeframe','availability_time','void_id')),
 ('ix_g8_pa7_g6_bpr_tf_avail','group6__bpr_relations',('timeframe','availability_time','bpr_id')),
 ('ix_g8_pa7_g7_zones_tf_avail','group7__institutional_zones',('timeframe','availability_time','zone_id')),
 ('ix_g8_pa7_g7_state_zone_time','group7__zone_state_transitions',('zone_id','transition_time','transition_ordinal')),
)
def q(s):return '"'+s.replace('"','""')+'"'
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--phase',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();con=sqlite3.connect(a.database.resolve());tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")};manifest={str(r[0]):str(r[1]) for r in con.execute('SELECT key,value FROM stage_manifest')};fail=[];created=[]
 if manifest.get('materialization_scope')!='PA7_COMPACT_V1':fail.append('not_pa7_compact_scope')
 before=con.total_changes
 for name,table,cols in INDEX_SPECS:
  if table not in tables:fail.append(f'missing_required_table:{table}');continue
  actual={r[1] for r in con.execute(f'PRAGMA table_info({q(table)})')};missing=[c for c in cols if c not in actual]
  if missing:fail.append(f'missing_columns:{table}:{",".join(missing)}');continue
  sql=f'CREATE INDEX IF NOT EXISTS {q(name)} ON {q(table)} ({",".join(q(c) for c in cols)})';con.execute(sql);created.append({'name':name,'table':table,'columns':list(cols)})
 con.commit();qc=con.execute('PRAGMA quick_check').fetchone()[0];ic=con.execute('PRAGMA integrity_check').fetchone()[0];fk=con.execute('PRAGMA foreign_key_check').fetchall();after=con.total_changes
 if after!=before:fail.append(f'unexpected_data_changes:{before}->{after}')
 if qc!='ok':fail.append(f'quick_check:{qc}')
 if ic!='ok':fail.append(f'integrity_check:{ic}')
 if fk:fail.append(f'foreign_key_errors:{len(fk)}')
 con.close();report={'format_version':1,'status':'PASS' if not fail else 'FAIL','scope':'PA7_COMPACT_V1_EXECUTION_INDEXES_ONLY','year':a.year,'phase':a.phase,'index_count':len(created),'indexes':created,'data_changes':after-before,'quick_check':qc,'integrity_check':ic,'foreign_key_errors':len(fk),'failures':fail};report['report_hash']=stable(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
