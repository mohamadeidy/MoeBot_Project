#!/usr/bin/env python3
"""Create and merge exact sorted (primary_id,row_hash) sidecars for Group 8 shards.

This implements the frozen storage-contract fingerprint stream without a global ID
ledger. Shard workers emit sorted per-hex-prefix pair files; prefix merge workers
perform an exact k-way merge and reject duplicate domain IDs; the final table SHA is
SHA256 over the canonical prefix streams in 0..f order, exactly matching the legacy
streaming validator's sorted primary-ID hash.
"""
from __future__ import annotations

import argparse,hashlib,heapq,json,sqlite3
from pathlib import Path
from typing import Any,Iterable,TextIO

TABLES={
 'candidate':('price_action_pattern_candidate','candidate_id','candidate_hash'),
 'state':('price_action_pattern_state','state_event_id','state_hash'),
}
HEX='0123456789abcdef'


def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
def prefix(row_id:str)->str:
 tail=str(row_id).rsplit('_',1)[-1]
 if not tail or tail[0].lower() not in HEX:raise RuntimeError(f'non-hex deterministic ID:{row_id}')
 return tail[0].lower()


def _local_group8_ref_errors(c:sqlite3.Connection)->int:
 """Require only PA7 chain-internal candidate references to resolve in this shard.

 Breakout candidates can legitimately reference Group8 bounded-range candidates that
 live in the Annual Core rather than the PA7 shard. Failed-breakout and retest rows,
 however, are generated from a breakout candidate in the same physical PA7 shard and
 their Group8 candidate reference must therefore resolve locally. All other Group8
 references are resolved by the final cross-shard/core audit.
 """
 if 'price_action_pattern_candidate' not in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:return 0
 return int(c.execute("""SELECT COUNT(*) FROM price_action_pattern_candidate c,json_each(c.upstream_refs_json) j
 WHERE c.definition_id IN ('pa_failed_breakout','pa_retest')
 AND lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
 AND COALESCE(json_extract(j.value,'$.source_type'),'')='price_action_pattern_candidate'
 AND NOT EXISTS(SELECT 1 FROM price_action_pattern_candidate p WHERE p.candidate_id=CAST(json_extract(j.value,'$.source_id') AS TEXT))""").fetchone()[0])


def create_sidecars(databases:Iterable[Path],outdir:Path)->dict[str,Any]:
 paths=[Path(x).resolve() for x in databases]
 outdir.mkdir(parents=True,exist_ok=True);handles:dict[tuple[str,str],TextIO]={};counts={(t,p):0 for t in TABLES for p in HEX};db_count=0;local_ref_errors=0;sources=[]
 try:
  for t in TABLES:
   for p in HEX:handles[(t,p)]=(outdir/f'{t}_{p}.pairs').open('a',encoding='utf-8',newline='')
  for db in paths:
   sources.append({'filename':db.name,'size_bytes':db.stat().st_size,'sha256':sha(db)})
   c=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True)
   try:
    if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError(f'invalid sqlite:{db}')
    if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError(f'foreign-key error:{db}')
    local_ref_errors+=_local_group8_ref_errors(c)
    existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for key,(table,idc,hc) in TABLES.items():
     if table not in existing:continue
     for rid,rh in c.execute(f'SELECT "{idc}","{hc}" FROM "{table}"'):
      p=prefix(str(rid));handles[(key,p)].write(f'{rid}\t{rh}\n');counts[(key,p)]+=1
    db_count+=1
   finally:c.close()
 finally:
  for f in handles.values():f.close()
 if local_ref_errors:raise RuntimeError(f'unresolved local PA7 chain refs:{local_ref_errors}')
 files={};total=0
 for key in TABLES:
  for p in HEX:
   path=outdir/f'{key}_{p}.pairs';lines=path.read_text().splitlines();lines.sort(key=lambda s:s.split('\t',1)[0]);prev=None
   for line in lines:
    rid=line.split('\t',1)[0]
    if rid==prev:raise RuntimeError(f'duplicate domain ID within sidecar set:{key}:{rid}')
    prev=rid
   path.write_text(('\n'.join(lines)+'\n') if lines else '')
   files[f'{key}_{p}']={'filename':path.name,'rows':len(lines),'size_bytes':path.stat().st_size,'sha256':sha(path)};total+=len(lines)
 rec={'format_version':2,'status':'PASS','database_count':db_count,'source_databases':sources,'total_pair_rows':total,'local_group8_reference_errors':0,'files':files,'free_only':True,'paid_runner_used':False,'paid_service_used':False};rec['report_hash']=stable(rec);return rec


def _read_line(f:TextIO):
 s=f.readline()
 if not s:return None
 rid,rh=s.rstrip('\n').split('\t',1);return rid,rh


def merge_prefix(inputs:Iterable[Path],output:Path)->dict[str,Any]:
 paths=[Path(p).resolve() for p in inputs];input_meta=[{'filename':p.name,'size_bytes':p.stat().st_size,'sha256':sha(p)} for p in paths];streams=[p.open('r',encoding='utf-8') for p in paths];heap=[]
 try:
  for i,f in enumerate(streams):
   item=_read_line(f)
   if item:heapq.heappush(heap,(item[0],item[1],i))
  output.parent.mkdir(parents=True,exist_ok=True);count=0;prev=None;h=hashlib.sha256()
  with output.open('wb') as out:
   while heap:
    rid,rh,i=heapq.heappop(heap)
    if rid==prev:raise RuntimeError(f'duplicate domain ID across sidecars:{rid}')
    prev=rid;blob=rid.encode()+b'\0'+rh.encode()+b'\n';out.write(blob);h.update(blob);count+=1
    item=_read_line(streams[i])
    if item:heapq.heappush(heap,(item[0],item[1],i))
  return {'format_version':2,'status':'PASS','inputs':input_meta,'input_count':len(paths),'row_count':count,'canonical_stream_sha256':h.hexdigest(),'file_sha256':sha(output),'file_size_bytes':output.stat().st_size}
 finally:
  for f in streams:f.close()


def table_hash(prefix_streams:Iterable[Path])->dict[str,Any]:
 paths=[Path(p) for p in prefix_streams];h=hashlib.sha256();size=0
 for p in paths:
  with p.open('rb') as f:
   for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b);size+=len(b)
 return {'status':'PASS','prefix_count':len(paths),'canonical_bytes':size,'logical_sha256':h.hexdigest()}


def main()->int:
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('create');a.add_argument('--outdir',type=Path,required=True);a.add_argument('--report',type=Path,required=True);a.add_argument('databases',nargs='+',type=Path)
 b=s.add_parser('merge-prefix');b.add_argument('--output',type=Path,required=True);b.add_argument('--report',type=Path,required=True);b.add_argument('inputs',nargs='+',type=Path)
 c=s.add_parser('table-hash');c.add_argument('--report',type=Path,required=True);c.add_argument('prefix_streams',nargs='+',type=Path)
 x=p.parse_args()
 if x.cmd=='create':r=create_sidecars(x.databases,x.outdir)
 elif x.cmd=='merge-prefix':r=merge_prefix(x.inputs,x.output)
 else:r=table_hash(x.prefix_streams)
 x.report.parent.mkdir(parents=True,exist_ok=True);q=dict(r);q['report_hash']=stable(q);x.report.write_text(json.dumps(q,indent=2,sort_keys=True)+'\n');print(json.dumps(q,indent=2,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
