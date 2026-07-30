#!/usr/bin/env python3
"""Full wall-clock stage-4 BENCHMARK_ONLY/official job with SHA verification."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3,subprocess,time
from pathlib import Path
from typing import Any
from group8_context_rejection_fastpath import IndexedContextRejectionEngine,STAGE4_PARTITION_COUNT
from group8_segmented_annual_core import run_segment
from moebot_group8_engine_v0_8_0 import stable_hash

def cmd(*a:str,capture:bool=False)->str:
 r=subprocess.run(a,check=True,text=True,capture_output=capture);return r.stdout.strip() if capture else ''
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(16*1024*1024),b''):h.update(c)
 return h.hexdigest()
def integrity(p:Path)->None:
 c=sqlite3.connect(p)
 try:v=str(c.execute('PRAGMA integrity_check').fetchone()[0])
 finally:c.close()
 if v!='ok':raise RuntimeError(f'SQLite integrity failure:{p.name}:{v}')
def self_hash(m:dict[str,Any])->str:
 k='report_hash' if 'report_hash' in m else 'manifest_hash';s=str(m[k]);q=dict(m);q.pop(k)
 if stable_hash(q)!=s:raise RuntimeError('manifest self-hash mismatch')
 return s
def restore_staging(root:Path,w:Path)->tuple[Path,float]:
 t=time.monotonic();m=json.loads((root/'reports/48_FULL_2023_STAGING_RELEASE.json').read_text());d=w/'staging_parts';d.mkdir(parents=True,exist_ok=True);ps=[]
 for x in m['parts']:
  p=d/x['filename'];cmd('curl','-fL','--retry','6','--retry-delay','2',x['url'],'-o',str(p))
  if p.stat().st_size!=x['size_bytes'] or sha(p)!=x['sha256']:raise RuntimeError(f'staging part verification failure:{p.name}')
  ps.append(p)
 z=w/'staging.sqlite.zst'
 with z.open('wb') as out:
  for p in ps:
   with p.open('rb') as src:shutil.copyfileobj(src,out)
 if z.stat().st_size!=m['compressed_size_bytes'] or sha(z)!=m['compressed_sha256']:raise RuntimeError('staging archive verification failure')
 db=w/'staging.sqlite';cmd('zstd','-q','-d','-f',str(z),'-o',str(db));integrity(db);return db,time.monotonic()-t
def prefix(i:int)->str:return 'checkpoint2' if i<0 else f'stage4p{i:02d}'
def restore_parent(repo:str,tag:str,i:int,w:Path)->tuple[Path,dict[str,Any],str,float]:
 t=time.monotonic();n=prefix(i);d=w/f'parent-{n}';d.mkdir(parents=True,exist_ok=True);cmd('gh','release','download',tag,'--repo',repo,'--pattern',f'{n}.*','--dir',str(d),'--clobber');m=json.loads((d/f'{n}.json').read_text());mh=self_hash(m);ps=sorted(d.glob(f'{n}.sqlite.zst.part-*'))
 if [p.name for p in ps]!=[x['filename'] for x in m['parts']]:raise RuntimeError('parent filename coverage mismatch')
 for p,x in zip(ps,m['parts']):
  if p.stat().st_size!=x['size_bytes'] or sha(p)!=x['sha256']:raise RuntimeError(f'parent part verification failure:{p.name}')
 z=d/f'{n}.sqlite.zst'
 with z.open('wb') as out:
  for p in ps:
   with p.open('rb') as src:shutil.copyfileobj(src,out)
 if z.stat().st_size!=m['compressed_size_bytes'] or sha(z)!=m['compressed_sha256']:raise RuntimeError('parent compressed verification failure')
 db=d/f'{n}.sqlite';cmd('zstd','-q','-d','-f',str(z),'-o',str(db))
 if db.stat().st_size!=m['raw_size_bytes'] or sha(db)!=m['raw_sha256']:raise RuntimeError('parent raw verification failure')
 integrity(db)
 if i>=0:
  plan=IndexedContextRejectionEngine.stage4_partition_plan()
  if m['partition_index']!=i or m['plan_hash']!=plan['plan_hash'] or m.get('checkpoint_3_published') is not False:raise RuntimeError('parent official partition contract failure')
 return db,m,mh,time.monotonic()-t
def ensure_bench_release(repo:str,tag:str,head:str)->None:
 if not tag.startswith('moebot-group8-stage4-benchmark-') or head[:12] not in tag:raise RuntimeError('benchmark output tag is not exact-head isolated')
 r=subprocess.run(['gh','release','view',tag,'--repo',repo],text=True,capture_output=True)
 if r.returncode:
  c=subprocess.run(['gh','release','create',tag,'--repo',repo,'--title',f'Group8 stage4 benchmark {head[:12]}','--notes','BENCHMARK_ONLY diagnostics; not official Annual 2023 evidence.'],text=True,capture_output=True)
  if c.returncode and subprocess.run(['gh','release','view',tag,'--repo',repo],text=True,capture_output=True).returncode:raise RuntimeError(f'cannot create benchmark release:{c.stderr}')
def publish_verify(repo:str,tag:str,n:str,db:Path,payload:dict[str,Any],w:Path)->dict[str,float]:
 z=w/f'{n}.sqlite.zst';t=time.monotonic();cmd('zstd','-q','-3','-T0','-f',str(db),'-o',str(z));cmd('split','-b','1750000000','-d','-a','3',str(z),str(w/f'{n}.sqlite.zst.part-'));compression=time.monotonic()-t;t=time.monotonic();ps=[{'filename':p.name,'size_bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(w.glob(f'{n}.sqlite.zst.part-*'))];payload.update({'raw_size_bytes':db.stat().st_size,'raw_sha256':sha(db),'compressed_size_bytes':z.stat().st_size,'compressed_sha256':sha(z),'parts':ps,'compression_seconds':compression});hash_seconds=time.monotonic()-t;payload['hash_seconds']=hash_seconds;payload['manifest_hash']=stable_hash(payload);mp=w/f'{n}.json';mp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');t=time.monotonic();cmd('gh','release','upload',tag,*[str(w/x['filename']) for x in ps],str(mp),'--repo',repo,'--clobber');upload=time.monotonic()-t;d=w/f'verify-{n}';d.mkdir(parents=True,exist_ok=True);t=time.monotonic();cmd('gh','release','download',tag,'--repo',repo,'--pattern',f'{n}.*','--dir',str(d),'--clobber');dm=json.loads((d/f'{n}.json').read_text());self_hash(dm);dps=sorted(d.glob(f'{n}.sqlite.zst.part-*'))
 if [p.name for p in dps]!=[x['filename'] for x in dm['parts']]:raise RuntimeError('public redownload filename mismatch')
 for p,x in zip(dps,dm['parts']):
  if p.stat().st_size!=x['size_bytes'] or sha(p)!=x['sha256']:raise RuntimeError('public redownload part mismatch')
 return {'compression_seconds':compression,'hash_seconds':hash_seconds,'upload_seconds':upload,'redownload_verify_seconds':time.monotonic()-t}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=('benchmark','official'),required=True);p.add_argument('--repo',required=True);p.add_argument('--tag');p.add_argument('--source-tag');p.add_argument('--output-tag');p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--partition',type=int,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--job-start-epoch',type=float,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 if not 0<=a.partition<STAGE4_PARTITION_COUNT:raise ValueError('invalid partition')
 status=json.loads((a.artifacts_root/'STATUS.json').read_text())
 if status['annual_execution_2024_authorized'] is not False:raise RuntimeError('2024 lock is not confirmed')
 if status['free_only_policy']['paid_runner_allowed'] or status['free_only_policy']['paid_service_allowed']:raise RuntimeError('FREE-only policy failure')
 head=cmd('git','rev-parse','HEAD',capture=True);source=a.source_tag or a.tag
 if not source:raise ValueError('source tag is required')
 output=a.output_tag or (f'moebot-group8-stage4-benchmark-{head[:12]}' if a.mode=='benchmark' else source)
 if a.mode=='benchmark':
  if output==source:raise RuntimeError('BENCHMARK_ONLY cannot write official source tag')
  ensure_bench_release(a.repo,output,head)
 elif output!=source:raise RuntimeError('official chain must remain on canonical release tag')
 a.work_dir.mkdir(parents=True,exist_ok=True);staging,sr=restore_staging(a.artifacts_root,a.work_dir);parent_i=-1 if a.mode=='benchmark' or a.partition==0 else a.partition-1;parent,pm,ph,pr=restore_parent(a.repo,source,parent_i,a.work_dir);core=a.work_dir/'core.sqlite';shutil.copy2(parent,core);plan=IndexedContextRejectionEngine.stage4_partition_plan();rid=f"{plan['plan_id']}:range-{a.partition:02d}-{a.partition:02d}";t=time.monotonic();result=run_segment(staging_db=staging,output_db=core,artifacts_root=a.artifacts_root,year=2023,symbol='XAUUSD_',start=4,end=4,stage4_partition=a.partition,benchmark_only=a.mode=='benchmark');execution=time.monotonic()-t;integrity(core)
 if a.mode=='benchmark' and not(result.get('benchmark_only') is True and result.get('official_chain_progress') is False and result.get('official_receipt_published') is False):raise RuntimeError('BENCHMARK_ONLY role contract failure')
 n=f'stage4bench{a.partition:02d}-{head[:12]}' if a.mode=='benchmark' else prefix(a.partition);payload={'status':'PASS','role':'STAGE4_FULL_JOB_BENCHMARK_ONLY' if a.mode=='benchmark' else 'STAGE4_PARTITION_CHECKPOINT','mode':a.mode,'year':2023,'github_head_sha':head,'partition_index':a.partition,'range_identity':rid,'first_partition':a.partition,'last_partition':a.partition,'plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'parent_manifest_hash':ph,'source_tag':source,'output_tag':output,'receipt_preview':result['receipt'],'official_receipt_published':False if a.mode=='benchmark' else True,'restore_seconds':sr+pr,'staging_restore_seconds':sr,'parent_restore_seconds':pr,'execution_seconds':execution,'checkpoint_3_published':False,'free_only':True,'oos_2024_accessed':False};timings=publish_verify(a.repo,output,n,core,payload,a.work_dir);wall=time.time()-a.job_start_epoch;payload.update(timings);payload['full_job_wall_seconds']=wall;payload['safety_limit_seconds']=14400;payload['runtime_safety_pass']=wall<=14400;payload['manifest_hash']=stable_hash({k:v for k,v in payload.items() if k!='manifest_hash'});a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
 if not payload['runtime_safety_pass']:raise RuntimeError(f'full job safety failure:{wall}')
 print(json.dumps(payload,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
