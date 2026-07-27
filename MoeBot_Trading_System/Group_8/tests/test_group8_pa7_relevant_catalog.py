#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from moebot_group8_engine_v0_8_0 import Group8Engine
from group8_annual_core_driver import AnnualCoreEngine
from group8_pa7_shard_executor import ShardSpec,CHAIN_DEFINITIONS
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_relevant_catalog import init_catalog,append_pass1,append_pass2,finalize
from group8_pa7_derived_executor import PA7DerivedEngine
from group8_global_finalizer import Group8GlobalFinalizer
from test_group8_engine_v0_8_0 import ART,make_stage

TABLES={'school_interpretation':('interpretation_id','interpretation_hash'),'narrative_hypothesis':('hypothesis_id','hypothesis_hash'),'hypothesis_lifecycle_event':('lifecycle_event_id','lifecycle_hash'),'invalidation_record':('invalidation_id','invalidation_hash'),'shared_evidence':('shared_evidence_id','shared_evidence_hash'),'conflicting_evidence':('conflict_id','conflict_hash'),'multi_timeframe_context_relation':('relation_id','relation_hash'),'evidence_chain':('evidence_chain_id','evidence_hash')}
def rows(db,table,idc,hashc):
 c=sqlite3.connect(db)
 try:return {str(r[0]):str(r[1]) for r in c.execute(f'SELECT {idc},{hashc} FROM {table}')}
 finally:c.close()
def non_pa7(db):
 c=sqlite3.connect(db)
 try:
  q=','.join('?' for _ in CHAIN_DEFINITIONS);return {str(r[0]):str(r[1]) for r in c.execute(f'SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id NOT IN ({q})',CHAIN_DEFINITIONS)}
 finally:c.close()
def states(db,cids):
 c=sqlite3.connect(db);out={}
 try:
  ids=sorted(cids)
  for n in range(0,len(ids),500):
   ch=ids[n:n+500];q=','.join('?' for _ in ch)
   if ch:
    for r in c.execute(f'SELECT state_event_id,state_hash FROM price_action_pattern_state WHERE candidate_id IN ({q})',ch):out[str(r[0])]=str(r[1])
  return out
 finally:c.close()

class RelevantCatalogParity(unittest.TestCase):
 def test_reduced_catalog_preserves_full_frozen_non_pa7_domain(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';refdb=t/'ref.sqlite';work=t/'work.sqlite';cat=t/'cat.sqlite';make_stage(stage)
   ref=Group8Engine(staging_db=stage,output_db=refdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(ref.run()['status'],'PASS')
   finally:ref.close()
   core=AnnualCoreEngine(staging_db=stage,output_db=work,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(core.run_core()['status'],'PASS')
   finally:core.close()
   self.assertEqual(init_catalog(work,cat)['status'],'PASS');shards=[]
   for tf in ('M15','H1'):
    for scope in ('upstream','group8_range'):
     for b in range(4):
      db=t/f's_{tf}_{scope}_{b}.sqlite';mp=t/f'm_{tf}_{scope}_{b}.json';run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=mp);shards.append(db)
   for i,db in enumerate(shards):self.assertEqual(append_pass1(cat,db,f'shard{i}')['status'],'PASS')
   for i,db in enumerate(shards):self.assertEqual(append_pass2(cat,db,f'shard{i}')['status'],'PASS')
   rep=finalize(cat,t/'cat.json');self.assertEqual(rep['status'],'PASS');self.assertGreater(rep['candidate_rows'],0)
   d=PA7DerivedEngine(staging_db=stage,output_db=work,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(d.run_derived()['status'],'PASS')
   finally:d.close()
   g=Group8GlobalFinalizer(staging_db=stage,output_db=work,pa7_catalog=cat,artifacts_root=ART,year=2023,symbol='XAUUSD_')
   try:self.assertEqual(g.run_global_finalizer()['status'],'PASS')
   finally:g.close()
   exp=non_pa7(refdb);got=non_pa7(work);self.assertEqual(exp,got);self.assertEqual(states(refdb,set(exp)),states(work,set(got)))
   for table,(idc,hashc) in TABLES.items():self.assertEqual(rows(refdb,table,idc,hashc),rows(work,table,idc,hashc),table)

if __name__=='__main__':unittest.main()
