#!/usr/bin/env python3
"""Permanent exact stage-4 parity, benchmark-role parity, and negative gates."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sqlite3,time
from pathlib import Path
from typing import Any
from group8_annual_core_driver import AnnualCoreEngine
from group8_context_rejection_fastpath import STAGE4_PARTITION_COUNT
from group8_postprocess_v0_8_0 import checkpoint
from group8_segmented_annual_core import _enforce_stage4_execution_order,_validated_receipt
from moebot_group8_engine_v0_8_0 import canonical_json,stable_hash

LOGICAL_TABLES=("price_action_pattern_candidate","price_action_pattern_state","school_interpretation","narrative_hypothesis","hypothesis_lifecycle_event","shared_evidence","conflicting_evidence","multi_timeframe_context_relation","evidence_chain","invalidation_record","processing_checkpoint")
STAGE4_DEF="pa_context_linked_rejection";SOURCE_DEFS=("pa_pin_bar_like","pa_rejection_close")

def _pk_cols(con,table):
 rows=con.execute(f"PRAGMA table_info('{table}')").fetchall();return [str(r[1]) for r in sorted((r for r in rows if int(r[5])>0),key=lambda r:int(r[5]))]
def _rows(con,table):
 cols=[str(r[1]) for r in con.execute(f"PRAGMA table_info('{table}')")];order=','.join(f'"{c}"' for c in (_pk_cols(con,table) or cols));return [{c:row[i] for i,c in enumerate(cols)} for row in con.execute(f'SELECT * FROM "{table}" ORDER BY {order}')]
def _fingerprint(con,table):
 rows=_rows(con,table);hashes=[hashlib.sha256(canonical_json(r).encode()).hexdigest() for r in rows];pk=_pk_cols(con,table);return {'count':len(rows),'primary_ids':[tuple(r[c] for c in pk) for r in rows],'row_hashes':hashes,'logical_fingerprint':stable_hash(hashes)}
def _counts_by_definition(con):return {t:{str(r[0]):int(r[1]) for r in con.execute(f'SELECT definition_id,COUNT(*) FROM "{t}" GROUP BY definition_id ORDER BY definition_id')} for t in ('price_action_pattern_candidate','school_interpretation','narrative_hypothesis')}
def _stage4_rows(con):
 cols=[str(r[1]) for r in con.execute("PRAGMA table_info('price_action_pattern_candidate')")];return [{c:row[i] for i,c in enumerate(cols)} for row in con.execute('SELECT * FROM price_action_pattern_candidate WHERE definition_id=? ORDER BY candidate_id',(STAGE4_DEF,))]
def _assert_zero_duplicates(con):
 for table in LOGICAL_TABLES:
  pk=_pk_cols(con,table)
  if pk:
   group=','.join(f'"{c}"' for c in pk)
   if con.execute(f'SELECT 1 FROM "{table}" GROUP BY {group} HAVING COUNT(*)>1 LIMIT 1').fetchone() is not None:raise AssertionError(f'duplicate logical primary key:{table}')
 if con.execute('''SELECT 1 FROM price_action_pattern_candidate WHERE definition_id=? GROUP BY source_bar_id,event_time,confirmation_time,availability_time,features_json,upstream_refs_json HAVING COUNT(*)>1 LIMIT 1''',(STAGE4_DEF,)).fetchone() is not None:raise AssertionError('duplicate stage-4 domain output')
def _assert_references(con):
 missing=int(con.execute('''SELECT COUNT(*) FROM price_action_pattern_state s LEFT JOIN price_action_pattern_candidate p ON p.candidate_id=s.candidate_id WHERE p.candidate_id IS NULL''').fetchone()[0])
 if missing:raise AssertionError(f'missing pattern references:{missing}')
def _fixture_ids(db,per_partition):
 con=sqlite3.connect(db)
 try:rows=con.execute('''SELECT candidate_id,availability_time FROM price_action_pattern_candidate WHERE definition_id IN (?,?) ORDER BY availability_time,candidate_id''',SOURCE_DEFS).fetchall()
 finally:con.close()
 buckets={i:[] for i in range(STAGE4_PARTITION_COUNT)}
 for cid,av in rows:buckets[AnnualCoreEngine._partition_for_candidate(str(cid))].append((str(cid),int(av)))
 chosen=set()
 for vals in buckets.values():
  if not vals:continue
  if len(vals)<=per_partition:chosen.update(x[0] for x in vals);continue
  points={round(i*(len(vals)-1)/(per_partition-1)) for i in range(per_partition)};chosen.update(vals[i][0] for i in sorted(points))
 if not chosen:raise AssertionError('fixture selection produced zero candidates')
 return chosen
def _install_allowlist(con,ids):
 con.execute('CREATE TEMP TABLE IF NOT EXISTS stage4_fixture_allowlist(candidate_id TEXT PRIMARY KEY)');con.execute('DELETE FROM stage4_fixture_allowlist');con.executemany('INSERT INTO stage4_fixture_allowlist(candidate_id) VALUES(?)',[(x,) for x in sorted(ids)]);con.commit()
class _Rows:
 def __init__(self,rows):self.rows=list(rows)
 def fetchall(self):return list(self.rows)
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
def _filtered_process(engine,partition,ids):
 original=engine.out;_install_allowlist(original,ids);selected=original.execute("""SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') AND candidate_id IN (SELECT candidate_id FROM stage4_fixture_allowlist) ORDER BY availability_time,candidate_id""").fetchall()
 if partition is not None:selected=[r for r in selected if engine._partition_for_candidate(str(r['candidate_id']))==partition]
 class Proxy:
  def __init__(self,con,rows):self._con,self._rows=con,rows
  def execute(self,sql,params=()):
   if "definition_id IN ('pa_pin_bar_like','pa_rejection_close')" in sql and 'ORDER BY availability_time,candidate_id' in sql:return _Rows(self._rows)
   return self._con.execute(sql,params)
  def __getattr__(self,name):return getattr(self._con,name)
 engine.out=Proxy(original,selected)
 try:return engine.process_context_rejections_fast(partition_index=partition)
 finally:engine.out=original
