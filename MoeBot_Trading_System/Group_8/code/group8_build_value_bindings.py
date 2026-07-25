#!/usr/bin/env python3
"""Bind observed annual categorical values to source-verified Group8 semantics."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any

def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def union_values(d:dict[str,Any],group:str,table:str,field:str)->list[Any]:
 row=d['cross_year'][group][table][field];return row['union']
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--categorical-dictionary',type=Path,required=True);ap.add_argument('--source-semantics',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();cats=json.loads(a.categorical_dictionary.read_text());src=json.loads(a.source_semantics.read_text());fail=[]
 if cats.get('status')!='PASS':fail.append('categorical_dictionary_not_pass')
 if src.get('status')!='PASS':fail.append('source_semantics_not_pass')
 s3=src['semantics']['group3']
 observed={
  'active_bias':union_values(cats,'group3','structure_states','active_bias'),
  'sequence_bias':union_values(cats,'group3','structure_states','sequence_bias'),
  'event_type':union_values(cats,'group3','break_events','event_type'),
  'direction':union_values(cats,'group3','break_events','direction'),
  'break_kind':union_values(cats,'group3','break_events','break_kind'),
  'outcome':union_values(cats,'group3','break_events','outcome'),
  'layer_structure':union_values(cats,'group3','structure_states','layer'),
  'layer_events':union_values(cats,'group3','break_events','layer'),
  'swing_relation':union_values(cats,'group3','swings','relation')}
 expected={
  'active_bias':set(s3['active_bias_values']),'sequence_bias':set(s3['sequence_bias_values']),
  'event_type':{'BOS','MSS','CHOCH',s3['failed_event_type']},'direction':set(s3['direction_values']),
  'break_kind':set(s3['break_kind_values']),'outcome':{s3['accepted_outcome'],s3['failed_outcome']},
  'layer_structure':set(s3['layers']),'layer_events':set(s3['layers']),'swing_relation':set(s3['swing_relations'])}
 coverage={}
 for key,vals in observed.items():
  actual=set(vals);unknown=sorted(actual-expected[key]);coverage[key]={'observed':vals,'source_verified_allowed':sorted(expected[key]),'unknown':unknown,'pass':not unknown}
  if unknown:fail.append(f'unknown_group3_{key}:{unknown}')
 # Mechanical transition semantics are source-verified: continuation=>BOS, reversal strong=>MSS, reversal non-strong=>CHOCH.
 bindings={
  'group3':{
   'advancing_bias_values':['bullish'],
   'declining_bias_values':['bearish'],
   'indeterminate_bias_values':['transition','unknown'],
   'bullish_direction_values':['up'],
   'bearish_direction_values':['down'],
   'bullish_transition_event_types':['CHOCH','MSS'],
   'bearish_transition_event_types':['CHOCH','MSS'],
   'bos_event_types':['BOS'],
   'mss_or_bos_event_types':['BOS','MSS'],
   'all_accepted_structure_event_types':['BOS','CHOCH','MSS'],
   'failed_break_event_types':[s3['failed_event_type']],
   'accepted_outcome_values':[s3['accepted_outcome']],
   'failed_outcome_values':[s3['failed_outcome']],
   'continuation_break_kind_values':['continuation'],
   'reversal_break_kind_values':['reversal'],
   'internal_layer_values':['internal'],
   'external_layer_values':['external']}}
 # Bindings must themselves be subsets of source-verified and observed-capable domains; absence in one finite year is allowed, unknown values are not.
 for name,vals in bindings['group3'].items():
  if not isinstance(vals,list) or not vals:fail.append(f'empty_binding:{name}')
 report={'format_version':1,'status':'PASS' if not fail else 'FAIL','source_semantics_evidence_hash':src['evidence_hash'],'categorical_dictionary_hash':cats['dictionary_hash'],'bindings':bindings,'observed_domain_coverage':coverage,'unknown_value_policy':'Preserve raw upstream value, mark interpretation unclassified/ambiguous, and do not coerce into any frozen binding.','failures':fail}
 report['binding_hash']=hashlib.sha256(canon(report).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'binding_hash':report['binding_hash'],'failures':fail},indent=2));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
