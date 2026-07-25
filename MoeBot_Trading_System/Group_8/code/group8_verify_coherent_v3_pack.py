#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sqlite3,subprocess,urllib.request
from pathlib import Path

def shaf(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
def rows(c,sql):
 cur=c.execute(sql);names=[x[0] for x in cur.description or []];return [dict(zip(names,r)) for r in cur.fetchall()]
def schema(c):
 tables={}
 for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
  name=r[0];q=name.replace("'","''");tables[name]={'sql':r[1],'columns':rows(c,f"PRAGMA table_info('{q}')"),'foreign_keys':rows(c,f"PRAGMA foreign_key_list('{q}')"),'indexes':rows(c,f"PRAGMA index_list('{q}')"),'row_count':c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]}
 return tables
def categories(c,tables):
 names={'timeframe','direction','role','status','state','event_type','zone_class','zone_label','definition_id','source_group','relation_type','lifecycle_state','freshness','fill_state','directional_validity','variant_type','classification','pool_class','side','layer','active_bias','sequence_bias','outcome','break_kind'};out={}
 for table,rec in tables.items():
  cols=[x['name'] for x in rec['columns']]
  for col in sorted(set(cols)&names):
   vals=c.execute(f'SELECT "{col}",COUNT(*) FROM "{table}" GROUP BY "{col}" ORDER BY "{col}"').fetchall()
   if len(vals)<=500:out[f'{table}.{col}']=[{'value':v,'count':n} for v,n in vals]
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();m=json.loads(a.manifest.read_text());work=a.work_dir.resolve();work.mkdir(parents=True,exist_ok=True);results={};fails=[]
 if m.get('status')!='PASS_PACKAGED':fails.append('manifest_not_pass')
 for g,rec in sorted(m['packages'].items()):
  chunks=[]
  for part in rec['parts']:
   path=work/part['filename']
   with urllib.request.urlopen(part['url'],timeout=300) as response,path.open('wb') as out:
    while True:
     b=response.read(8*1024*1024)
     if not b:break
     out.write(b)
   if path.stat().st_size!=part['size_bytes'] or shaf(path)!=part['sha256']:fails.append(f'{g}:part:{part["filename"]}')
   chunks.append(path)
  z=work/rec['compressed_filename']
  with z.open('wb') as out:
   for x in chunks:
    with x.open('rb') as src:
     while True:
      b=src.read(16*1024*1024)
      if not b:break
      out.write(b)
  if z.stat().st_size!=rec['compressed_size_bytes'] or shaf(z)!=rec['compressed_sha256']:fails.append(f'{g}:compressed_identity')
  db=work/rec['database_filename'];subprocess.run(['zstd','-q','-d','--long=31','-f',str(z),'-o',str(db)],check=True)
  db_sha=shaf(db)
  if db.stat().st_size!=rec['database_size_bytes'] or db_sha!=rec['database_sha256']:fails.append(f'{g}:database_identity')
  c=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True);q=c.execute('PRAGMA quick_check').fetchone()[0];i=c.execute('PRAGMA integrity_check').fetchone()[0];fk=len(c.execute('PRAGMA foreign_key_check').fetchall());s=schema(c);cats=categories(c,s);c.close()
  if q!='ok' or i!='ok' or fk:fails.append(f'{g}:sqlite')
  results[g]={'database':{'filename':db.name,'size_bytes':db.stat().st_size,'sha256':db_sha},'sqlite':{'quick_check':q,'integrity_check':i,'foreign_key_errors':fk},'schema':{'table_count':len(s),'tables':s},'categories':cats}
  for x in chunks:x.unlink(missing_ok=True)
  z.unlink(missing_ok=True);db.unlink(missing_ok=True)
 report={'format_version':2,'status':'PASS' if not fails else 'FAIL','year':m['year'],'lineage':m['lineage'],'source_manifest_hash':m['manifest_hash'],'disk_safe_sequential_verification':True,'groups':results,'failures':fails};report['report_hash']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'year':report['year'],'failures':fails,'report_hash':report['report_hash']},indent=2));return 0 if not fails else 1
if __name__=='__main__':raise SystemExit(main())
