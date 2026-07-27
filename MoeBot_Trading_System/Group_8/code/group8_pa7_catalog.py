#!/usr/bin/env python3
"""Build a compact query catalog from verified PA7 domain shards.

The catalog is execution infrastructure, not a domain artifact. It retains immutable
candidate IDs/hashes and only columns required by PA7-dependent Group8 logic.
It supports streaming append so annual release bundles can be verified, projected,
and deleted one at a time without ever co-locating the full PA7 domain on disk.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path
from typing import Iterable,Any

CHAIN={'pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer','pa_failed_breakout','pa_retest'}
INSERT_SQL='''INSERT INTO pa7_candidate_catalog(candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def shaf(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()

def init_catalog(output:Path,*,replace:bool=False)->None:
    if replace:output.unlink(missing_ok=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    out=sqlite3.connect(output)
    try:
        out.executescript('''
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY;
        CREATE TABLE IF NOT EXISTS pa7_candidate_catalog(
          candidate_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, symbol TEXT NOT NULL,
          timeframe TEXT NOT NULL, direction TEXT NOT NULL, source_bar_id INTEGER,
          related_source_bar_id INTEGER, event_time INTEGER NOT NULL, confirmation_time INTEGER NOT NULL,
          availability_time INTEGER NOT NULL, lower REAL, upper REAL, features_json TEXT NOT NULL,
          candidate_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pa7_catalog_source_shard(
          shard_key TEXT PRIMARY KEY, filename TEXT NOT NULL, file_size_bytes INTEGER NOT NULL,
          file_sha256 TEXT NOT NULL, candidate_rows INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_pa7cat_def_sym_tf_dir_avail ON pa7_candidate_catalog(definition_id,symbol,timeframe,direction,availability_time,candidate_id);
        CREATE INDEX IF NOT EXISTS ix_pa7cat_def_sym_tf_level_avail ON pa7_candidate_catalog(definition_id,symbol,timeframe,lower,availability_time,candidate_id);
        CREATE INDEX IF NOT EXISTS ix_pa7cat_failed_source_dir ON pa7_candidate_catalog(definition_id,source_bar_id,direction,candidate_id);
        ''');out.commit()
    finally:out.close()

def append_shards(output:Path,shards:Iterable[Path])->dict[str,Any]:
    if not output.is_file():init_catalog(output)
    out=sqlite3.connect(output);out.row_factory=sqlite3.Row;added=[];inserted=0
    try:
        for path in sorted(Path(p) for p in shards):
            if not path.is_file():raise RuntimeError(f'missing shard:{path}')
            file_sha=shaf(path);file_size=path.stat().st_size;shard_key=f'{path.name}:{file_size}:{file_sha}'
            if out.execute('SELECT 1 FROM pa7_catalog_source_shard WHERE shard_key=?',(shard_key,)).fetchone():raise RuntimeError(f'shard already appended:{path.name}')
            con=sqlite3.connect(path);con.row_factory=sqlite3.Row
            try:
                qc=con.execute('PRAGMA quick_check').fetchone()[0];ic=con.execute('PRAGMA integrity_check').fetchone()[0];fk=con.execute('PRAGMA foreign_key_check').fetchall()
                if qc!='ok' or ic!='ok' or fk:raise RuntimeError(f'invalid shard:{path}:{qc}:{ic}:fk={len(fk)}')
                n=0
                rows=con.execute("SELECT candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash FROM price_action_pattern_candidate ORDER BY candidate_id")
                for r in rows:
                    if r['definition_id'] not in CHAIN:raise RuntimeError(f'non-PA7 candidate in shard:{r["definition_id"]}')
                    try:out.execute(INSERT_SQL,tuple(r))
                    except sqlite3.IntegrityError as exc:
                        existing=out.execute('SELECT candidate_hash FROM pa7_candidate_catalog WHERE candidate_id=?',(r['candidate_id'],)).fetchone()
                        if existing is None or str(existing[0])!=str(r['candidate_hash']):raise RuntimeError(f'conflicting duplicate PA7 candidate:{r["candidate_id"]}') from exc
                        raise RuntimeError(f'duplicate PA7 domain candidate across shards:{r["candidate_id"]}') from exc
                    n+=1;inserted+=1
                actual=int(con.execute('SELECT COUNT(*) FROM price_action_pattern_candidate').fetchone()[0])
                if n!=actual:raise RuntimeError(f'candidate projection count mismatch:{path}:{n}!={actual}')
            finally:con.close()
            out.execute('INSERT INTO pa7_catalog_source_shard(shard_key,filename,file_size_bytes,file_sha256,candidate_rows) VALUES(?,?,?,?,?)',(shard_key,path.name,file_size,file_sha,n));out.commit();added.append({'filename':path.name,'file_size_bytes':file_size,'file_sha256':file_sha,'candidate_rows':n})
        return {'status':'PASS','appended_shards':added,'inserted_candidates':inserted}
    finally:out.close()

def finalize_catalog(output:Path)->dict[str,Any]:
    out=sqlite3.connect(output);out.row_factory=sqlite3.Row
    try:
        h=hashlib.sha256();counts={str(r[0]):int(r[1]) for r in out.execute('SELECT definition_id,COUNT(*) FROM pa7_candidate_catalog GROUP BY definition_id ORDER BY definition_id')};n=0
        for r in out.execute('SELECT candidate_id,candidate_hash FROM pa7_candidate_catalog ORDER BY candidate_id'):
            h.update(str(r[0]).encode());h.update(b'\0');h.update(str(r[1]).encode());h.update(b'\n');n+=1
        sources=[{'filename':str(r['filename']),'file_size_bytes':int(r['file_size_bytes']),'file_sha256':str(r['file_sha256']),'candidate_rows':int(r['candidate_rows'])} for r in out.execute('SELECT * FROM pa7_catalog_source_shard ORDER BY filename,shard_key')]
        if sum(x['candidate_rows'] for x in sources)!=n:raise RuntimeError(f'catalog/source candidate total mismatch:{sum(x["candidate_rows"] for x in sources)}!={n}')
        qc=out.execute('PRAGMA quick_check').fetchone()[0];ic=out.execute('PRAGMA integrity_check').fetchone()[0]
        if qc!='ok' or ic!='ok':raise RuntimeError(f'catalog SQLite validation failed:{qc}:{ic}')
        report={'format_version':2,'status':'PASS','artifact_kind':'PA7_QUERY_CATALOG','domain_artifact':False,'streaming_append_supported':True,'candidate_rows':n,'definition_counts':counts,'logical_candidate_sha256':h.hexdigest(),'source_shard_count':len(sources),'source_shards':sources,'quick_check':qc,'integrity_check':ic};report['report_hash']=stable(report);return report
    finally:out.close()

def build_catalog(shards:Iterable[Path],output:Path)->dict[str,Any]:
    init_catalog(output,replace=True);append_shards(output,shards);return finalize_catalog(output)

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path);p.add_argument('--append',action='store_true');p.add_argument('--finalize-only',action='store_true');p.add_argument('shards',nargs='*',type=Path);a=p.parse_args()
    if a.append and a.finalize_only:raise SystemExit('--append and --finalize-only are mutually exclusive')
    if a.finalize_only:r=finalize_catalog(a.output)
    elif a.append:
        if not a.shards:raise SystemExit('--append requires at least one shard')
        ar=append_shards(a.output,a.shards);r={**ar,'catalog':finalize_catalog(a.output)}
    else:
        if not a.shards:raise SystemExit('catalog build requires at least one shard')
        r=build_catalog(a.shards,a.output)
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
