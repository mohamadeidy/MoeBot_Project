#!/usr/bin/env python3
"""Full wall-clock stage-4 benchmark/official job with SHA-bound verification.

BENCHMARK_ONLY restores immutable checkpoint 2 from the official source tag, runs
one isolated partition, and publishes diagnostic assets only to a head-bound
benchmark tag. It cannot alter official partition assets or checkpoint 3.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3,subprocess,time
from pathlib import Path
from typing import Any
from group8_context_rejection_fastpath import IndexedContextRejectionEngine,STAGE4_PARTITION_COUNT
from group8_segmented_annual_core import run_segment
from moebot_group8_engine_v0_8_0 import stable_hash

def command(*args:str,capture:bool=False)->str:
 r=subprocess.run(args,check=True,text=True,capture_output=capture);return r.stdout.strip() if capture else ""

def sha256_file(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(16*1024*1024),b''):h.update(c)
 return h.hexdigest()

def integrity(path:Path)->None:
 con=sqlite3.connect(path)
 try:v=str(con.execute('PRAGMA integrity_check').fetchone()[0])
 finally:con.close()
 if v!='ok':raise RuntimeError(f'SQLite integrity failure:{path.name}:{v}')

def verify_self_hash(m:dict[str,Any])->str:
 key='report_hash' if 'report_hash' in m else 'manifest_hash';saved=str(m[key]);q=dict(m);q.pop(key)
 if stable_hash(q)!=saved:raise RuntimeError('manifest self-hash mismatch')
 return saved

def staging_restore(root:Path,work:Path)->tuple[Path,float]:
 t=time.monotonic();release=json.loads((root/'reports/48_FULL_2023_STAGING_RELEASE.json').read_text());d=work/'staging_parts';d.mkdir(parents=True,exist_ok=True);parts=[]
 for x in release['parts']:
  p=d/x['filename'];command('curl','-fL','--retry','6','--retry-delay','2',x['url'],'-o',str(p))
  if p.stat().st_size!=x['size_bytes'] or sha256_file(p)!=x['sha256']:raise RuntimeError(f'staging part verification failure:{p.name}')
  parts.append(p)
 z=work/'staging.sqlite.zst'
 with z.open('wb') as out:
  for p in parts:
   with p.open('rb') as src:shutil.copyfileobj(src,out)
 if z.stat().st_size!=release['compressed_size_bytes'] or sha256_file(z)!=release['compressed_sha256']:raise RuntimeError('staging archive verification failure')
 db=work/'staging.sqlite';command('zstd','-q','-d','-f',str(z),'-o',str(db));integrity(db);return db,time.monotonic()-t

def prefix(partition:int)->str:return 'checkpoint2' if partition<0 else f'stage4p{partition:02d}'

def parent_restore(repo:str,source_tag:str,parent_partition:int,work:Path)->tuple[Path,dict[str,Any],str,float]:
 t=time.monotonic();name=prefix(parent_partition);d=work/f'parent-{name}';d.mkdir(parents=True,exist_ok=True)
 command('gh','release','download',source_tag,'--repo',repo,'--pattern',f'{name}.*','--dir',str(d),'--clobber')
 m=json.loads((d/f'{name}.json').read_text());mh=verify_self_hash(m);parts=sorted(d.glob(f'{name}.sqlite.zst.part-*'))
 if [p.name for p in parts]!=[x['filename'] for x in m['parts']]:raise RuntimeError('parent filename coverage mismatch')
 for p,x in zip(parts,m['parts']):
  if p.stat().st_size!=x['size_bytes'] or sha256_file(p)!=x['sha256']:raise RuntimeError(f'parent part verification failure:{p.name}')
 z=d/f'{name}.sqlite.zst'
 with z.open('wb') as out:
  for p in parts:
   with p.open('rb') as src:shutil.copyfileobj(src,out)
 if z.stat().st_size!=m['compressed_size_bytes'] or sha256_file(z)!=m['compressed_sha256']:raise RuntimeError('parent compressed verification failure')
 db=d/f'{name}.sqlite';command('zstd','-q','-d','-f',str(z),'-o',str(db))
 if db.stat().st_size!=m['raw_size_bytes'] or sha256_file(db)!=m['raw_sha256']:raise RuntimeError('parent raw verification failure')
 integrity(db)
 if parent_partition>=0:
  plan=IndexedContextRejectionEngine.stage4_partition_plan()
  if m['partition_index']!=parent_partition or m['plan_hash']!=plan['plan_hash'] or m.get('checkpoint_3_published') is not False:raise RuntimeError('parent official partition contract failure')
 return db,m,mh,time.monotonic()-t

def ensure_benchmark_release(repo:str,tag:str,head:str)->None:
 if not tag.startswith('moebot-group8-stage4-benchmark-') or head[:12] not in tag:raise RuntimeError('benchmark output tag is not exact-head isolated')
 r=subprocess.run(['gh','release','view',tag,'--repo',repo],text=True,capture_output=True)
 if r.returncode!=0:
  c=subprocess.run(['gh','release','create',tag,'--repo',repo,'--title',f'Group8 stage4 benchmark {head[:12]}','--notes','BENCHMARK_ONLY diagnostic assets; not official Annual 2023 evidence.'],text=True,capture_output=True)
  if c.returncode!=0:
   r2=subprocess.run(['gh','release','view',tag,'--repo',repo],text=True,capture_output=True)
   if r2.returncode!=0:raise RuntimeError(f'cannot create benchmark release:{c.stderr}')

def publish_and_verify(repo:str,tag:str,asset_prefix:str,db:Path,payload:dict[str,Any],work:Path)->dict[str,float]:
 z=work/f'{asset_prefix}.sqlite.zst';t=time.monotonic();command('zstd','-q','-3','-T0','-f',str(db),'-o',str(z));command('split','-b','1750000000','-d','-a','3',str(z),str(work/f'{asset_prefix}.sqlite.zst.part-'));compression=time.monotonic()-t
 t=time.monotonic();parts=[{'filename':p.name,'size_bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in sorted(work.glob(f'{asset_prefix}.sqlite.zst.part-*'))];payload.update({'raw_size_bytes':db.stat().st_size,'raw_sha256':sha256_file(db),'compressed_size_bytes':z.stat().st_size,'compressed_sha256':sha256_file(z),'parts':parts,'compression_seconds':compression});hash_seconds=time.monotonic()-t;payload['hash_seconds']=hash_seconds;payload['manifest_hash']=stable_hash(payload);mp=work/f'{asset_prefix}.json';mp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
 t=time.monotonic();command('gh','release','upload',tag,*[str(work/x['filename']) for x in parts],str(mp),'--repo',repo,'--clobber');upload=time.monotonic()-t
 d=work/f'verify-{asset_prefix}';d.mkdir(parents=True,exist_ok=True);t=time.monotonic();command('gh','release','download',tag,'--repo',repo,'--pattern',f'{asset_prefix}.*','--dir',str(d),'--clobber');dm=json.loads((d/f'{asset_prefix}.json').read_text());verify_self_hash(dm);dparts=sorted(d.glob(f'{asset_prefix}.sqlite.zst.part-*'))
 if [p.name for p in dparts]!=[x['filename'] for x in dm['parts']]:raise RuntimeError('public redownload filename mismatch')
 for p,x in zip(dparts,dm['parts']):
  if p.stat().st_size!=x['size_bytes'] or sha256_file(p)!=x['sha256']:raise RuntimeError('public redownload part mismatch')
 redownload=time.monotonic()-t;return {'compression_seconds':compression,'hash_seconds':hash_seconds,'upload_seconds':upload,'redownload_verify_seconds':redownload}

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=('benchmark','official'),required=True);p.add_argument('--repo',required=True);p.add_argument('--source-tag',required=True);p.add_argument('--output-tag',required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--partition',type=int,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--job-start-epoch',type=float,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 if not 0<=a.partition<STAGE4_PARTITION_COUNT:raise ValueError('invalid partition')
 status=json.loads((a.artifacts_root/'STATUS.json').read_text())
 if status['annual_execution_2024_authorized'] is not False:raise RuntimeError('2024 lock is not confirmed')
 if status['free_only_policy']['paid_runner_allowed'] or status['free_only_policy']['paid_service_allowed']:raise RuntimeError('FREE-only policy failure')
 head=command('git','rev-parse','HEAD',capture=True)
 if a.mode=='benchmark':
  if a.output_tag==a.source_tag:raise RuntimeError('BENCHMARK_ONLY cannot write official source tag')
  ensure_benchmark_release(a.repo,a.output_tag,head)
 else:
  if a.output_tag!=a.source_tag:raise RuntimeError('official chain must remain on canonical release tag')
 a.work_dir.mkdir(parents=True,exist_ok=True);staging,srestore=staging_restore(a.artifacts_root,a.work_dir);parent_partition=-1 if a.mode=='benchmark' or a.partition==0 else a.partition-1;parent,parent_manifest,parent_hash,prestore=parent_restore(a.repo,a.source_tag,parent_partition,a.work_dir);core=a.work_dir/'core.sqlite';shutil.copy2(parent,core)
 plan=IndexedContextRejectionEngine.stage4_partition_plan();range_id=f"{plan['plan_id']}:range-{a.partition:02d}-{a.partition:02d}";t=time.monotonic();result=run_segment(staging_db=staging,output_db=core,artifacts_root=a.artifacts_root,year=2023,symbol='XAUUSD_',start=4,end=4,stage4_partition=a.partition,benchmark_only=a.mode=='benchmark');execution=time.monotonic()-t;integrity(core)
 if a.mode=='benchmark' and (result.get('benchmark_only') is not True or result.get('official_chain_progress') is not False or result.get('official_receipt_published') is not False):raise RuntimeError('BENCHMARK_ONLY role contract failure')
 asset=f'stage4bench{a.partition:02d}-{head[:12]}' if a.mode=='benchmark' else prefix(a.partition);payload={'status':'PASS','role':'STAGE4_FULL_JOB_BENCHMARK_ONLY' if a.mode=='benchmark' else 'STAGE4_PARTITION_CHECKPOINT','mode':a.mode,'year':2023,'github_head_sha':head,'partition_index':a.partition,'range_identity':range_id,'first_partition':a.partition,'last_partition':a.partition,'plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'parent_manifest_hash':parent_hash,'source_tag':a.source_tag,'output_tag':a.output_tag,'receipt_preview':result['receipt'],'official_receipt_published':False if a.mode=='benchmark' else True,'restore_seconds':srestore+prestore,'staging_restore_seconds':srestore,'parent_restore_seconds':prestore,'execution_seconds':execution,'checkpoint_3_published':False,'free_only':True,'oos_2024_accessed':False}
 timings=publish_and_verify(a.repo,a.output_tag,asset,core,payload,a.work_dir);wall=time.time()-a.job_start_epoch;payload.update(timings);payload['full_job_wall_seconds']=wall;payload['safety_limit_seconds']=14400;payload['runtime_safety_pass']=wall<=14400;payload['manifest_hash']=stable_hash({k:v for k,v in payload.items() if k!='manifest_hash'});a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
 if not payload['runtime_safety_pass']:raise RuntimeError(f'full job safety failure:{wall}')
 print(json.dumps(payload,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
