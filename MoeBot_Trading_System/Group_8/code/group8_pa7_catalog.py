#!/usr/bin/env python3
"""Build a compact query catalog from verified PA7 domain shards.

The catalog is execution infrastructure, not a domain artifact. It retains immutable
candidate IDs/hashes and only columns required by PA7-dependent Group8 logic.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path
from typing import Iterable,Any

CHAIN={'pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer','pa_failed_breakout','pa_retest'}

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def build_catalog(shards:Iterable[Path],output:Path)->dict[str,Any]:
    output.unlink(missing_ok=True);out=sqlite3.connect(output)
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
    ''')
    seen_shards=[];dupes=[];inserted=0
    sql='''INSERT INTO pa7_candidate_catalog(candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
    for path in sorted(Path(p) for p in shards):
        con=sqlite3.connect(path);con.row_factory=sqlite3.Row
        try:
            qc=con.execute('PRAGMA quick_check').fetchone()[0];ic=con.execute('PRAGMA integrity_check').fetchone()[0]
            if qc!='ok' or ic!='ok':raise RuntimeError(f'invalid shard:{path}:{qc}:{ic}')
            rows=con.execute("SELECT candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash FROM price_action_pattern_candidate ORDER BY candidate_id")
            for r in rows:
                if r['definition_id'] not in CHAIN:raise RuntimeError(f'non-PA7 candidate in shard:{r["definition_id"]}')
                try:out.execute(sql,tuple(r))
                except sqlite3.IntegrityError:
                    existing=out.execute('SELECT candidate_hash FROM pa7_candidate_catalog WHERE candidate_id=?',(r['candidate_id'],)).fetchone()
                    dupes.append(str(r['candidate_id']))
                    if existing is None or str(existing[0])!=str(r['candidate_hash']):raise RuntimeError(f'conflicting duplicate PA7 candidate:{r["candidate_id"]}')
                    continue
                inserted+=1
            seen_shards.append({'filename':path.name,'candidate_rows':con.execute('SELECT COUNT(*) FROM price_action_pattern_candidate').fetchone()[0]})
        finally:con.close()
        out.commit()
    if dupes:raise RuntimeError(f'duplicate PA7 domain candidate IDs across shards:{len(dupes)}')
    h=hashlib.sha256();counts={r[0]:r[1] for r in out.execute('SELECT definition_id,COUNT(*) FROM pa7_candidate_catalog GROUP BY definition_id ORDER BY definition_id')}
    for r in out.execute('SELECT candidate_id,candidate_hash FROM pa7_candidate_catalog ORDER BY candidate_id'):
        h.update(str(r[0]).encode());h.update(b'\0');h.update(str(r[1]).encode());h.update(b'\n')
    out.commit();qc=out.execute('PRAGMA quick_check').fetchone()[0];ic=out.execute('PRAGMA integrity_check').fetchone()[0];out.close()
    report={'format_version':1,'status':'PASS','artifact_kind':'PA7_QUERY_CATALOG','domain_artifact':False,'candidate_rows':inserted,'definition_counts':counts,'logical_candidate_sha256':h.hexdigest(),'source_shards':seen_shards,'quick_check':qc,'integrity_check':ic};report['report_hash']=stable(report);return report

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('shards',nargs='+',type=Path);a=p.parse_args();r=build_catalog(a.shards,a.output);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
