#!/usr/bin/env python3
"""Distributed FREE-only construction of the exact PA7 relevant-query catalog.

Each worker bundle is read once. That pass emits (a) the exact pass-1 relevant catalog
rows/exhaustion levels and (b) a compact projection of exact breakouts. Pass-1 partials
are merged globally to establish the complete exhaustion-level set. Pass 2 then scans
only the compact exact-breakout projections, not the large PA7 shard SQLite files.
The final catalog must be byte-logically equivalent (candidate IDs/hashes and query
seed sets) to the centralized two-pass relevant catalog.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3
from collections import Counter
from pathlib import Path
from typing import Any,Iterable

from group8_pa7_relevant_catalog import init_catalog,_levels,_match,_insert,finalize as finalize_catalog,KEEP_AT_RANGE_LEVEL,EXACT,FAILED,stable

COLS=('candidate_id','definition_id','symbol','timeframe','direction','source_bar_id','related_source_bar_id','event_time','confirmation_time','availability_time','lower','upper','features_json','candidate_hash')


def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()

def load(path:Path)->dict[str,Any]:return json.loads(path.read_text())
def verify_hash(r:dict[str,Any],label:str)->None:
 q=dict(r);saved=q.pop('report_hash',None)
 if saved!=stable(q):raise RuntimeError(f'{label}:report_hash_mismatch')
def logical_candidates(c:sqlite3.Connection,table:str='pa7_candidate_catalog')->tuple[int,str]:
 h=hashlib.sha256();n=0
 for cid,ch in c.execute(f'SELECT candidate_id,candidate_hash FROM {table} ORDER BY candidate_id'):
  h.update(str(cid).encode());h.update(b'\0');h.update(str(ch).encode());h.update(b'\n');n+=1
 return n,h.hexdigest()
def _auth(group8_root:Path,year:int)->None:
 if year==2024:
  s=load(group8_root/'STATUS.json')
  if s.get('annual_execution_2024_authorized') is not True:raise RuntimeError('2024 OOS is forbidden')

def _init_exact(path:Path)->sqlite3.Connection:
 path.unlink(missing_ok=True);c=sqlite3.connect(path);c.row_factory=sqlite3.Row
 c.executescript('''PRAGMA journal_mode=OFF;PRAGMA synchronous=OFF;
 CREATE TABLE exact_projection(shard_identity TEXT NOT NULL,candidate_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,direction TEXT NOT NULL,source_bar_id INTEGER,related_source_bar_id INTEGER,event_time INTEGER NOT NULL,confirmation_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,lower REAL,upper REAL,features_json TEXT NOT NULL,candidate_hash TEXT NOT NULL);
 CREATE INDEX ix_exact_level ON exact_projection(symbol,timeframe,lower,availability_time,candidate_id);
 CREATE TABLE projection_source(shard_identity TEXT PRIMARY KEY) WITHOUT ROWID;''');return c

def _insert_exact(out:sqlite3.Connection,sid:str,row:sqlite3.Row)->None:
 vals=(sid,)+tuple(row[c] for c in COLS)
 try:out.execute('INSERT INTO exact_projection VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals)
 except sqlite3.IntegrityError as e:raise RuntimeError(f'duplicate exact candidate across projection shards:{row["candidate_id"]}') from e


def project_bundle(*,core_db:Path,shards:list[tuple[str,Path]],pass1_db:Path,exact_db:Path,report_path:Path,group8_root:Path,year:int)->dict[str,Any]:
 _auth(group8_root,year);init_catalog(core_db,pass1_db);p=sqlite3.connect(pass1_db);p.row_factory=sqlite3.Row;e=_init_exact(exact_db)
 try:
  ranges=_levels(p,'target_range_level');rejections={(int(r[0]),str(r[1])) for r in p.execute('SELECT source_bar_id,direction FROM rejection_key')};seen=set();inserted=matched_failed=exact_rows=0
  for sid,db in shards:
   if sid in seen:raise RuntimeError(f'duplicate bundle shard identity:{sid}')
   seen.add(sid);src=sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row
   try:
    if src.execute('PRAGMA quick_check').fetchone()[0]!='ok' or src.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError(f'invalid shard:{sid}')
    sql="SELECT candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_failed_breakout','pa_retest') ORDER BY candidate_id"
    for row in src.execute(sql):
     if row['definition_id']==EXACT:_insert_exact(e,sid,row);exact_rows+=1
     target=_match(ranges,row['symbol'],row['timeframe'],row['lower']);rej=(row['definition_id']==FAILED and row['source_bar_id'] is not None and (int(row['source_bar_id']),str(row['direction'])) in rejections)
     if target or rej:
      if _insert(p,row):inserted+=1
      if rej:
       matched_failed+=1
       if row['lower'] is not None:p.execute('INSERT OR IGNORE INTO exhaustion_level VALUES(?,?,?)',(str(row['symbol']),str(row['timeframe']),float(row['lower'])))
   finally:src.close()
   p.execute('INSERT INTO processed VALUES(1,?)',(sid,));e.execute('INSERT INTO projection_source VALUES(?)',(sid,));p.commit();e.commit()
  pn,ph=logical_candidates(p);en,eh=logical_candidates(e,'exact_projection');rec={'format_version':1,'status':'PASS','year':year,'source_shards':sorted(seen),'source_shard_count':len(seen),'pass1_inserted':inserted,'matched_failed_breakouts':matched_failed,'pass1_candidate_rows':pn,'pass1_logical_candidate_sha256':ph,'exhaustion_level_count':int(p.execute('SELECT COUNT(*) FROM exhaustion_level').fetchone()[0]),'exact_projection_rows':en,'exact_projection_logical_sha256':eh,'pass1_db':{'filename':pass1_db.name,'size_bytes':pass1_db.stat().st_size,'sha256':sha(pass1_db)},'exact_db':{'filename':exact_db.name,'size_bytes':exact_db.stat().st_size,'sha256':sha(exact_db)},'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable(rec);report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec
 finally:p.close();e.close()


def _release_shards(release:dict[str,Any],year:int)->set[str]:
 verify_hash(release,'pa7_release')
 if release.get('status')!='PASS' or int(release.get('year',0))!=year or release.get('complete_once_only_coverage') is not True:raise RuntimeError('PA7 release not complete PASS')
 if release.get('free_only') is not True or release.get('paid_runner_used') or release.get('paid_service_used'):raise RuntimeError('PA7 release not FREE-only')
 return {str(s['shard_id']) for s in release.get('shards',[])}

def _verify_projection_bindings(db_paths:list[Path],reports:list[dict[str,Any]],field:str)->None:
 expected=Counter(str(r[field]['sha256']) for r in reports);actual=Counter(sha(Path(p).resolve()) for p in db_paths)
 if expected!=actual:raise RuntimeError(f'{field} projection database coverage mismatch')

def merge_pass1(*,core_db:Path,pa7_release_report:Path,partial_dbs:list[Path],projection_report_paths:list[Path],output_catalog:Path,report_path:Path,year:int)->dict[str,Any]:
 release=load(pa7_release_report);expected=_release_shards(release,year);reports=[load(p) for p in projection_report_paths]
 for i,r in enumerate(reports):verify_hash(r,f'projection_{i}')
 _verify_projection_bindings(partial_dbs,reports,'pass1_db');init_catalog(core_db,output_catalog);out=sqlite3.connect(output_catalog);out.row_factory=sqlite3.Row;seen=set();inserted=0
 try:
  for db in partial_dbs:
   src=sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row
   try:
    if src.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('partial pass1 quick_check failed')
    for sid, in src.execute('SELECT shard_identity FROM processed WHERE phase=1'):
     sid=str(sid)
     if sid in seen:raise RuntimeError(f'duplicate pass1 projection shard:{sid}')
     seen.add(sid);out.execute('INSERT INTO processed VALUES(1,?)',(sid,))
    for row in src.execute('SELECT * FROM pa7_candidate_catalog ORDER BY candidate_id'):
     if _insert(out,row):inserted+=1
    for row in src.execute('SELECT symbol,timeframe,level FROM exhaustion_level'):out.execute('INSERT OR IGNORE INTO exhaustion_level VALUES(?,?,?)',tuple(row))
   finally:src.close()
   out.commit()
  if seen!=expected:raise RuntimeError(f'pass1 shard coverage mismatch:{len(seen)}!={len(expected)}')
  n,h=logical_candidates(out);rec={'format_version':1,'status':'PASS','year':year,'source_shard_count':len(seen),'candidate_rows':n,'logical_candidate_sha256':h,'exhaustion_level_count':int(out.execute('SELECT COUNT(*) FROM exhaustion_level').fetchone()[0]),'processed_pass1_count':int(out.execute('SELECT COUNT(*) FROM processed WHERE phase=1').fetchone()[0]),'merged_inserted':inserted,'catalog_db':{'filename':output_catalog.name,'size_bytes':output_catalog.stat().st_size,'sha256':sha(output_catalog)},'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable(rec);report_path.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec
 finally:out.close()


def project_pass2(*,seed_catalog:Path,exact_db:Path,projection_report_path:Path,delta_db:Path,report_path:Path,year:int)->dict[str,Any]:
 pr=load(projection_report_path);verify_hash(pr,'projection')
 if sha(exact_db)!=pr['exact_db']['sha256']:raise RuntimeError('exact projection identity mismatch')
 seed=sqlite3.connect(f'file:{seed_catalog.resolve()}?mode=ro&immutable=1',uri=True);levels=_levels(seed,'exhaustion_level');seed.close();src=sqlite3.connect(f'file:{exact_db.resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row;delta_db.unlink(missing_ok=True);out=sqlite3.connect(delta_db);out.row_factory=sqlite3.Row
 try:
  out.executescript('''PRAGMA journal_mode=OFF;PRAGMA synchronous=OFF;CREATE TABLE pa7_candidate_delta(candidate_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,direction TEXT NOT NULL,source_bar_id INTEGER,related_source_bar_id INTEGER,event_time INTEGER NOT NULL,confirmation_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,lower REAL,upper REAL,features_json TEXT NOT NULL,candidate_hash TEXT NOT NULL);CREATE TABLE processed(shard_identity TEXT PRIMARY KEY) WITHOUT ROWID;''');inserted=0
  for row in src.execute('SELECT * FROM exact_projection ORDER BY candidate_id'):
   if _match(levels,row['symbol'],row['timeframe'],row['lower']):
    vals=tuple(row[c] for c in COLS)
    try:out.execute('INSERT INTO pa7_candidate_delta VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals);inserted+=1
    except sqlite3.IntegrityError as e:raise RuntimeError(f'duplicate pass2 delta candidate:{row["candidate_id"]}') from e
  for sid, in src.execute('SELECT shard_identity FROM projection_source ORDER BY shard_identity'):out.execute('INSERT INTO processed VALUES(?)',(str(sid),))
  out.commit();n,h=logical_candidates(out,'pa7_candidate_delta');rec={'format_version':1,'status':'PASS','year':year,'source_shards':sorted(str(r[0]) for r in out.execute('SELECT shard_identity FROM processed')),'source_shard_count':int(out.execute('SELECT COUNT(*) FROM processed').fetchone()[0]),'candidate_rows':n,'logical_candidate_sha256':h,'delta_db':{'filename':delta_db.name,'size_bytes':delta_db.stat().st_size,'sha256':sha(delta_db)},'free_only':True,'paid_runner_used':False,'paid_service_used':False,'oos_2024_accessed':year==2024};rec['report_hash']=stable(rec);report_path.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');return rec
 finally:src.close();out.close()


def merge_pass2(*,seed_catalog:Path,pa7_release_report:Path,delta_dbs:list[Path],delta_report_paths:list[Path],output_catalog:Path,final_report_path:Path,year:int)->dict[str,Any]:
 release=load(pa7_release_report);expected=_release_shards(release,year);reports=[load(p) for p in delta_report_paths]
 for i,r in enumerate(reports):verify_hash(r,f'delta_{i}')
 _verify_projection_bindings(delta_dbs,reports,'delta_db');output_catalog.unlink(missing_ok=True);shutil.copy2(seed_catalog,output_catalog);out=sqlite3.connect(output_catalog);out.row_factory=sqlite3.Row;seen=set()
 try:
  for db in delta_dbs:
   src=sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro&immutable=1',uri=True);src.row_factory=sqlite3.Row
   try:
    for sid, in src.execute('SELECT shard_identity FROM processed'):
     sid=str(sid)
     if sid in seen:raise RuntimeError(f'duplicate pass2 projection shard:{sid}')
     seen.add(sid);out.execute('INSERT INTO processed VALUES(2,?)',(sid,))
    for row in src.execute('SELECT * FROM pa7_candidate_delta ORDER BY candidate_id'):_insert(out,row)
   finally:src.close()
   out.commit()
  if seen!=expected:raise RuntimeError(f'pass2 shard coverage mismatch:{len(seen)}!={len(expected)}')
  p1={str(r[0]) for r in out.execute('SELECT shard_identity FROM processed WHERE phase=1')};p2={str(r[0]) for r in out.execute('SELECT shard_identity FROM processed WHERE phase=2')}
  if p1!=expected or p2!=expected:raise RuntimeError('final relevant catalog processed coverage mismatch')
 finally:out.close()
 return finalize_catalog(output_catalog,final_report_path)


def _pairs(values:Iterable[str])->list[tuple[str,Path]]:
 out=[]
 for v in values:
  sid,sep,path=v.partition('=')
  if not sep or not sid:raise ValueError(v)
  out.append((sid,Path(path).resolve()))
 return out

def main()->int:
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('project-bundle');a.add_argument('--core-db',type=Path,required=True);a.add_argument('--shard',action='append',required=True,help='SHARD_ID=/path/db');a.add_argument('--pass1-db',type=Path,required=True);a.add_argument('--exact-db',type=Path,required=True);a.add_argument('--report',type=Path,required=True);a.add_argument('--group8-root',type=Path,required=True);a.add_argument('--year',type=int,required=True)
 b=s.add_parser('merge-pass1');b.add_argument('--core-db',type=Path,required=True);b.add_argument('--pa7-release-report',type=Path,required=True);b.add_argument('--partial-db',type=Path,action='append',required=True);b.add_argument('--projection-report',type=Path,action='append',required=True);b.add_argument('--catalog',type=Path,required=True);b.add_argument('--report',type=Path,required=True);b.add_argument('--year',type=int,required=True)
 c=s.add_parser('project-pass2');c.add_argument('--seed-catalog',type=Path,required=True);c.add_argument('--exact-db',type=Path,required=True);c.add_argument('--projection-report',type=Path,required=True);c.add_argument('--delta-db',type=Path,required=True);c.add_argument('--report',type=Path,required=True);c.add_argument('--year',type=int,required=True)
 d=s.add_parser('merge-pass2');d.add_argument('--seed-catalog',type=Path,required=True);d.add_argument('--pa7-release-report',type=Path,required=True);d.add_argument('--delta-db',type=Path,action='append',required=True);d.add_argument('--delta-report',type=Path,action='append',required=True);d.add_argument('--catalog',type=Path,required=True);d.add_argument('--report',type=Path,required=True);d.add_argument('--year',type=int,required=True)
 x=p.parse_args()
 if x.cmd=='project-bundle':r=project_bundle(core_db=x.core_db,shards=_pairs(x.shard),pass1_db=x.pass1_db,exact_db=x.exact_db,report_path=x.report,group8_root=x.group8_root,year=x.year)
 elif x.cmd=='merge-pass1':r=merge_pass1(core_db=x.core_db,pa7_release_report=x.pa7_release_report,partial_dbs=x.partial_db,projection_report_paths=x.projection_report,catalog=x.catalog if False else x.catalog,output_catalog=x.catalog,report_path=x.report,year=x.year)
 elif x.cmd=='project-pass2':r=project_pass2(seed_catalog=x.seed_catalog,exact_db=x.exact_db,projection_report_path=x.projection_report,delta_db=x.delta_db,report_path=x.report,year=x.year)
 else:r=merge_pass2(seed_catalog=x.seed_catalog,pa7_release_report=x.pa7_release_report,delta_dbs=x.delta_db,delta_report_paths=x.delta_report,output_catalog=x.catalog,final_report_path=x.report,year=x.year)
 print(json.dumps({'status':r['status'],'report_hash':r.get('report_hash'),'candidate_rows':r.get('candidate_rows')},indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
