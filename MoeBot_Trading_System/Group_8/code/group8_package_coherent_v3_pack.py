#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3,subprocess
from pathlib import Path
GROUPS=('group2','group3','group4','group5','group6','group7')
def shaf(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
def cj(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=(2023,2024),required=True);p.add_argument('--pipeline-report',type=Path,required=True);p.add_argument('--group7-report',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--repository',required=True);p.add_argument('--tag',required=True);p.add_argument('--part-size',type=int,default=1800*1024*1024)
 for g in GROUPS:p.add_argument(f'--{g}',type=Path,required=True)
 a=p.parse_args();pipe=json.loads(a.pipeline_report.read_text());g7r=json.loads(a.group7_report.read_text());out=a.output_dir.resolve();shutil.rmtree(out,ignore_errors=True);out.mkdir(parents=True)
 if g7r.get('status')!='PASS' or int(g7r.get('year',-1))!=a.year:raise RuntimeError('Group7 annual report not PASS')
 packages={}
 for g in GROUPS:
  src=getattr(a,g).resolve()
  if not src.is_file():raise FileNotFoundError(src)
  con=sqlite3.connect(f'file:{src}?mode=ro&immutable=1',uri=True);q=con.execute('PRAGMA quick_check').fetchone()[0];i=con.execute('PRAGMA integrity_check').fetchone()[0];fk=len(con.execute('PRAGMA foreign_key_check').fetchall());con.close()
  if q!='ok' or i!='ok' or fk:raise RuntimeError(f'{g} sqlite integrity')
  target_name=f'{src.stem}_corrected_v3_group8_v1.sqlite' if 'corrected_v3_group8_v1' not in src.name else src.name
  compressed=out/f'{target_name}.zst';subprocess.run(['zstd','-q','-19','--long=31','-T0','-f',str(src),'-o',str(compressed)],check=True)
  csize=compressed.stat().st_size;csha=shaf(compressed);parts=[]
  with compressed.open('rb') as fh:
   n=0
   while True:
    data=fh.read(a.part_size)
    if not data:break
    part=out/f'{compressed.name}.part-{n:03d}';part.write_bytes(data);parts.append({'filename':part.name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'url':f'https://github.com/{a.repository}/releases/download/{a.tag}/{part.name}'});n+=1
  compressed.unlink();packages[g]={'source_filename':src.name,'database_filename':target_name,'database_size_bytes':src.stat().st_size,'database_sha256':shaf(src),'compressed_filename':f'{target_name}.zst','compressed_size_bytes':csize,'compressed_sha256':csha,'compression':'zstd -19 --long=31','parts':parts,'sqlite':{'quick_check':q,'integrity_check':i,'foreign_key_errors':fk}}
 report={'format_version':1,'status':'PASS_PACKAGED','purpose':'Group8 coherent corrected-runtime-v3 annual dependencies Groups2-7','year':a.year,'repository':a.repository,'release_tag':a.tag,'lineage':'dukascopy_rebuild_v1_corrected_runtime_v3_group8_v1','runtime_engines':pipe['engines'],'source_sha256':pipe['source_sha256'],'group7_source_closure_tag':g7r['source_group7_closure_tag'],'group7_source_closure_commit_sha':g7r['source_group7_closure_commit_sha'],'group7_config_id':g7r['summary']['config_id'],'packages':packages}
 report['manifest_hash']=hashlib.sha256(cj(report).encode()).hexdigest();m=out/f'MoeBot_Group8_Coherent_Upstream_G2-G7_{a.year}_manifest.json';m.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'year':a.year,'manifest_hash':report['manifest_hash'],'parts':{g:len(v['parts']) for g,v in packages.items()}},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
