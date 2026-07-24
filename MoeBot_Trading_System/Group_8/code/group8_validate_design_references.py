#!/usr/bin/env python3
"""Fail-closed validation for Group 8 definition references before design freeze."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any

CONFIG_ALIASES = {
    "doji_strict_body_ratio": "pattern_thresholds.doji_strict_body_to_range_max",
    "doji_broad_body_ratio": "pattern_thresholds.doji_broad_body_to_range_max",
    "pin_dominant_wick_ratio": "pattern_thresholds.pin_dominant_wick_to_range_min",
    "pin_max_body_ratio": "pattern_thresholds.pin_body_to_range_max",
    "pin_max_opposite_wick_ratio": "pattern_thresholds.pin_opposite_wick_to_range_max",
    "rejection_min_wick_ratio": "pattern_thresholds.rejection_wick_to_range_min",
    "rejection_close_outer_fraction": "pattern_thresholds.rejection_close_outer_fraction",
    "context_proximity_atr": "feature_parameters.proximity_atr_fraction",
    "breakout_atr_buffer": "pattern_thresholds.atr_buffer_breakout_fraction",
}

def walk_strings(v: Any):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values(): yield from walk_strings(x)
    elif isinstance(v, list):
        for x in v: yield from walk_strings(x)

def get_path(d:dict[str,Any], path:str)->Any:
    cur:Any=d
    for part in path.split('.'):
        if not isinstance(cur,dict) or part not in cur: raise KeyError(path)
        cur=cur[part]
    return cur

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--definitions',type=Path,required=True);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--bindings',type=Path,required=True);a=ap.parse_args()
    defs=json.loads(a.definitions.read_text());cfg=json.loads(a.config.read_text());bindings=json.loads(a.bindings.read_text())
    failures=[];refs={'config':{},'bindings':{}}
    if bindings.get('status')!='PASS': failures.append('bindings_not_pass')
    for text in walk_strings(defs):
        for name in re.findall(r'\bconfig\.([A-Za-z_][A-Za-z0-9_]*)',text):
            target=CONFIG_ALIASES.get(name)
            if not target: failures.append(f'unknown_config_alias:{name}');continue
            try: value=get_path(cfg,target)
            except KeyError: failures.append(f'missing_config_target:{name}->{target}');continue
            refs['config'][name]={'target':target,'value':value}
        for path in re.findall(r'UPSTREAM_VALUE_BINDINGS\.([A-Za-z0-9_.]+)',text):
            try:value=get_path(bindings,path)
            except KeyError: failures.append(f'missing_binding:{path}');continue
            refs['bindings'][path]=value
    # All aliases are resolved into a frozen explicit reference map; engine must consume this map, not infer aliases.
    out={'format_version':1,'status':'PASS' if not failures else 'FAIL','definition_file':a.definitions.name,'config_file':a.config.name,'bindings_file':a.bindings.name,'resolved_references':refs,'failures':sorted(set(failures))}
    print(json.dumps(out,indent=2,sort_keys=True));raise SystemExit(0 if not failures else 1)
if __name__=='__main__':main()
