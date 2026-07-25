#!/usr/bin/env python3
"""Build machine-readable Group8 upstream semantic evidence from exact canonical runtime sources.

This script does not infer meanings from labels alone. It verifies exact source-code rules in
canonical SHA-pinned G2-G5 engines and emits only the semantics needed by Group8 adapters.
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path
from typing import Any

EXPECTED={
 'group2':('moebot_group2_engine_v0_2_1.py','3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926'),
 'group3':('moebot_group3_structure_engine_v0_1_1.py','8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512'),
 'group4':('moebot_group4_zones_engine_v0_1_6.py','744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad'),
 'group5':('moebot_group5_liquidity_engine_v0_1_6.py','97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc'),
}
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def locate(root:Path,name:str)->Path:
 xs=list(root.rglob(name))
 if len(xs)!=1:raise RuntimeError(f'expected one {name}, found {xs}')
 return xs[0]
def ast_literal_assignment(tree:ast.AST,name:str)->Any:
 for node in ast.walk(tree):
  if isinstance(node,ast.Assign):
   for target in node.targets:
    if isinstance(target,ast.Name) and target.id==name:return ast.literal_eval(node.value)
 raise KeyError(name)
def require(text:str,snippet:str,label:str,failures:list[str])->None:
 if snippet not in text:failures.append(f'missing_source_rule:{label}')
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--runtime-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();root=a.runtime_root.resolve();files={};texts={};fail=[]
 for g,(name,want) in EXPECTED.items():
  p=locate(root,name);got=sha(p);files[g]={'filename':name,'sha256':got,'expected_sha256':want,'sha256_pass':got==want};texts[g]=p.read_text()
  if got!=want:fail.append(f'sha:{g}:{got}')
 g2=ast.parse(texts['group2']);directional=ast_literal_assignment(g2,'DIRECTIONAL');labels=ast_literal_assignment(g2,'LABELS')
 expected_directional={'strong_bullish_trend':1,'weak_bullish_trend':1,'strong_bearish_trend':-1,'weak_bearish_trend':-1}
 if directional!=expected_directional:fail.append('group2_directional_mapping_drift')
 require(texts['group3'],"if hr=='HH' and lr=='HL':self.sequence_bias='bullish'",'g3_bullish_sequence',fail)
 require(texts['group3'],"elif hr=='LH' and lr=='LL':self.sequence_bias='bearish'",'g3_bearish_sequence',fail)
 require(texts['group3'],"elif hr and lr and hr!='INITIAL' and lr!='INITIAL':self.sequence_bias='transition'",'g3_transition_sequence',fail)
 require(texts['group3'],"else:self.sequence_bias='unknown'",'g3_unknown_sequence',fail)
 require(texts['group3'],"et='BOS' if p.break_kind=='continuation' else ('MSS' if p.strong_break else 'CHOCH')",'g3_break_event_rule',fail)
 require(texts['group3'],"events.append(self._event(p,'FAILED_BREAK','failed'",'g3_failed_break',fail)
 require(texts['group3'],"if p.direction=='up':self.active_bias='bullish'",'g3_up_to_bullish',fail)
 require(texts['group3'],"else:self.active_bias='bearish'",'g3_down_to_bearish',fail)
 require(texts['group3'],"out.append(('up','continuation',self.last_high))",'g3_bullish_continuation_target',fail)
 require(texts['group3'],"out.append(('down','reversal',self.protected_low))",'g3_bullish_reversal_target',fail)
 require(texts['group3'],"out.append(('down','continuation',self.last_low))",'g3_bearish_continuation_target',fail)
 require(texts['group3'],"out.append(('up','reversal',self.protected_high))",'g3_bearish_reversal_target',fail)
 require(texts['group4'],'z.status=\'flipped\'; z.current_role=\'support\' if bdir==\'up\' else \'resistance\'','g4_flip_role_rule',fail)
 require(texts['group4'],"new_status='mitigated' if pen>=self.cfg.mitigation_penetration or close_inside else 'tested'",'g4_touch_state_rule',fail)
 require(texts['group5'],'is_sweep = int(is_primary and reclaimed)','g5_sweep_requires_reclaim',fail)
 require(texts['group5'],'is_primary = event_type != "reclaim"','g5_primary_event_rule',fail)
 require(texts['group5'],'is_grab = int(event_type == "liquidity_grab")','g5_grab_flag_rule',fail)
 require(texts['group5'],'is_stop = int(event_type == "stop_run")','g5_stop_flag_rule',fail)
 require(texts['group5'],'if bar.active_bias == "bullish" and bp is not None','g5_bullish_draw_rule',fail)
 require(texts['group5'],'elif bar.active_bias == "bearish" and sp is not None','g5_bearish_draw_rule',fail)
 semantics={
  'group2':{
   'directional_label_sign':directional,
   'neutral_direction_labels':['neutral_range'],
   'all_engine_labels':labels,
   'interpretation_rule':'Only labels present in directional_label_sign are directional; neutral_range is non-directional; phase/volatility labels are not direction signals.'},
  'group3':{
   'sequence_bias_values':['bullish','bearish','transition','unknown'],
   'active_bias_values':['bullish','bearish','transition','unknown'],
   'direction_values':['up','down'],
   'break_kind_values':['continuation','reversal'],
   'accepted_event_mapping':{'continuation':'BOS','reversal_strong':'MSS','reversal_non_strong':'CHOCH'},
   'failed_event_type':'FAILED_BREAK','accepted_outcome':'accepted','failed_outcome':'failed',
   'swing_relations':['INITIAL','HH','LH','HL','LL'],
   'layers':['internal','external']},
  'group4':{
   'base_roles':['support','resistance'],
   'core_status_progression_values':['fresh','tested','mitigated','broken','flipped','superseded','expired'],
   'flip_rule':'break up then qualifying opposite-side retest => support; break down then qualifying retest => resistance',
   'touch_rule':'mitigated when penetration threshold reached or close inside; otherwise tested'},
  'group5':{
   'pool_sides':['buy_side','sell_side'],
   'draw_sides':['buy_side','sell_side','none','balanced_uncertain'],
   'primary_event_types':['liquidity_grab','stop_run','false_breakout','taken_without_reclaim','censored_pending'],
   'auxiliary_event_type':'reclaim',
   'sweep_flag_rule':'is_sweep=1 only for a non-reclaim primary event whose interaction was reclaimed',
   'grab_flag_rule':'event_type==liquidity_grab','stop_run_flag_rule':'event_type==stop_run',
   'draw_rule':'bullish active_bias may select nearest eligible buy-side pool; bearish active_bias may select nearest eligible sell-side pool; otherwise deterministic distance/ambiguity logic applies'}
 }
 out={'format_version':1,'status':'PASS' if not fail else 'FAIL','source_files':files,'semantics':semantics,'failures':fail};out['evidence_hash']=hashlib.sha256(canon(out).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':out['status'],'evidence_hash':out['evidence_hash'],'failures':fail},indent=2));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
