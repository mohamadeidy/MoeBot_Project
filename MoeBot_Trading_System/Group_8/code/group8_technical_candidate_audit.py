#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, json, re, sqlite3
from pathlib import Path

from moebot_group8_engine_v0_8_0 import (
    ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, EXPECTED_DEFINITION_COUNT,
    EXPECTED_DEFINITION_REGISTRY_HASH, EXPECTED_SCHEMA_SHA256,
    EXPECTED_DESIGN_FREEZE_HASH, Group8Engine, sha256_file, stable_hash,
)

FORBIDDEN_TABLE_REFERENCES={
    'post_event_observations',
    'fvg_visit_reactions',
}
FORBIDDEN_SCHEMA_TOKENS={
    'buy','sell','entry','stop_loss','take_profit','position_size','lot_size',
    'pnl','mfe','mae','future_return','profit_factor','expectancy','sharpe',
    'hit_rate','trade_score','preferred_school','preferred_setup','setup_grade',
}

def file_hash(path:Path)->str:
    return sha256_file(path)

def schema_columns(schema_sql:str)->dict[str,list[str]]:
    con=sqlite3.connect(':memory:');con.executescript(schema_sql);out={}
    for table, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        out[table]=[r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    con.close();return out

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve();failures=[];checks={}
    config=json.loads((root/'FROZEN_CONFIG.json').read_text());defs=json.loads((root/'01_DEFINITION_REGISTRY.json').read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text());schema=(root/'02_SCHEMA.sql').read_text()
    checks['frozen_identity']=(config.get('config_id')==CONFIG_ID and config.get('engine_version')==ENGINE_VERSION and config.get('schema_version')==SCHEMA_VERSION and freeze.get('design_freeze_hash')==EXPECTED_DESIGN_FREEZE_HASH and defs.get('registry_hash')==EXPECTED_DEFINITION_REGISTRY_HASH and len(defs.get('definitions',{}))==EXPECTED_DEFINITION_COUNT and sha256_file(root/'02_SCHEMA.sql')==EXPECTED_SCHEMA_SHA256)
    if not checks['frozen_identity']:failures.append('frozen_identity_mismatch')
    evaluators=set(Group8Engine.evaluator_registry());frozen=set(defs['definitions']);checks['exact_45_evaluator_coverage']=(evaluators==frozen and len(evaluators)==45)
    if not checks['exact_45_evaluator_coverage']:failures.append({'evaluator_mismatch':{'missing':sorted(frozen-evaluators),'extra':sorted(evaluators-frozen)}})
    cols=schema_columns(schema);schema_hits=[]
    for table,columns in cols.items():
        words={x.lower() for x in [table,*columns]};hits=sorted(words&FORBIDDEN_SCHEMA_TOKENS)
        if hits:schema_hits.append({'table':table,'tokens':hits})
    checks['prohibited_output_schema_absent']=not schema_hits
    if schema_hits:failures.append({'prohibited_schema':schema_hits})
    engine_path=root/'code/moebot_group8_engine_v0_8_0.py';materializer_path=root/'code/group8_materialize_inputs.py';postprocessor_path=root/'code/group8_postprocess_v0_8_0.py';test_path=root/'tests/test_group8_engine_v0_8_0.py';lifecycle_test_path=root/'tests/test_group8_lifecycle_persistence_v0_8_0.py'
    engine_text=engine_path.read_text();materializer_text=materializer_path.read_text();postprocessor_text=postprocessor_path.read_text();future_refs=sorted(t for t in FORBIDDEN_TABLE_REFERENCES if t in engine_text or t in materializer_text or t in postprocessor_text)
    lifecycle_markers=['ensure_pattern_creation_state','ensure_initial_hypothesis_lifecycle','continuation_structure_valid','finalize_postprocessing','processing_checkpoint','invalidation_record','group8_audit_evidence','right_censored','completed_descriptive','contradicted']
    checks['lifecycle_persistence_hardening_present']=all(x in engine_text+postprocessor_text for x in lifecycle_markers)
    if not checks['lifecycle_persistence_hardening_present']:failures.append({'lifecycle_persistence_markers_missing':[x for x in lifecycle_markers if x not in engine_text+postprocessor_text]})
    checks['future_outcome_tables_not_consumed']=not future_refs
    if future_refs:failures.append({'future_outcome_table_reference':future_refs})
    tree=ast.parse(engine_text);bad_functions=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            tokens=set(re.findall(r'[a-z_]+',node.name.lower()))
            if tokens&FORBIDDEN_SCHEMA_TOKENS:bad_functions.append(node.name)
    checks['no_trading_action_functions']=not bad_functions
    if bad_functions:failures.append({'trading_action_functions':sorted(bad_functions)})
    checks['materializer_adapter_bound']=('required_columns' in materializer_text and 'copy_table' in materializer_text and "adapter['adapters']" in materializer_text)
    if not checks['materializer_adapter_bound']:failures.append('materializer_not_adapter_bound')
    checks['upstream_read_only_enforced']=("mode=ro&immutable=1" in materializer_text and "mode=ro&immutable=1" in engine_text)
    if not checks['upstream_read_only_enforced']:failures.append('upstream_read_only_not_enforced')
    causal_markers=[
        'availability_time < confirmation_time',
        'confirmation_time < event_time',
        'lifecycle before hypothesis availability',
        '_active_zone_status_at',
        'transition_time<=?',
        'interaction_time<=?',
    ]
    checks['causality_guards_present']=all(x in engine_text for x in causal_markers)
    checks['historical_zone_state_reconstruction_present']=all(x in engine_text for x in ['_active_zone_status_at','transition_time<=?','interaction_time<=?'])
    if not checks['causality_guards_present']:failures.append({'causality_guards_missing':[x for x in causal_markers if x not in engine_text]})
    if not checks['historical_zone_state_reconstruction_present']:failures.append('historical_zone_state_reconstruction_missing')
    checks['deterministic_identity_present']=all(x in engine_text for x in ['deterministic_id','canonical_json','stable_hash','conflicting deterministic duplicate'])
    if not checks['deterministic_identity_present']:failures.append('deterministic_identity_guards_missing')
    checks['2024_execution_not_embedded']=('2024' not in re.sub(r'EXPECTED_DEFINITION_COUNT\s*=\s*45','',engine_text))
    if not checks['2024_execution_not_embedded']:failures.append('engine_contains_2024_specific_execution_logic')
    hashes={'engine_sha256':file_hash(engine_path),'materializer_sha256':file_hash(materializer_path),'postprocessor_sha256':file_hash(postprocessor_path),'tests_sha256':file_hash(test_path),'lifecycle_tests_sha256':file_hash(lifecycle_test_path),'schema_sha256':file_hash(root/'02_SCHEMA.sql'),'definition_registry_file_sha256':file_hash(root/'01_DEFINITION_REGISTRY.json'),'frozen_config_file_sha256':file_hash(root/'FROZEN_CONFIG.json')}
    report={'format_version':1,'phase':'ENGINE_TECHNICAL_CANDIDATE_AUDIT','status':'PASS' if not failures else 'FAIL','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'definition_count':len(frozen),'checks':checks,'hashes':hashes,'failures':failures};report['report_hash']=stable_hash(report);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if not failures else 1

if __name__=='__main__':raise SystemExit(main())
