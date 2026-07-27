#!/usr/bin/env python3
"""Streaming equivalent of the frozen Group 8 lossless shard-union validator.

Each shard is verified and reduced to immutable (ID, hash) plus Group8-reference
metadata before the raw shard can be deleted. The final ledger fingerprint is
therefore lossless for the same union invariants while avoiding co-location of
all annual shard databases on a standard free runner.
"""
from __future__ import annotations

import argparse,hashlib,json,sqlite3
from pathlib import Path
from typing import Any

from group8_shard_union_validator import DOMAIN_TABLES,REGISTRY_TABLES,GROUP8_REF_COLUMNS,EXPECTED_CONTRACT,EXPECTED_FREEZE,EXPECTED_ENGINE,stable_hash,sha256_file,_tables,_json_refs


def init_ledger(path:Path,*,year:int,symbol:str,full_annual_union:bool)->None:
    path.unlink(missing_ok=True);c=sqlite3.connect(path)
    try:
        c.executescript('''
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE shard(shard_id TEXT PRIMARY KEY,manifest_hash TEXT NOT NULL,file_sha256 TEXT NOT NULL,file_size_bytes INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE domain(table_name TEXT NOT NULL,row_id TEXT NOT NULL,row_hash TEXT NOT NULL,shard_id TEXT NOT NULL,PRIMARY KEY(table_name,row_id)) WITHOUT ROWID;
        CREATE TABLE registry(table_name TEXT NOT NULL,row_id TEXT NOT NULL,row_hash TEXT NOT NULL,PRIMARY KEY(table_name,row_id)) WITHOUT ROWID;
        CREATE TABLE refs(source_table TEXT NOT NULL,source_id TEXT NOT NULL,target_type TEXT NOT NULL,target_id TEXT NOT NULL,shard_id TEXT NOT NULL);
        CREATE INDEX ix_stream_refs_target ON refs(target_id);
        ''')
        for k,v in {'year':str(year),'symbol':symbol,'full_annual_union':'1' if full_annual_union else '0','storage_contract_hash':EXPECTED_CONTRACT,'design_freeze_hash':EXPECTED_FREEZE,'engine_sha256':EXPECTED_ENGINE}.items():c.execute('INSERT INTO meta VALUES(?,?)',(k,v))
        c.commit()
    finally:c.close()


def _meta(c:sqlite3.Connection)->dict[str,str]:return {r[0]:r[1] for r in c.execute('SELECT key,value FROM meta')}


def append_shard(ledger:Path,db:Path,manifest_path:Path)->dict[str,Any]:
    lc=sqlite3.connect(ledger);lc.row_factory=sqlite3.Row
    try:
        meta=_meta(lc);year=int(meta['year']);symbol=meta['symbol'];m=json.loads(manifest_path.read_text());q=dict(m);saved=q.pop('manifest_hash',None)
        if saved!=stable_hash(q):raise RuntimeError(f'manifest self-hash mismatch:{manifest_path}')
        for k,e in (('year',year),('symbol',symbol),('storage_contract_hash',EXPECTED_CONTRACT),('design_freeze_hash',EXPECTED_FREEZE),('engine_sha256',EXPECTED_ENGINE)):
            if m.get(k)!=e:raise RuntimeError(f'manifest identity mismatch {k}:{manifest_path}')
        if sha256_file(db)!=m.get('sha256') or db.stat().st_size!=int(m.get('file_size_bytes',-1)):raise RuntimeError(f'shard file identity mismatch:{db}')
        sid=str(m['shard_id'])
        if lc.execute('SELECT 1 FROM shard WHERE shard_id=?',(sid,)).fetchone():raise RuntimeError(f'duplicate shard append:{sid}')
        sc=sqlite3.connect(f'file:{db.resolve()}?mode=ro&immutable=1',uri=True);sc.row_factory=sqlite3.Row
        try:
            if sc.execute('PRAGMA quick_check').fetchone()[0]!='ok' or sc.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError(f'sqlite check failed:{db}')
            if sc.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError(f'foreign-key errors:{db}')
            existing=_tables(sc);domain_rows=registry_rows=ref_rows=0
            for table,(idc,hc) in DOMAIN_TABLES.items():
                if table not in existing:continue
                cols={r[1] for r in sc.execute(f'PRAGMA table_info("{table}")')}
                refcols=tuple(x for x in GROUP8_REF_COLUMNS.get(table,()) if x in cols)
                select=[idc,hc,*refcols]
                for r in sc.execute(f'SELECT {",".join(chr(34)+x+chr(34) for x in select)} FROM "{table}"'):
                    rid=str(r[idc]);rh=str(r[hc])
                    try:lc.execute('INSERT INTO domain VALUES(?,?,?,?)',(table,rid,rh,sid))
                    except sqlite3.IntegrityError:
                        prev=lc.execute('SELECT row_hash,shard_id FROM domain WHERE table_name=? AND row_id=?',(table,rid)).fetchone();raise RuntimeError(f'duplicate domain ID across shards:{table}:{rid}:{prev[1]}:{sid}')
                    domain_rows+=1
                    for rc in refcols:
                        for ref in _json_refs(r[rc]):
                            if str(ref.get('source_group','')).lower()!='group8':continue
                            target=str(ref.get('source_id') or '')
                            if target:
                                lc.execute('INSERT INTO refs VALUES(?,?,?,?,?)',(table,rid,str(ref.get('source_type') or ''),target,sid));ref_rows+=1
            for table,(idc,hc) in REGISTRY_TABLES.items():
                if table not in existing:continue
                for rid,rh in sc.execute(f'SELECT "{idc}","{hc}" FROM "{table}"'):
                    rid=str(rid);rh=str(rh);prev=lc.execute('SELECT row_hash FROM registry WHERE table_name=? AND row_id=?',(table,rid)).fetchone()
                    if prev is None:lc.execute('INSERT INTO registry VALUES(?,?,?)',(table,rid,rh));registry_rows+=1
                    elif str(prev[0])!=rh:raise RuntimeError(f'registry conflict:{table}:{rid}')
        finally:sc.close()
        lc.execute('INSERT INTO shard VALUES(?,?,?,?)',(sid,saved,m['sha256'],int(m['file_size_bytes'])));lc.commit()
        return {'status':'PASS','shard_id':sid,'domain_rows':domain_rows,'registry_rows_added':registry_rows,'group8_refs_added':ref_rows}
    finally:lc.close()


