#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def make_recipe(*,subject_type:str,subject_id:str,symbol:str,timeframe:str,window_start:int,window_end:int,renderer_version:str,overlay_spec:dict,annotation_spec:dict)->dict:
    if window_end<window_start:raise ValueError("invalid window")
    body={"subject_type":subject_type,"subject_id":subject_id,"symbol":symbol,"timeframe":timeframe,"window_start":window_start,"window_end":window_end,
          "renderer_version":renderer_version,"overlay_spec":overlay_spec,"annotation_spec":annotation_spec}
    body["recipe_id"]="g11r_"+stable(body);body["recipe_hash"]=stable(body);return body
def deterministic_sample(records:list[dict],*,n:int,seed:str,stratum_key:str)->list[dict]:
    if n<0:raise ValueError("n")
    groups={}
    for r in records:groups.setdefault(str(r[stratum_key]),[]).append(r)
    out=[]
    for k in sorted(groups):
        ranked=sorted(groups[k],key=lambda r:stable({"seed":seed,"stratum":k,"id":r["recipe_id"]}))
        out.extend(ranked[:min(n,len(ranked))])
    return out
