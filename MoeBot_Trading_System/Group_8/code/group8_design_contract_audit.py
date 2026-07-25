#!/usr/bin/env python3
"""Independent fail-closed audit for Group 8 design candidate v2."""
from __future__ import annotations
import argparse,hashlib,json,re,sqlite3
from pathlib import Path
from typing import Any
ALLOWED_SCHOOLS={'classical_price_action','dow_theory','wyckoff','ict_smc'}
REQUIRED_TABLES={'upstream_id_bridge','price_action_pattern_candidate','price_action_pattern_state','school_interpretation','shared_evidence','conflicting_evidence','narrative_hypothesis','hypothesis_lifecycle_event','multi_timeframe_context_relation','evidence_chain','invalidation_record'}
IMMUTABLE_TABLES={'config_registry','dataset_registry','dependency_registry','upstream_id_bridge','school_registry','pattern_definition_registry','interpretation_definition_registry','price_action_pattern_candidate','price_action_pattern_state','school_interpretation','shared_evidence','conflicting_evidence','narrative_hypothesis','hypothesis_lifecycle_event','multi_timeframe_context_relation','evidence_chain','invalidation_record','group8_audit_evidence'}
FORBIDDEN_SQL_COLUMNS={'entry','entry_price','stop','stop_loss','take_profit','target','position_size','lot','risk','pnl','mfe','mae','future_return','profitability','expectancy','sharpe','profit_factor'}
CONFIG_ALIASES={'doji_strict_body_ratio':'pattern_thresholds.doji_strict_body_to_range_max','doji_broad_body_ratio':'pattern_thresholds.doji_broad_body_to_range_max','pin_dominant_wick_ratio':'pattern_thresholds.pin_dominant_wick_to_range_min','pin_max_body_ratio':'pattern_thresholds.pin_body_to_range_max','pin_max_opposite_wick_ratio':'pattern_thresholds.pin_opposite_wick_to_range_max','rejection_min_wick_ratio':'pattern_thresholds.rejection_wick_to_range_min','rejection_close_outer_fraction':'pattern_thresholds.rejection_close_outer_fraction','context_proximity_atr':'feature_parameters.proximity_atr_fraction','breakout_atr_buffer':'pattern_thresholds.atr_buffer_breakout_fraction'}
def cj(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def get(d:dict[str,Any],path:str)->Any:
 cur:Any=d
 for part in path.split('.'):
  if not isinstance(cur,dict) or part not in cur:raise KeyError(path)
  cur=cur[part]
 return cur
def strings(v:Any):
 if isinstance(v,str):yield v
 elif isinstance(v,dict):
  for x in v.values():yield from strings(x)
 elif isinstance(v,list):
  for x in v:yield from strings(x)
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--schema',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.root.resolve();fail=[];checks={}
 defs=json.loads((root/'01_DEFINITION_REGISTRY_CANDIDATE_v2.json').read_text());cfg=json.loads((root/'FROZEN_CONFIG_DRAFT.json').read_text());sem=json.loads((root/'UPSTREAM_SOURCE_SEMANTICS_EVIDENCE.json').read_text());D=defs.get('definitions',{})
 checks['definition_count']=len(D)
 if len(D)!=45:fail.append(f'definition_count:{len(D)}')
 versions=[]
 for name,spec in sorted(D.items()):
  for key in ('school','kind','version','mandatory_inputs','availability'):
   if key not in spec:fail.append(f'{name}:missing:{key}')
  if not ('pass_rule' in spec or 'resolution_rule' in spec):fail.append(f'{name}:missing_pass_or_resolution_rule')
  if spec.get('school') not in ALLOWED_SCHOOLS:fail.append(f'{name}:school:{spec.get("school")}')
  versions.append(spec.get('version'))
 if len(set(versions))!=len(versions):fail.append('duplicate_definition_version')
 if sem.get('status')!='PASS' or sem.get('failures'):fail.append('source_semantics_not_pass')
 for text in strings(defs):
  for alias in re.findall(r'\bconfig\.([A-Za-z_][A-Za-z0-9_]*)',text):
   target=CONFIG_ALIASES.get(alias)
   if not target:fail.append(f'unknown_config_alias:{alias}')
   else:
    try:get(cfg,target)
    except KeyError:fail.append(f'missing_config_target:{alias}:{target}')
 bindings=sorted(set(path for text in strings(defs) for path in re.findall(r'UPSTREAM_VALUE_BINDINGS\.([A-Za-z0-9_.]+)',text)))
 expected_bindings={'group3.advancing_bias_values','group3.declining_bias_values','group3.indeterminate_bias_values','group3.bullish_transition_event_types','group3.bearish_transition_event_types','group3.bullish_direction_values','group3.bearish_direction_values','group3.mss_or_bos_event_types'}
 if set(bindings)!=expected_bindings:fail.append(f'binding_reference_set:{bindings}')
 global_text=' '.join(defs.get('global_rules',[])).lower()
 for phrase in ('no future-return','creation records are immutable','no implicit horizon','never select a preferred object or school'):
  if phrase not in global_text:fail.append(f'missing_global_rule:{phrase}')
 con=sqlite3.connect(':memory:');sql=a.schema.read_text();con.executescript(sql);tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")};triggers={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
 for t in sorted(REQUIRED_TABLES-tables):fail.append(f'missing_table:{t}')
 for t in sorted(IMMUTABLE_TABLES):
  if f'no_update_{t}' not in triggers:fail.append(f'missing_update_guard:{t}')
  if f'no_delete_{t}' not in triggers:fail.append(f'missing_delete_guard:{t}')
 for table in tables:
  cols={str(r[1]).lower() for r in con.execute(f'PRAGMA table_info("{table}")')}
  for col in sorted(cols&FORBIDDEN_SQL_COLUMNS):fail.append(f'forbidden_column:{table}.{col}')
 bridge_cols={r[1] for r in con.execute("PRAGMA table_info('upstream_id_bridge')")}
 if bridge_cols!={'source_group','published_id','corrected_v3_id','mapping_kind','evidence_json','bridge_hash'}:fail.append(f'bridge_schema:{sorted(bridge_cols)}')
 ds_cols={r[1] for r in con.execute("PRAGMA table_info('dataset_registry')")}
 for col in ('upstream_lineage_bridge_hash','annual_dependency_registry_hash','adapter_map_hash','categorical_dictionary_hash','value_bindings_hash','definition_registry_hash'):
  if col not in ds_cols:fail.append(f'dataset_registry_missing:{col}')
 con.close();checks.update({'definition_versions_unique':len(set(versions))==len(versions),'source_semantics_status':sem.get('status'),'binding_references':bindings,'schema_table_count':len(tables),'schema_trigger_count':len(triggers),'immutable_table_count':len(IMMUTABLE_TABLES)})
 report={'format_version':1,'status':'PASS' if not fail else 'FAIL','checks':checks,'failures':sorted(set(fail))};report['report_hash']=hashlib.sha256(cj(report).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
