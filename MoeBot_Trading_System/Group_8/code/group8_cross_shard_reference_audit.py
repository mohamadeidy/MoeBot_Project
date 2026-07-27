#!/usr/bin/env python3
"""Audit every Group8-domain reference in the finalized non-PA7 core.

Candidate references may resolve either in the finalized core or in the reduced PA7
query catalog. Other Group8 subjects resolve in the finalized core. PA7 shard-local
chain references are audited separately by logical-sidecar generation; legitimate
PA7-to-core references are resolved here.
"""
from __future__ import annotations
import argparse,json,sqlite3,hashlib
from pathlib import Path
from typing import Any


def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


MAP={
 'price_action_pattern_candidate':('price_action_pattern_candidate','candidate_id'),
 'price_action_pattern_state':('price_action_pattern_state','state_event_id'),
 'school_interpretation':('school_interpretation','interpretation_id'),
 'shared_evidence':('shared_evidence','shared_evidence_id'),
 'conflicting_evidence':('conflicting_evidence','conflict_id'),
 'narrative_hypothesis':('narrative_hypothesis','hypothesis_id'),
 'hypothesis_lifecycle_event':('hypothesis_lifecycle_event','lifecycle_event_id'),
 'multi_timeframe_context_relation':('multi_timeframe_context_relation','relation_id'),
 'evidence_chain':('evidence_chain','evidence_chain_id'),
 'invalidation_record':('invalidation_record','invalidation_id'),
}


def audit(core_db:Path,pa7_catalog:Path,report:Path)->dict[str,Any]:
 c=sqlite3.connect(core_db);c.row_factory=sqlite3.Row;c.execute("ATTACH DATABASE ? AS pa7",(str(pa7_catalog.resolve()),));un=[];checked=0
 def exists(kind:str,rid:str)->bool:
  nonlocal checked;checked+=1
  if kind=='price_action_pattern_candidate':
   return c.execute('SELECT 1 FROM price_action_pattern_candidate WHERE candidate_id=? UNION ALL SELECT 1 FROM pa7.pa7_candidate_catalog WHERE candidate_id=? LIMIT 1',(rid,rid)).fetchone() is not None
  rec=MAP.get(kind)
  if not rec:return False
  return c.execute(f'SELECT 1 FROM {rec[0]} WHERE {rec[1]}=? LIMIT 1',(rid,)).fetchone() is not None
 def check(kind:str,rid:Any,where:str):
  if rid is None:return
  if not exists(kind,str(rid)) and len(un)<100:un.append({'where':where,'target_type':kind,'target_id':str(rid)})
 try:
  for table,idc in (('price_action_pattern_candidate','candidate_id'),('school_interpretation','interpretation_id'),('narrative_hypothesis','hypothesis_id')):
   for row in c.execute(f'SELECT {idc},upstream_refs_json FROM {table}'):
    for ref in json.loads(row['upstream_refs_json']):
     if str(ref.get('source_group','')).lower()=='group8':check(str(ref.get('source_type') or ''),ref.get('source_id'),f'{table}:{row[idc]}:upstream')
  for r in c.execute('SELECT evidence_chain_id,subject_type,subject_id,source_group,source_type,source_id FROM evidence_chain'):
   check(str(r['subject_type']),r['subject_id'],f"evidence:{r['evidence_chain_id']}:subject")
   if str(r['source_group']).lower()=='group8':check(str(r['source_type']),r['source_id'],f"evidence:{r['evidence_chain_id']}:source")
  for r in c.execute('SELECT shared_evidence_id,subject_ids_json FROM shared_evidence'):
   for rid in json.loads(r['subject_ids_json']):
    # Frozen global-finalizer subjects are interpretations or hypotheses.
    ok=exists('school_interpretation',str(rid)) or exists('narrative_hypothesis',str(rid))
    if not ok and len(un)<100:un.append({'where':f"shared:{r['shared_evidence_id']}",'target_type':'subject','target_id':str(rid)})
  for r in c.execute('SELECT conflict_id,left_subject_type,left_subject_id,right_subject_type,right_subject_id FROM conflicting_evidence'):
   check(str(r['left_subject_type']),r['left_subject_id'],f"conflict:{r['conflict_id']}:left");check(str(r['right_subject_type']),r['right_subject_id'],f"conflict:{r['conflict_id']}:right")
  for r in c.execute('SELECT relation_id,subject_type,subject_id,object_type,object_id FROM multi_timeframe_context_relation'):
   check(str(r['subject_type']),r['subject_id'],f"mtf:{r['relation_id']}:subject");check(str(r['object_type']),r['object_id'],f"mtf:{r['relation_id']}:object")
  for r in c.execute('SELECT lifecycle_event_id,hypothesis_id,source_type,source_id FROM hypothesis_lifecycle_event'):
   check('narrative_hypothesis',r['hypothesis_id'],f"life:{r['lifecycle_event_id']}:subject")
   if r['source_type'] in MAP:check(str(r['source_type']),r['source_id'],f"life:{r['lifecycle_event_id']}:source")
  for r in c.execute('SELECT invalidation_id,subject_type,subject_id,source_type,source_id FROM invalidation_record'):
   check(str(r['subject_type']),r['subject_id'],f"inv:{r['invalidation_id']}:subject")
   if r['source_type'] in MAP:check(str(r['source_type']),r['source_id'],f"inv:{r['invalidation_id']}:source")
  rec={'format_version':1,'status':'PASS' if not un else 'FAIL','checked_reference_count':checked,'unresolved_group8_reference_count':len(un),'unresolved_group8_reference_sample':un,'core_quick_check':c.execute('PRAGMA quick_check').fetchone()[0],'free_only':True,'paid_runner_used':False,'paid_service_used':False};rec['report_hash']=stable(rec);report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
  if un:raise RuntimeError(f'unresolved Group8 references:{un[:5]}')
  return rec
 finally:c.close()


def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--core-db',type=Path,required=True);p.add_argument('--pa7-catalog',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();print(json.dumps(audit(a.core_db,a.pa7_catalog,a.report),indent=2,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