def _run_one_shot(staging,base,out,root,ids):
 shutil.copy2(base,out);e=AnnualCoreEngine(staging_db=staging,output_db=out,artifacts_root=root,year=2023,symbol='XAUUSD_')
 try:e.load_bars();t=time.monotonic();_filtered_process(e,None,ids);checkpoint(e,'context_rejections_fast');return time.monotonic()-t
 finally:e.close()
def _run_partitioned(staging,base,out,root,ids):
 shutil.copy2(base,out);e=AnnualCoreEngine(staging_db=staging,output_db=out,artifacts_root=root,year=2023,symbol='XAUUSD_');times=[]
 try:
  e.load_bars()
  for i in range(STAGE4_PARTITION_COUNT):_enforce_stage4_execution_order(e,i);t=time.monotonic();_filtered_process(e,i,ids);times.append(time.monotonic()-t)
  e.verify_stage4_partition_coverage();checkpoint(e,'context_rejections_fast');return times
 finally:e.close()
def _compare(one,part):
 a=sqlite3.connect(one);a.row_factory=sqlite3.Row;b=sqlite3.connect(part);b.row_factory=sqlite3.Row
 try:
  for con in (a,b):_assert_zero_duplicates(con);_assert_references(con)
  fa={t:_fingerprint(a,t) for t in LOGICAL_TABLES};fb={t:_fingerprint(b,t) for t in LOGICAL_TABLES}
  if fa!=fb:raise AssertionError(f"logical table mismatch:{[t for t in LOGICAL_TABLES if fa[t]!=fb[t]]}")
  if _counts_by_definition(a)!=_counts_by_definition(b):raise AssertionError('counts by definition mismatch')
  fields=('candidate_id','candidate_hash','features_json','upstream_refs_json','event_time','confirmation_time','availability_time');ra,rb=_stage4_rows(a),_stage4_rows(b)
  if [{k:r[k] for k in fields} for r in ra]!=[{k:r[k] for k in fields} for r in rb]:raise AssertionError('stage-4 exact field mismatch')
  return {'status':'PASS','tables':fa,'counts_by_definition':_counts_by_definition(a),'stage4_output_count':len(ra)}
 finally:a.close();b.close()
