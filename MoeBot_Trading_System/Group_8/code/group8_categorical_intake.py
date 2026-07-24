#!/usr/bin/env python3
"""Extract exact observed categorical dictionaries from one verified read-only annual SQLite dependency."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from pathlib import Path
from typing import Any

FIELDS={
 'source':{'bars':['timeframe','symbol','time_confidence']},
 'group2':{'regime_states':['direction_code','volatility_code','phase_code','raw_label_code','stable_label_code','uncertain','baseline_mature'],'timeframe_dictionary':['timeframe','timeframe_code','parent_timeframe_code']},
 'group3':{'structure_states':['timeframe','layer','sequence_bias','active_bias','leg','last_event_type'],'break_events':['timeframe','layer','event_type','direction','break_kind','strong_break','outcome'],'swings':['timeframe','layer','swing_type','relation']},
 'group4':{'zones':['timeframe','source_timeframe','zone_class','initial_role','current_role','layer','status','broken_direction'],'zone_interactions':['timeframe','event_type','status_after','role_after'],'zone_transitions':['from_status','to_status','role_after','reason']},
 'group5':{'liquidity_pools':['timeframe','pool_class','side','layer','status'],'liquidity_events':['timeframe','side','event_type','reclaimed','same_bar','closed_beyond','is_sweep','is_liquidity_grab','is_stop_run','is_false_breakout','resolution'],'draw_states':['timeframe','active_bias','draw_side'],'inducements':['timeframe','direction','status'],'liquidity_voids':['timeframe','direction','status']},
 'group6':{'displacement_legs':['timeframe','leg_kind','direction','origin_label','initial_classification','uncertain'],'displacement_validation_events':['validation_type','result'],'fvg_events':['timeframe','direction','clean_displacement','formation_quality'],'fvg_lifecycle_summary':['fill_state','directional_validity'],'group6_evidence':['subject_type','source_group','relation_type','source_timeframe'],'imbalance_variants':['timeframe','variant_type','direction','classification','separation_reason'],'inversion_fvg_relations':['direction_before','direction_after','inversion_status'],'liquidity_voids':['timeframe','direction','state'],'bpr_relations':['timeframe','second_fvg_direction','state'],'mtf_imbalance_relations':['child_type','child_timeframe','parent_type','parent_timeframe','relation_type','direction_alignment']},
 'group7':{'definition_registry':['definition_id','definition_version','derived','range_policy','invalidation_closes'],'institutional_zones':['definition_id','timeframe','direction','zone_label'],'zone_evidence':['evidence_type','source_group','relation_type'],'zone_relations':['relation_type'],'zone_state_transitions':['event_type','status','freshness'],'zone_lifecycle_summary':['status','freshness']},
}
def norm(v:Any)->Any:
    if isinstance(v,(bytes,bytearray,memoryview)):return {'__bytes_hex__':bytes(v).hex()}
    return v
def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--database',type=Path,required=True);ap.add_argument('--group',choices=tuple(FIELDS),required=True);ap.add_argument('--year',type=int,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    con=sqlite3.connect(f'file:{a.database.resolve()}?mode=ro&immutable=1',uri=True);con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")};out={}
    for table,fields in FIELDS[a.group].items():
        if table not in tables:raise SystemExit(f'missing table {table}')
        actual={r[1] for r in con.execute(f'PRAGMA table_info("{table}")')};missing=set(fields)-actual
        if missing:raise SystemExit(f'{table} missing fields {sorted(missing)}')
        out[table]={}
        for field in fields:
            vals=[norm(r[0]) for r in con.execute(f'SELECT DISTINCT "{field}" FROM "{table}" ORDER BY "{field}"')]
            if len(vals)>200:raise SystemExit(f'categorical cardinality unexpectedly high {table}.{field}={len(vals)}')
            out[table][field]={'distinct_count':len(vals),'values':vals}
    q=con.execute('PRAGMA quick_check').fetchone()[0];i=con.execute('PRAGMA integrity_check').fetchone()[0];fk=len(con.execute('PRAGMA foreign_key_check').fetchall());con.close()
    report={'format_version':1,'status':'PASS' if q=='ok' and i=='ok' and fk==0 else 'FAIL','group':a.group,'year':a.year,'sqlite':{'quick_check':q,'integrity_check':i,'foreign_key_errors':fk},'categorical_values':out}
    report['report_hash']=hashlib.sha256(canon(report).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'group':a.group,'year':a.year,'report_hash':report['report_hash']},indent=2));raise SystemExit(0 if report['status']=='PASS' else 1)
if __name__=='__main__':main()
