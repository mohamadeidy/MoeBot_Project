#!/usr/bin/env python3
"""Build a compact SQLite catalog from immutable shard release manifests.

The catalog indexes metadata only. It never opens shard SQLite payloads and therefore
lets downstream Groups 9-15 select relevant archives without copying full history.
"""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from typing import Any

def _pick(d:dict[str,Any],*names,default=None):
    for n in names:
        if n in d:return d[n]
    return default

def init(con:sqlite3.Connection)->None:
    con.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS release_catalog(
      release_key TEXT PRIMARY KEY,
      source_path TEXT NOT NULL,
      group_no INTEGER,
      stage INTEGER,
      year INTEGER,
      status TEXT,
      release_hash TEXT,
      plan_hash TEXT,
      logical_fingerprint TEXT
    );
    CREATE TABLE IF NOT EXISTS shard_catalog(
      release_key TEXT NOT NULL,
      shard_key TEXT NOT NULL,
      ordinal_no INTEGER,
      family TEXT,
      year INTEGER,
      symbol TEXT,
      timeframe TEXT,
      root_month TEXT,
      bucket_count INTEGER,
      bucket_index INTEGER,
      archive_path TEXT,
      raw_sha256 TEXT,
      compressed_sha256 TEXT,
      compressed_size_bytes INTEGER,
      manifest_hash TEXT,
      PRIMARY KEY(release_key,shard_key)
    );
    CREATE INDEX IF NOT EXISTS ix_shard_scope
      ON shard_catalog(year,family,timeframe,root_month,bucket_index);
    CREATE TABLE IF NOT EXISTS shard_table_catalog(
      release_key TEXT NOT NULL,
      shard_key TEXT NOT NULL,
      table_name TEXT NOT NULL,
      row_count INTEGER NOT NULL,
      logical_sha256 TEXT,
      PRIMARY KEY(release_key,shard_key,table_name)
    );
    CREATE INDEX IF NOT EXISTS ix_shard_table_name ON shard_table_catalog(table_name,row_count);
    """)

def ingest(con:sqlite3.Connection,path:Path,group_no:int|None)->None:
    r=json.loads(path.read_text())
    release_hash=str(_pick(r,"release_hash","manifest_hash","report_hash",default=""))
    key=f"{path.name}:{release_hash[:16]}"
    con.execute("""INSERT OR REPLACE INTO release_catalog
      (release_key,source_path,group_no,stage,year,status,release_hash,plan_hash,logical_fingerprint)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (key,str(path),group_no,_pick(r,"stage"),_pick(r,"year"),_pick(r,"status"),release_hash,
       _pick(r,"plan_hash","preflight_plan_hash"),_pick(r,"global_logical_sha256","logical_fingerprint")))
    shards=list(r.get("shards") or [])
    for i,s in enumerate(shards):
        spec=s.get("spec") or s
        shard_key=str(_pick(s,"shard_id",default=f"{i:06d}"))
        con.execute("""INSERT OR REPLACE INTO shard_catalog
          (release_key,shard_key,ordinal_no,family,year,symbol,timeframe,root_month,bucket_count,bucket_index,
           archive_path,raw_sha256,compressed_sha256,compressed_size_bytes,manifest_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (key,shard_key,int(_pick(s,"ordinal",default=i)),_pick(spec,"family"),_pick(spec,"year",default=r.get("year")),
           _pick(spec,"symbol",default=r.get("symbol")),_pick(spec,"timeframe"),_pick(spec,"root_month","causal_root_window"),
           _pick(spec,"bucket_count"),_pick(spec,"bucket_index"),_pick(s,"archive_path","database"),
           _pick(s,"raw_sha256","sha256"),_pick(s,"compressed_sha256"),_pick(s,"compressed_size_bytes"),
           _pick(s,"manifest_hash")))
        counts=s.get("table_row_counts") or {}
        hashes=s.get("table_logical_sha256") or {}
        for table,n in counts.items():
            con.execute("""INSERT OR REPLACE INTO shard_table_catalog
              (release_key,shard_key,table_name,row_count,logical_sha256) VALUES(?,?,?,?,?)""",
              (key,shard_key,str(table),int(n),hashes.get(table)))
    con.commit()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--release",type=Path,action="append",required=True)
    p.add_argument("--group",type=int)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(a.output)
    try:
        init(con)
        for path in a.release:ingest(con,path.resolve(),a.group)
        summary={
          "releases":con.execute("SELECT COUNT(*) FROM release_catalog").fetchone()[0],
          "shards":con.execute("SELECT COUNT(*) FROM shard_catalog").fetchone()[0],
          "table_entries":con.execute("SELECT COUNT(*) FROM shard_table_catalog").fetchone()[0],
          "rows_described":con.execute("SELECT COALESCE(SUM(row_count),0) FROM shard_table_catalog").fetchone()[0],
        }
    finally:con.close()
    print(json.dumps({"status":"PASS","catalog":str(a.output.resolve()),**summary},indent=2,sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
