#!/usr/bin/env python3
"""Generate Group 8 schema candidate v2 from the reviewed draft schema.

Changes are governance/persistence hardening only: bind the annual lineage bridge,
record every frozen dependency hash, and enforce append-only immutability on all
registry/research/evidence rows. Processing checkpoints remain mutable by design.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

IMMUTABLE_TABLES=(
'config_registry','dataset_registry','dependency_registry','upstream_id_bridge','school_registry',
'pattern_definition_registry','interpretation_definition_registry','price_action_pattern_candidate',
'price_action_pattern_state','school_interpretation','shared_evidence','conflicting_evidence',
'narrative_hypothesis','hypothesis_lifecycle_event','multi_timeframe_context_relation',
'evidence_chain','invalidation_record','group8_audit_evidence')
EXISTING_TRIGGER_TABLES={'price_action_pattern_candidate','school_interpretation','narrative_hypothesis','shared_evidence','conflicting_evidence'}

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--draft',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 sql=a.draft.read_text(encoding='utf-8')
 start=sql.index('CREATE TABLE IF NOT EXISTS dataset_registry(');end=sql.index('CREATE TABLE IF NOT EXISTS dependency_registry(')
 dataset='''CREATE TABLE IF NOT EXISTS dataset_registry(
    dataset_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    year INTEGER NOT NULL,
    lineage TEXT NOT NULL,
    source_db_filename TEXT NOT NULL,
    source_db_size_bytes INTEGER NOT NULL,
    source_db_sha256 TEXT NOT NULL,
    group7_db_filename TEXT NOT NULL,
    group7_db_size_bytes INTEGER NOT NULL,
    group7_db_sha256 TEXT NOT NULL,
    group7_recovery_anchor_tag TEXT NOT NULL,
    group7_recovery_anchor_commit_sha TEXT NOT NULL,
    group7_source_closure_tag TEXT NOT NULL,
    group7_source_closure_commit_sha TEXT NOT NULL,
    upstream_lineage_bridge_hash TEXT NOT NULL,
    annual_dependency_registry_hash TEXT NOT NULL,
    adapter_map_hash TEXT NOT NULL,
    categorical_dictionary_hash TEXT NOT NULL,
    value_bindings_hash TEXT NOT NULL,
    definition_registry_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    record_hash TEXT NOT NULL
);

'''
 sql=sql[:start]+dataset+sql[end:]
 bridge='''CREATE TABLE IF NOT EXISTS upstream_id_bridge(
    source_group TEXT NOT NULL,
    published_id TEXT NOT NULL,
    corrected_v3_id TEXT NOT NULL,
    mapping_kind TEXT NOT NULL CHECK(mapping_kind IN ('identity','explicit_bijective')),
    evidence_json TEXT NOT NULL,
    bridge_hash TEXT NOT NULL,
    PRIMARY KEY(source_group,published_id),
    UNIQUE(source_group,corrected_v3_id)
);

'''
 pos=sql.index('CREATE TABLE IF NOT EXISTS school_registry(');sql=sql[:pos]+bridge+sql[pos:]
 pos=sql.index('CREATE TRIGGER IF NOT EXISTS no_update_price_action_pattern_candidate')
 sql=sql[:pos]+"CREATE INDEX IF NOT EXISTS ix_bridge_corrected_id\n    ON upstream_id_bridge(source_group,corrected_v3_id);\n\n"+sql[pos:]
 extra=['','-- All registries, creation records, evidence, lifecycle and invalidation rows are append-only.']
 for table in IMMUTABLE_TABLES:
  if table in EXISTING_TRIGGER_TABLES:continue
  extra.append(f"CREATE TRIGGER IF NOT EXISTS no_update_{table}\nBEFORE UPDATE ON {table} BEGIN\n    SELECT RAISE(ABORT,'immutable record: {table}');\nEND;")
  extra.append(f"CREATE TRIGGER IF NOT EXISTS no_delete_{table}\nBEFORE DELETE ON {table} BEGIN\n    SELECT RAISE(ABORT,'immutable record: {table}');\nEND;")
 sql=sql.rstrip()+'\n'+'\n'.join(extra)+'\n'
 con=sqlite3.connect(':memory:');con.executescript(sql)
 tables=sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"));triggers=sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))
 missing=[]
 for table in IMMUTABLE_TABLES:
  for prefix in ('no_update_','no_delete_'):
   if prefix+table not in triggers:missing.append(prefix+table)
 bridge_cols=[r[1] for r in con.execute("PRAGMA table_info('upstream_id_bridge')")]
 dataset_cols=[r[1] for r in con.execute("PRAGMA table_info('dataset_registry')")]
 con.close();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(sql,encoding='utf-8')
 report={'format_version':1,'status':'PASS' if not missing else 'FAIL','source_draft':a.draft.name,'output':a.output.name,'schema_sha256':hashlib.sha256(sql.encode()).hexdigest(),'table_count':len(tables),'trigger_count':len(triggers),'immutable_table_count':len(IMMUTABLE_TABLES),'missing_immutability_triggers':missing,'bridge_columns':bridge_cols,'dataset_columns':dataset_cols}
 report['report_hash']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest();a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
