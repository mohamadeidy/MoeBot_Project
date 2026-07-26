#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()


def q(name:str)->str:
    return '"'+name.replace('"','""')+'"'


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-db',type=Path,required=True)
    ap.add_argument('--output-db',type=Path,required=True)
    ap.add_argument('--adapter-map',type=Path,required=True)
    ap.add_argument('--group',required=True)
    ap.add_argument('--expected-sha256')
    ap.add_argument('--expected-size',type=int)
    ap.add_argument('--report',type=Path,required=True)
    a=ap.parse_args()
    amap=json.loads(a.adapter_map.read_text())
    if amap.get('status')!='PASS': raise SystemExit('adapter map not PASS')
    adapters=amap['adapters'].get(a.group)
    if not adapters: raise SystemExit(f'no adapters for {a.group}')
    size=a.input_db.stat().st_size; sha=sha256_file(a.input_db)
    failures=[]
    if a.expected_size is not None and size!=a.expected_size: failures.append('source_size')
    if a.expected_sha256 and sha!=a.expected_sha256: failures.append('source_sha256')
    src=sqlite3.connect(f'file:{a.input_db.resolve()}?mode=ro&immutable=1',uri=True); src.row_factory=sqlite3.Row
    quick=src.execute('PRAGMA quick_check').fetchone()[0]; integrity=src.execute('PRAGMA integrity_check').fetchone()[0]; fk=len(src.execute('PRAGMA foreign_key_check').fetchall())
    if quick!='ok' or integrity!='ok' or fk: failures.append('source_sqlite')
    a.output_db.parent.mkdir(parents=True,exist_ok=True); a.output_db.unlink(missing_ok=True)
    out=sqlite3.connect(str(a.output_db)); out.execute('PRAGMA journal_mode=OFF');out.execute('PRAGMA synchronous=OFF');out.execute('PRAGMA temp_store=FILE')
    copied={}
    try:
        existing={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,rec in sorted(adapters.items()):
            if table not in existing:
                failures.append(f'missing_table:{table}'); continue
            required=list(rec['required_columns'])
            info={r[1]:r for r in src.execute(f'PRAGMA table_info({q(table)})')}
            missing=[c for c in required if c not in info]
            if missing:
                failures.append(f'missing_columns:{table}:{missing}');continue
            defs=[]
            for col in required:
                typ=info[col][2] or 'BLOB'
                defs.append(f'{q(col)} {typ}')
            out.execute(f'CREATE TABLE {q(table)} ({", ".join(defs)})')
            cols=', '.join(q(c) for c in required)
            cur=src.execute(f'SELECT {cols} FROM {q(table)}')
            sql=f'INSERT INTO {q(table)} ({cols}) VALUES ({",".join("?" for _ in required)})'
            n=0;buf=[]
            for row in cur:
                buf.append(tuple(row[c] for c in required))
                if len(buf)>=5000:
                    out.executemany(sql,buf); n+=len(buf);buf.clear()
            if buf: out.executemany(sql,buf);n+=len(buf)
            copied[table]={'rows':n,'columns':required,'adapter_hash':rec['adapter_hash']}
            colset=set(required)
            for candidates in [
                ('timeframe','availability_time'),('timeframe','available_at'),('timeframe','close_time'),('timeframe','resolved_time'),
                ('timeframe','interaction_time'),('timeframe','transition_time'),('timeframe','bar_id'),('symbol','timeframe'),
                ('zone_id',),('pool_id',),('event_id',),('state_id',),('fvg_id',),('leg_id',),('definition_id',),('source_id',),('subject_id',),
            ]:
                if all(c in colset for c in candidates):
                    idx='idx_'+table+'_'+'_'.join(candidates)
                    out.execute(f'CREATE INDEX IF NOT EXISTS {q(idx)} ON {q(table)} ({", ".join(q(c) for c in candidates)})')
        out.commit()
    finally:
        src.close();out.close()
    snap_sha=sha256_file(a.output_db) if a.output_db.exists() else None
    con=sqlite3.connect(f'file:{a.output_db.resolve()}?mode=ro&immutable=1',uri=True) if a.output_db.exists() else None
    snap_quick=con.execute('PRAGMA quick_check').fetchone()[0] if con else None
    if con: con.close()
    if snap_quick!='ok': failures.append('snapshot_sqlite')
    report={'format_version':1,'status':'PASS' if not failures else 'FAIL','group':a.group,
            'source_database':{'filename':a.input_db.name,'size_bytes':size,'sha256':sha,'sqlite':{'quick_check':quick,'integrity_check':integrity,'foreign_key_errors':fk}},
            'snapshot':{'filename':a.output_db.name,'size_bytes':a.output_db.stat().st_size if a.output_db.exists() else 0,'sha256':snap_sha,'quick_check':snap_quick,'tables':copied},
            'adapter_map_hash':amap['adapter_map_hash'],'failures':failures}
    payload=dict(report);report['report_hash']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'group':a.group,'snapshot_size':report['snapshot']['size_bytes'],'report_hash':report['report_hash'],'failures':failures},indent=2))
    return 0 if not failures else 1

if __name__=='__main__': raise SystemExit(main())
