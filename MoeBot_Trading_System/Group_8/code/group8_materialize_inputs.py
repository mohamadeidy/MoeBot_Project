#!/usr/bin/env python3
"""Disk-safe verified input materializer for MoeBot Group 8 v0.8.0.

Each annual dependency is restored one at a time from the frozen Group 8 registry,
verified before row access, copied into a compact read-only staging SQLite using
only the exact frozen adapter columns, and then deleted. Upstream IDs are never
renamed or regenerated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ENGINE_VERSION="0.8.0"
SCHEMA_VERSION="8.0.0"
CONFIG_ID="cfg8_0e5a4dc3394efff2d2d54c20b0a93fba66b6ddd3d8e8a28a70292e6bb5755ded"
LOGICAL_LINEAGE="moebot-group8-upstream-corrected-v3-g7-v075-v1"


def shaf(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()


def q(name:str)->str:
    return '"'+name.replace('"','""')+'"'


def download(url:str,path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(url,timeout=300) as response,path.open('wb') as out:
        while True:
            b=response.read(8*1024*1024)
            if not b:break
            out.write(b)


def restore_record(rec:Mapping[str,Any],work:Path)->Path:
    chunks=[]
    for part in rec['parts']:
        p=work/part['filename'];download(part['url'],p)
        if p.stat().st_size!=int(part['size_bytes']) or shaf(p)!=part['sha256']:
            raise RuntimeError(f"part identity mismatch: {part['filename']}")
        chunks.append(p)
    z=work/rec['compressed_filename']
    with z.open('wb') as out:
        for p in chunks:
            with p.open('rb') as src:shutil.copyfileobj(src,out,16*1024*1024)
    if z.stat().st_size!=int(rec['compressed_size_bytes']) or shaf(z)!=rec['compressed_sha256']:
        raise RuntimeError(f"compressed identity mismatch: {z.name}")
    db=work/rec['database_filename']
    subprocess.run(['zstd','-q','-d','--long=31','-f',str(z),'-o',str(db)],check=True)
    if db.stat().st_size!=int(rec['database_size_bytes']) or shaf(db)!=rec['database_sha256']:
        raise RuntimeError(f"database identity mismatch: {db.name}")
    for p in chunks:p.unlink(missing_ok=True)
    z.unlink(missing_ok=True)
    return db


def verify_sqlite(db:Path)->sqlite3.Connection:
    con=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True)
    if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':
        con.close();raise RuntimeError(f'quick_check failed: {db.name}')
    if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        con.close();raise RuntimeError(f'integrity_check failed: {db.name}')
    fk=con.execute('PRAGMA foreign_key_check').fetchall()
    if fk:
        con.close();raise RuntimeError(f'foreign_key_check failed: {db.name}: {len(fk)}')
    con.row_factory=sqlite3.Row
    return con


def copy_table(src:sqlite3.Connection,dst:sqlite3.Connection,src_table:str,dst_table:str,required:list[str])->int:
    info={r['name']:r for r in src.execute(f'PRAGMA table_info({q(src_table)})')}
    missing=sorted(set(required)-set(info))
    if missing:raise RuntimeError(f'{src_table} missing adapter columns {missing}')
    dst.execute(f'DROP TABLE IF EXISTS {q(dst_table)}')
    defs=[]
    for c in required:
        typ=info[c]['type'] or ''
        defs.append(f'{q(c)} {typ}')
    dst.execute(f'CREATE TABLE {q(dst_table)} ({", ".join(defs)})')
    cols=', '.join(q(c) for c in required);marks=','.join('?' for _ in required)
    cur=src.execute(f'SELECT {cols} FROM {q(src_table)}')
    n=0
    while True:
        rows=cur.fetchmany(20000)
        if not rows:break
        dst.executemany(f'INSERT INTO {q(dst_table)} ({cols}) VALUES ({marks})',[tuple(r[c] for c in required) for r in rows])
        n+=len(rows);dst.commit()
    actual=set(required)
    for idx_cols in [('symbol','timeframe'),('timeframe','availability_time'),('timeframe','available_at'),('zone_id',),('pool_id',),('leg_id',),('fvg_id',),('event_id',),('state_id',),('candidate_id',),('definition_id',)]:
        if all(c in actual for c in idx_cols):
            name=f"ix_{dst_table}_{'_'.join(idx_cols)}".replace('-','_')
            dst.execute(f'CREATE INDEX IF NOT EXISTS {q(name)} ON {q(dst_table)} ({",".join(q(c) for c in idx_cols)})')
    dst.commit();return n


def metadata_increment_candidates(src:sqlite3.Connection)->dict[str,str]:
    tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'metadata' not in tables:return {}
    cols={r[1] for r in src.execute("PRAGMA table_info('metadata')")}
    if not {'key','value'}<=cols:return {}
    out={}
    for key,value in src.execute("SELECT key,value FROM metadata"):
        k=str(key).lower()
        if any(token in k for token in ('point','tick_size','ticksize','minimum_price_increment')):
            try:v=float(value)
            except (TypeError,ValueError):continue
            if v>0:out[f'verified_{key}']=str(value)
    return out


def create_manifest(dst:sqlite3.Connection, values:Mapping[str,str])->None:
    dst.execute('CREATE TABLE IF NOT EXISTS stage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    dst.execute('CREATE TABLE IF NOT EXISTS staging_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    for k,v in values.items():dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',(k,str(v)))
    dst.commit()


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    root=a.artifacts_root.resolve();reg=json.loads((root/'UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json').read_text());adapter=json.loads((root/'UPSTREAM_ADAPTER_MAP.json').read_text());freeze=json.loads((root/'DESIGN_FREEZE_MANIFEST.json').read_text())
    year=str(a.year)
    if reg.get('status')!='PASS' or year not in reg.get('years',{}):raise SystemExit('frozen annual dependency registry invalid')
    if adapter.get('adapter_map_hash')!=freeze.get('adapter_map_hash'):raise SystemExit('adapter/freeze hash mismatch')
    a.work_dir.mkdir(parents=True,exist_ok=True);a.output_db.parent.mkdir(parents=True,exist_ok=True);a.output_db.unlink(missing_ok=True)
    dst=sqlite3.connect(a.output_db);dst.execute('PRAGMA journal_mode=WAL');dst.execute('PRAGMA synchronous=NORMAL')
    identities={};table_counts={};failures=[]
    create_manifest(dst,{'status':'BUILDING','year':year,'engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'logical_dependency_lineage_id':LOGICAL_LINEAGE,'adapter_map_hash':adapter['adapter_map_hash']})
    records={'source':reg['source_databases'][year]};records.update(reg['years'][year]['manifest']['packages'])
    try:
        for group in ['source','group2','group3','group4','group5','group6','group7']:
            rec=records[group];gw=a.work_dir/group;gw.mkdir(parents=True,exist_ok=True);db=restore_record(rec,gw);src=verify_sqlite(db)
            identities[group]={'filename':rec['database_filename'],'size_bytes':int(rec['database_size_bytes']),'sha256':rec['database_sha256'],'engine_version':rec.get('engine_version'),'schema_version':rec.get('schema_version'),'config_id':rec.get('config_id')}
            for logical,arec in adapter['adapters'][group].items():table_counts[f'{group}__{logical}']=copy_table(src,dst,arec['table'],f'{group}__{logical}',list(arec['required_columns']))
            if group=='source':
                for k,v in metadata_increment_candidates(src).items():dst.execute('INSERT OR REPLACE INTO staging_metadata(key,value) VALUES(?,?)',(k,v))
                symbols=[r[0] for r in src.execute('SELECT DISTINCT symbol FROM bars ORDER BY symbol')]
                if len(symbols)==1:dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',('symbol',symbols[0]))
            src.close();db.unlink(missing_ok=True);shutil.rmtree(gw,ignore_errors=True);dst.commit()
        manifest_values={'status':'PASS','database_identities_json':json.dumps(identities,sort_keys=True,separators=(',',':')),'table_counts_json':json.dumps(table_counts,sort_keys=True,separators=(',',':'))}
        for k,v in manifest_values.items():dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',(k,v))
        dst.commit();qc=dst.execute('PRAGMA quick_check').fetchone()[0];ic=dst.execute('PRAGMA integrity_check').fetchone()[0]
        if qc!='ok' or ic!='ok':failures.append(f'staging_sqlite:{qc}:{ic}')
    except Exception as exc:
        failures.append(f'{type(exc).__name__}:{exc}');dst.execute('INSERT OR REPLACE INTO stage_manifest(key,value) VALUES(?,?)',('status','FAIL'));dst.commit()
    finally:dst.close()
    report={'format_version':1,'status':'PASS' if not failures else 'FAIL','year':a.year,'engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'logical_dependency_lineage_id':LOGICAL_LINEAGE,'database_identities':identities,'table_counts':table_counts,'disk_safe_sequential_materialization':True,'read_only_upstream':True,'failures':failures};report['report_hash']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest();a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0 if not failures else 1

if __name__=='__main__':raise SystemExit(main())
