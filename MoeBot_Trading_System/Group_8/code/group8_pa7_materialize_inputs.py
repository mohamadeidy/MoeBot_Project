#!/usr/bin/env python3
"""Materialize only frozen upstream tables actually consumed by PA7 shard jobs.

The full frozen dependency identities remain recorded in stage_manifest, but only
source + Groups4-7 are downloaded/restored because Groups2-3 are not read by the
PA7 chain. All consumed databases and copied adapter columns are verified exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from group8_materialize_inputs import (
    CONFIG_ID,
    ENGINE_VERSION,
    LOGICAL_LINEAGE,
    SCHEMA_VERSION,
    copy_table,
    create_manifest,
    metadata_increment_candidates,
    restore_record,
    verify_sqlite,
)
from group8_pa7_shard_executor import PA7_REQUIRED_TABLES


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def main() -> int:
    p=argparse.ArgumentParser();p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    root=a.artifacts_root.resolve();reg=json.loads((root/'UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json').read_text());adapter=json.loads((root/'UPSTREAM_ADAPTER_MAP.json').read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text());year=str(a.year)
    if a.year==2024:
        status=json.loads((root/'STATUS.json').read_text())
        if status.get('annual_execution_2024_authorized') is not True:raise SystemExit('2024 OOS is forbidden')
    if reg.get('status')!='PASS' or year not in reg.get('years',{}):raise SystemExit('frozen annual dependency registry invalid')
    if adapter.get('adapter_map_hash')!=freeze.get('adapter_map_hash'):raise SystemExit('adapter/freeze hash mismatch')
    records={'source':reg['source_databases'][year]};records.update(reg['years'][year]['manifest']['packages'])
    all_groups=['source','group2','group3','group4','group5','group6','group7'];materialized=list(PA7_REQUIRED_TABLES)
    identities={g:{'filename':records[g]['database_filename'],'size_bytes':int(records[g]['database_size_bytes']),'sha256':records[g]['database_sha256'],'engine_version':records[g].get('engine_version'),'schema_version':records[g].get('schema_version'),'config_id':records[g].get('config_id')} for g in all_groups}
    a.work_dir.mkdir(parents=True,exist_ok=True);a.output_db.parent.mkdir(parents=True,exist_ok=True);a.output_db.unlink(missing_ok=True)
    dst=sqlite3.connect(a.output_db);dst.execute('PRAGMA journal_mode=WAL');dst.execute('PRAGMA synchronous=NORMAL');table_counts={};verified={};failures=[]
    create_manifest(dst,{'status':'BUILDING','year':year,'engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'logical_dependency_lineage_id':LOGICAL_LINEAGE,'adapter_map_hash':adapter['adapter_map_hash'],'materialization_scope':'PA7_COMPACT_V1','materialized_groups_json':json.dumps(materialized,separators=(',',':')),'database_identities_json':json.dumps(identities,sort_keys=True,separators=(',',':'))})
    try:
        for group in materialized:
            rec=records[group];gw=a.work_dir/group;gw.mkdir(parents=True,exist_ok=True);db=restore_record(rec,gw);src=verify_sqlite(db);verified[group]={'database_sha256':rec['database_sha256'],'database_size_bytes':int(rec['database_size_bytes'])}
            for logical in PA7_REQUIRED_TABLES[group]:
                arec=adapter['adapters'][group][logical];table_counts[f'{group}__{logical}']=copy_table(src,dst,arec['table'],f'{group}__{logical}',list(arec['required_columns']))
            if group=='source':
                for k,v in metadata_increment_candidates(src).items():dst.execute('INSERT OR REPLACE INTO staging_metadata(key,value) VALUES(?,?)',(k,v))
                table=adapter['adapters']['source']['bars']['table'];symbols=[r[0] for r in src.execute(f'SELECT DISTINCT symbol FROM "{table}" ORDER BY symbol')]
                if len(symbols)==1:dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',('symbol',symbols[0]))
            src.close();db.unlink(missing_ok=True);shutil.rmtree(gw,ignore_errors=True);dst.commit()
        for k,v in {'status':'PASS','table_counts_json':json.dumps(table_counts,sort_keys=True,separators=(',',':')),'verified_materialized_groups_json':json.dumps(verified,sort_keys=True,separators=(',',':'))}.items():dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',(k,v))
        dst.commit();qc=dst.execute('PRAGMA quick_check').fetchone()[0];ic=dst.execute('PRAGMA integrity_check').fetchone()[0]
        if qc!='ok' or ic!='ok':failures.append(f'staging_sqlite:{qc}:{ic}')
    except Exception as exc:
        failures.append(f'{type(exc).__name__}:{exc}');dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',('status','FAIL'));dst.commit()
    finally:dst.close()
    report={'format_version':1,'status':'PASS' if not failures else 'FAIL','scope':'PA7_COMPACT_V1','year':a.year,'engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'logical_dependency_lineage_id':LOGICAL_LINEAGE,'database_identities':identities,'verified_materialized_groups':verified,'omitted_nonconsumed_groups':['group2','group3'],'table_counts':table_counts,'read_only_upstream':True,'oos_2024_accessed':a.year==2024,'failures':failures};report['report_hash']=stable_hash(report);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if not failures else 1

if __name__=='__main__':raise SystemExit(main())