def _expect_fail(name,fn):
 try:fn()
 except Exception:return
 raise AssertionError(f'negative regression did not fail:{name}')
def _negative_tests(staging,base,root,ids,work):
 db=work/'negative.sqlite';shutil.copy2(base,db);e=AnnualCoreEngine(staging_db=staging,output_db=db,artifacts_root=root,year=2023,symbol='XAUUSD_')
 try:
  e.load_bars();_expect_fail('wrong execution order',lambda:_enforce_stage4_execution_order(e,1));_enforce_stage4_execution_order(e,0);r0=_filtered_process(e,0,ids);existing=_enforce_stage4_execution_order(e,0);r0b=_filtered_process(e,0,ids)
  if existing!=r0 or r0b!=r0:raise AssertionError('same-partition retry not idempotent')
  key=next(r[0] for r in e.out.execute("SELECT key FROM metadata WHERE key LIKE 'physical_stage4_partition_receipt:%:00'"));_expect_fail('repeated partition',lambda:e.out.execute('INSERT INTO metadata(key,value) VALUES(?,?)',(key,e.out.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()[0])));_expect_fail('finalize before complete coverage',e.verify_stage4_partition_coverage);saved=e.out.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()[0]
  bad=json.loads(saved);bad['plan_hash']='0'*64;bad['receipt_hash']=stable_hash({k:v for k,v in bad.items() if k!='receipt_hash'});e.out.execute('UPDATE metadata SET value=? WHERE key=?',(json.dumps(bad,sort_keys=True,separators=(',',':')),key));_expect_fail('wrong plan hash',lambda:_validated_receipt(e,0));e.out.execute('UPDATE metadata SET value=? WHERE key=?',(saved,key));bad=json.loads(saved);bad['receipt_hash']='f'*64;e.out.execute('UPDATE metadata SET value=? WHERE key=?',(json.dumps(bad,sort_keys=True,separators=(',',':')),key));_expect_fail('conflicting receipt',lambda:_validated_receipt(e,0));e.out.execute('UPDATE metadata SET value=? WHERE key=?',(saved,key));_expect_fail('missing partition',e.verify_stage4_partition_coverage);clean=work/'negative_clean.sqlite';e.out.commit();shutil.copy2(db,clean);row=e.out.execute('SELECT candidate_id FROM price_action_pattern_candidate WHERE definition_id=? LIMIT 1',(STAGE4_DEF,)).fetchone()
  if row:e.out.execute('DROP TRIGGER IF EXISTS no_update_price_action_pattern_candidate');e.out.execute("UPDATE price_action_pattern_candidate SET features_json='{}' WHERE candidate_id=?",(row[0],));e.out.commit();_expect_fail('modified partition output',lambda:_compare(clean,db))
  return {'missing_partition':'PASS','repeated_partition':'PASS','conflicting_receipt':'PASS','modified_partition_output':'PASS','wrong_plan_hash':'PASS','wrong_execution_order':'PASS','finalize_before_complete':'PASS','idempotent_retry':'PASS'}
 finally:e.close()