def finalize(ledger:Path,output:Path)->dict[str,Any]:
    c=sqlite3.connect(ledger)
    try:
        meta=_meta(c);full=meta['full_annual_union']=='1';shard_count=int(c.execute('SELECT COUNT(*) FROM shard').fetchone()[0]);total_bytes=int(c.execute('SELECT COALESCE(SUM(file_size_bytes),0) FROM shard').fetchone()[0])
        unresolved=[]
        for st,sid,tt,tid,sh in c.execute('SELECT source_table,source_id,target_type,target_id,shard_id FROM refs ORDER BY target_id'):
            if c.execute('SELECT 1 FROM domain WHERE row_id=? LIMIT 1',(tid,)).fetchone() is None:unresolved.append({'source_table':st,'source_id':sid,'target_type':tt,'target_id':tid,'shard_id':sh})
        if full and unresolved:raise RuntimeError(f'unresolved cross-shard Group8 refs:{unresolved[:5]}')
        counts={};hashes={}
        for table in DOMAIN_TABLES:
            n=int(c.execute('SELECT COUNT(*) FROM domain WHERE table_name=?',(table,)).fetchone()[0])
            if not n:continue
            h=hashlib.sha256()
            for rid,rh in c.execute('SELECT row_id,row_hash FROM domain WHERE table_name=? ORDER BY row_id',(table,)):
                h.update(str(rid).encode());h.update(b'\0');h.update(str(rh).encode());h.update(b'\n')
            counts[table]=n;hashes[table]=h.hexdigest()
        gp={'tables':{t:{'count':counts[t],'logical_sha256':hashes[t]} for t in sorted(counts)}};global_sha=stable_hash(gp)
        rec={'format_version':1,'status':'PASS','year':int(meta['year']),'symbol':meta['symbol'],'full_annual_union':full,'shard_count':shard_count,'total_shard_bytes':total_bytes,'storage_contract_hash':meta['storage_contract_hash'],'design_freeze_hash':meta['design_freeze_hash'],'engine_sha256':meta['engine_sha256'],'table_row_counts':counts,'table_logical_sha256':hashes,'global_logical_sha256':global_sha,'unresolved_group8_reference_count':len(unresolved),'unresolved_group8_reference_sample':unresolved[:20],'duplicate_domain_id_count':0,'registry_conflict_count':0,'oos_2024_accessed':int(meta['year'])==2024}
        rec['report_hash']=stable_hash(rec);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec
    finally:c.close()


def main()->int:
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('init');a.add_argument('--ledger',type=Path,required=True);a.add_argument('--year',type=int,required=True);a.add_argument('--symbol',required=True);a.add_argument('--full-annual-union',action='store_true')
    b=sub.add_parser('append');b.add_argument('--ledger',type=Path,required=True);b.add_argument('--database',type=Path,required=True);b.add_argument('--manifest',type=Path,required=True)
    d=sub.add_parser('finalize');d.add_argument('--ledger',type=Path,required=True);d.add_argument('--output',type=Path,required=True)
    x=p.parse_args()
    if x.cmd=='init':init_ledger(x.ledger,year=x.year,symbol=x.symbol,full_annual_union=x.full_annual_union);r={'status':'PASS'}
    elif x.cmd=='append':r=append_shard(x.ledger,x.database,x.manifest)
    else:r=finalize(x.ledger,x.output)
    print(json.dumps(r,indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
