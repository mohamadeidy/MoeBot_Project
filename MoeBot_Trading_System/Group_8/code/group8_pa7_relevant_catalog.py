#!/usr/bin/env python3
"""Build the minimal PA7 query projection required by frozen derived/global logic.

The full PA7 domain remains losslessly preserved in released shards. This catalog is
execution infrastructure only. It retains exactly the immutable PA7 candidates that
can affect downstream Group8 derived/global queries:
  pass 1: exact/failed/retest rows at real bounded-range levels, plus failed breakouts
          that match an actual core rejection candidate;
  pass 2: exact breakouts at the exhaustion levels discovered by pass 1.
No trading rule, threshold, candidate ID/hash, or domain artifact is changed.
"""
from __future__ import annotations

import argparse,bisect,hashlib,json,sqlite3
from pathlib import Path
from typing import Any,Iterable

KEEP_AT_RANGE_LEVEL={'pa_breakout_exact','pa_failed_breakout','pa_retest'}
EXACT='pa_breakout_exact';FAILED='pa_failed_breakout'


def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def _levels(con:sqlite3.Connection,table:str)->dict[tuple[str,str],list[float]]:
    out={}
    for sym,tf,level in con.execute(f'SELECT symbol,timeframe,level FROM {table} ORDER BY symbol,timeframe,level'):
        out.setdefault((str(sym),str(tf)),[]).append(float(level))
    return out


def _match(levels:dict[tuple[str,str],list[float]],symbol:str,tf:str,value:float|None)->bool:
    if value is None:return False
    arr=levels.get((str(symbol),str(tf)))
    if not arr:return False
    x=float(value);i=bisect.bisect_left(arr,x-1e-12)
    return i<len(arr) and abs(arr[i]-x)<=1e-12


def init_catalog(core_db:Path,output:Path)->dict[str,Any]:
    output.unlink(missing_ok=True);core=sqlite3.connect(f'file:{core_db.resolve()}?mode=ro&immutable=1',uri=True);out=sqlite3.connect(output)
    try:
        if core.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('core quick_check failed')
        out.executescript('''
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE pa7_candidate_catalog(
          candidate_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, symbol TEXT NOT NULL,
          timeframe TEXT NOT NULL, direction TEXT NOT NULL, source_bar_id INTEGER,
          related_source_bar_id INTEGER, event_time INTEGER NOT NULL, confirmation_time INTEGER NOT NULL,
          availability_time INTEGER NOT NULL, lower REAL, upper REAL, features_json TEXT NOT NULL,
          candidate_hash TEXT NOT NULL
        );
        CREATE INDEX ix_pa7cat_def_sym_tf_dir_avail ON pa7_candidate_catalog(definition_id,symbol,timeframe,direction,availability_time,candidate_id);
        CREATE INDEX ix_pa7cat_def_sym_tf_level_avail ON pa7_candidate_catalog(definition_id,symbol,timeframe,lower,availability_time,candidate_id);
        CREATE INDEX ix_pa7cat_failed_source_dir ON pa7_candidate_catalog(definition_id,source_bar_id,direction,candidate_id);
        CREATE TABLE target_range_level(symbol TEXT NOT NULL,timeframe TEXT NOT NULL,level REAL NOT NULL,PRIMARY KEY(symbol,timeframe,level)) WITHOUT ROWID;
        CREATE TABLE exhaustion_level(symbol TEXT NOT NULL,timeframe TEXT NOT NULL,level REAL NOT NULL,PRIMARY KEY(symbol,timeframe,level)) WITHOUT ROWID;
        CREATE TABLE rejection_key(source_bar_id INTEGER NOT NULL,direction TEXT NOT NULL,PRIMARY KEY(source_bar_id,direction)) WITHOUT ROWID;
        CREATE TABLE processed(phase INTEGER NOT NULL,shard_identity TEXT NOT NULL,PRIMARY KEY(phase,shard_identity)) WITHOUT ROWID;
        ''')
        for sym,tf,lo,hi in core.execute("SELECT symbol,timeframe,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'"):
            if lo is not None:out.execute('INSERT OR IGNORE INTO target_range_level VALUES(?,?,?)',(str(sym),str(tf),float(lo)))
            if hi is not None:out.execute('INSERT OR IGNORE INTO target_range_level VALUES(?,?,?)',(str(sym),str(tf),float(hi)))
        for bar,direction in core.execute("SELECT source_bar_id,direction FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') AND source_bar_id IS NOT NULL"):
            out.execute('INSERT OR IGNORE INTO rejection_key VALUES(?,?)',(int(bar),str(direction)))
        out.commit();r={'status':'PASS','target_range_levels':out.execute('SELECT COUNT(*) FROM target_range_level').fetchone()[0],'rejection_keys':out.execute('SELECT COUNT(*) FROM rejection_key').fetchone()[0],'domain_artifact':False,'free_only':True,'paid_runner_used':False,'paid_service_used':False}
        return r
    finally:core.close();out.close()