def _benchmark_role_parity(staging,base,root,ids,work,index=3):
 pre=work/'role_pre.sqlite';shutil.copy2(base,pre);e=AnnualCoreEngine(staging_db=staging,output_db=pre,artifacts_root=root,year=2023,symbol='XAUUSD_')
 try:
  e.load_bars()
  for i in range(index):_enforce_stage4_execution_order(e,i);_filtered_process(e,i,ids)
  e.out.commit()
 finally:e.close()
 official=work/'role_official.sqlite';bench=work/'role_benchmark.sqlite';shutil.copy2(pre,official);shutil.copy2(pre,bench);c=sqlite3.connect(bench);c.execute("DELETE FROM metadata WHERE key LIKE 'physical_stage4_partition_receipt:%'");c.commit();c.close()
 eo=AnnualCoreEngine(staging_db=staging,output_db=official,artifacts_root=root,year=2023,symbol='XAUUSD_');eb=AnnualCoreEngine(staging_db=staging,output_db=bench,artifacts_root=root,year=2023,symbol='XAUUSD_')
 try:
  eo.load_bars();eb.load_bars();_enforce_stage4_execution_order(eo,index);ro=_filtered_process(eo,index,ids)
  for i in range(STAGE4_PARTITION_COUNT):
   if _validated_receipt(eb,i) is not None:raise AssertionError('benchmark clone retained official receipt')
  rb=_filtered_process(eb,index,ids);eo.out.commit();eb.out.commit()
 finally:eo.close();eb.close()
 oc=sqlite3.connect(official);bc=sqlite3.connect(bench);oc.row_factory=sqlite3.Row;bc.row_factory=sqlite3.Row
 try:
  source_ids={x for x in ids if AnnualCoreEngine._partition_for_candidate(x)==index};op=[dict(r) for r in oc.execute('SELECT * FROM price_action_pattern_candidate WHERE definition_id=? AND json_extract(upstream_refs_json,"$[0].source_id") IN (%s) ORDER BY candidate_id'%(','.join('?' for _ in source_ids) or "''"),(STAGE4_DEF,*sorted(source_ids)))];bp=[dict(r) for r in bc.execute('SELECT * FROM price_action_pattern_candidate WHERE definition_id=? AND json_extract(upstream_refs_json,"$[0].source_id") IN (%s) ORDER BY candidate_id'%(','.join('?' for _ in source_ids) or "''"),(STAGE4_DEF,*sorted(source_ids)))]
  fields=('candidate_id','candidate_hash','feature_hash','features_json','upstream_refs_json','event_time','confirmation_time','availability_time')
  if [{k:r[k] for k in fields} for r in op]!=[{k:r[k] for k in fields} for r in bp]:raise AssertionError('BENCHMARK_ONLY candidate output mismatch')
  if ro!=rb:raise AssertionError('BENCHMARK_ONLY receipt preview mismatch')
  return {'status':'PASS','partition_index':index,'source_ids_hash':ro['source_ids_hash'],'output_ids_hash':ro['output_ids_hash'],'candidate_ids':[r['candidate_id'] for r in op],'row_hashes':[r['candidate_hash'] for r in op],'features_json_equal':True,'upstream_refs_json_equal':True,'causal_timestamps_equal':True,'receipt_content_equal_before_publication':True,'official_artifact_published':False,'checkpoint_3_published':False}
 finally:oc.close();bc.close()
def main():
 p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--checkpoint2-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--fixture-per-partition',type=int,default=8);p.add_argument('--report',type=Path,required=True);a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True);ids=_fixture_ids(a.checkpoint2_db,a.fixture_per_partition);one=a.work_dir/'one_shot.sqlite';part=a.work_dir/'partitioned.sqlite';one_time=_run_one_shot(a.staging_db,a.checkpoint2_db,one,a.artifacts_root,ids);part_times=_run_partitioned(a.staging_db,a.checkpoint2_db,part,a.artifacts_root,ids);parity=_compare(one,part);negatives=_negative_tests(a.staging_db,a.checkpoint2_db,a.artifacts_root,ids,a.work_dir);role=_benchmark_role_parity(a.staging_db,a.checkpoint2_db,a.artifacts_root,ids,a.work_dir);report={'status':'PASS','fixture_candidate_count':len(ids),'partition_count':STAGE4_PARTITION_COUNT,'one_shot_seconds':one_time,'partition_seconds':part_times,'worst_partition_seconds':max(part_times),'parity':parity,'benchmark_role_parity':role,'negative_regressions':negatives};a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
