#!/usr/bin/env python3
"""Fail-closed validation for Group 8 definition references before design freeze."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from typing import Any
CONFIG_ALIASES={
 "doji_strict_body_ratio":"pattern_thresholds.doji_strict_body_to_range_max",
 "doji_broad_body_ratio":"pattern_thresholds.doji_broad_body_to_range_max",
 "pin_dominant_wick_ratio":"pattern_thresholds.pin_dominant_wick_to_range_min",
 "pin_max_body_ratio":"pattern_thresholds.pin_body_to_range_max",
 "pin_max_opposite_wick_ratio":"pattern_thresholds.pin_opposite_wick_to_range_max",
 "rejection_min_wick_ratio":"pattern_thresholds.rejection_wick_to_range_min",
 "rejection_close_outer_fraction":"pattern_thresholds.rejection_close_outer_fraction",
 "context_proximity_atr":"feature_parameters.proximity_atr_fraction",
 "breakout_atr_buffer":"pattern_thresholds.atr_buffer_breakout_fraction",
}
def walk_strings(v:Any):
 if isinstance(v,str):yield v
 elif isinstance(v,dict):
  for x in v.values():yield from walk_strings(x)
 elif isinstance(v,list):
  for x in v:yield from walk_strings(x)
def get_path(d:dict[str,Any],path:str)->Any:
 cur:Any=d
 for part in path.split('.'):
  if not isinstance(cur,dict) or part not in cur:raise KeyError(path)
  cur=cur[part]
 return cur
def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--definitions',type=Path,required=True);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--bindings',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();defs=json.loads(a.definitions.read_text());cfg=json.loads(a.config.read_text());bindings=json.loads(a.bindings.read_text());binding_values=bindings.get('bindings',bindings);fail=[];refs={'config':{},'bindings':{}}
 if bindings.get('status')!='PASS':fail.append('bindings_not_pass')
 for text in walk_strings(defs):
  for name in re.findall(r'\bconfig\.([A-Za-z_][A-Za-z0-9_]*)',text):
   target=CONFIG_ALIASES.get(name)
   if not target:fail.append(f'unknown_config_alias:{name}');continue
   try:value=get_path(cfg,target)
   except KeyError:fail.append(f'missing_config_target:{name}->{target}');continue
   refs['config'][name]={'target':target,'value':value}
  for path in re.findall(r'UPSTREAM_VALUE_BINDINGS\.(group[0-9]+\.[A-Za-z0-9_.]+)',text):
   try:value=get_path(binding_values,path)
   except KeyError:fail.append(f'missing_binding:{path}');continue
   refs['bindings'][path]=value
 out={'format_version':1,'status':'PASS' if not fail else 'FAIL','definition_file':a.definitions.name,'config_file':a.config.name,'bindings_file':a.bindings.name,'binding_hash':bindings.get('binding_hash'),'resolved_references':refs,'failures':sorted(set(fail))};out['resolution_hash']=hashlib.sha256(canon(out).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':out['status'],'resolution_hash':out['resolution_hash'],'failures':out['failures']},indent=2));raise SystemExit(0 if not fail else 1)
if __name__=='__main__':main()