def _insert(out:sqlite3.Connection,row:sqlite3.Row)->bool:
    cols=('candidate_id','definition_id','symbol','timeframe','direction','source_bar_id','related_source_bar_id','event_time','confirmation_time','availability_time','lower','upper','features_json','candidate_hash')
    vals=tuple(row[c] for c in cols);cur=out.execute('INSERT OR IGNORE INTO pa7_candidate_catalog VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals)
    if cur.rowcount==1:return True
    prev=out.execute('SELECT candidate_hash FROM pa7_candidate_catalog WHERE candidate_id=?',(row['candidate_id'],)).fetchone()
    if prev is None or str(prev[0])!=str(row['candidate_hash']):raise RuntimeError(f'conflicting PA7 candidate duplicate:{row["candidate_id"]}')
    return False


def append_pass1(catalog:Path,shard_db:Path,shard_identity:str)->dict[str,Any]:
    out=sqlite3.connect(catalog);out.row_factory=sqlite3.Row;src=sqlite3.connect(f'file:{shard_db.resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row
    try:
        if out.execute('SELECT 1 FROM processed WHERE phase=1 AND shard_identity=?',(shard_identity,)).fetchone():raise RuntimeError(f'duplicate pass1 shard:{shard_identity}')
        range_levels=_levels(out,'target_range_level');rejections={(int(r[0]),str(r[1])) for r in out.execute('SELECT source_bar_id,direction FROM rejection_key')};inserted=matched_failed=0
        sql="SELECT candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_failed_breakout','pa_retest') ORDER BY candidate_id"
        for row in src.execute(sql):
            target=_match(range_levels,row['symbol'],row['timeframe'],row['lower']);rej=(row['definition_id']==FAILED and row['source_bar_id'] is not None and (int(row['source_bar_id']),str(row['direction'])) in rejections)
            if not target and not rej:continue
            if _insert(out,row):inserted+=1
            if rej:
                matched_failed+=1
                if row['lower'] is not None:out.execute('INSERT OR IGNORE INTO exhaustion_level VALUES(?,?,?)',(str(row['symbol']),str(row['timeframe']),float(row['lower'])))
        out.execute('INSERT INTO processed VALUES(1,?)',(shard_identity,));out.commit();return {'status':'PASS','phase':1,'inserted':inserted,'matched_failed_breakouts':matched_failed}
    finally:src.close();out.close()


def append_pass2(catalog:Path,shard_db:Path,shard_identity:str)->dict[str,Any]:
    out=sqlite3.connect(catalog);out.row_factory=sqlite3.Row;src=sqlite3.connect(f'file:{shard_db.resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row
    try:
        if out.execute('SELECT 1 FROM processed WHERE phase=2 AND shard_identity=?',(shard_identity,)).fetchone():raise RuntimeError(f'duplicate pass2 shard:{shard_identity}')
        levels=_levels(out,'exhaustion_level');inserted=0
        for row in src.execute("SELECT candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash FROM price_action_pattern_candidate WHERE definition_id='pa_breakout_exact' ORDER BY candidate_id"):
            if _match(levels,row['symbol'],row['timeframe'],row['lower']) and _insert(out,row):inserted+=1
        out.execute('INSERT INTO processed VALUES(2,?)',(shard_identity,));out.commit();return {'status':'PASS','phase':2,'inserted':inserted}
    finally:src.close();out.close()


def finalize(catalog:Path,report:Path)->dict[str,Any]:
    c=sqlite3.connect(catalog)
    try:
        h=hashlib.sha256();counts={r[0]:int(r[1]) for r in c.execute('SELECT definition_id,COUNT(*) FROM pa7_candidate_catalog GROUP BY definition_id ORDER BY definition_id')}
        for cid,ch in c.execute('SELECT candidate_id,candidate_hash FROM pa7_candidate_catalog ORDER BY candidate_id'):
            h.update(str(cid).encode());h.update(b'\0');h.update(str(ch).encode());h.update(b'\n')
        rec={'format_version':1,'status':'PASS','artifact_kind':'PA7_RELEVANT_QUERY_CATALOG','domain_artifact':False,'candidate_rows':int(c.execute('SELECT COUNT(*) FROM pa7_candidate_catalog').fetchone()[0]),'definition_counts':counts,'target_range_level_count':int(c.execute('SELECT COUNT(*) FROM target_range_level').fetchone()[0]),'exhaustion_level_count':int(c.execute('SELECT COUNT(*) FROM exhaustion_level').fetchone()[0]),'pass1_shard_count':int(c.execute('SELECT COUNT(*) FROM processed WHERE phase=1').fetchone()[0]),'pass2_shard_count':int(c.execute('SELECT COUNT(*) FROM processed WHERE phase=2').fetchone()[0]),'logical_candidate_sha256':h.hexdigest(),'quick_check':c.execute('PRAGMA quick_check').fetchone()[0],'integrity_check':c.execute('PRAGMA integrity_check').fetchone()[0],'free_only':True,'paid_runner_used':False,'paid_service_used':False};rec['report_hash']=stable(rec);report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec
    finally:c.close()


def main()->int:
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('init');a.add_argument('--core-db',type=Path,required=True);a.add_argument('--catalog',type=Path,required=True)
    for name in ('pass1','pass2'):
        x=s.add_parser(name);x.add_argument('--catalog',type=Path,required=True);x.add_argument('--shard-db',type=Path,required=True);x.add_argument('--shard-identity',required=True)
    f=s.add_parser('finalize');f.add_argument('--catalog',type=Path,required=True);f.add_argument('--report',type=Path,required=True)
    z=p.parse_args()
    if z.cmd=='init':r=init_catalog(z.core_db,z.catalog)
    elif z.cmd=='pass1':r=append_pass1(z.catalog,z.shard_db,z.shard_identity)
    elif z.cmd=='pass2':r=append_pass2(z.catalog,z.shard_db,z.shard_identity)
    else:r=finalize(z.catalog,z.report)
    print(json.dumps(r,indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
