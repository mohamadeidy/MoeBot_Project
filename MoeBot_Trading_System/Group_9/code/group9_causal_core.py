#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from typing import Iterable

STATES={"FORMING","READY","FAILED","MISSING","INVALIDATED"}
TERMINAL={"FAILED","MISSING","INVALIDATED"}
ALLOWED={
 None:{"FORMING"},
 "FORMING":{"READY","FAILED","MISSING"},
 "READY":{"INVALIDATED"},
 "FAILED":set(),"MISSING":set(),"INVALIDATED":set(),
}
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def setup_id(*,family:str,symbol:str,timeframe:str,direction:str,root_subject_type:str,root_subject_id:str,definition_version:str)->str:
 if direction not in {"bullish","bearish"}:raise ValueError("setup direction must be bullish/bearish")
 payload={"family":family,"symbol":symbol,"timeframe":timeframe,"direction":direction,
          "root_subject_type":root_subject_type,"root_subject_id":str(root_subject_id),
          "definition_version":definition_version}
 return "g9s_"+stable(payload)

def evidence_id(*,sid:str,component:str,source_group:int,source_type:str,source_id:str)->str:
 return "g9e_"+stable({"setup_id":sid,"component":component,"source_group":int(source_group),"source_type":source_type,"source_id":str(source_id)})

def transition(*,sid:str,ordinal:int,from_state:str|None,to_state:str,evidence:list[dict],reason_code:str)->dict:
 if to_state not in STATES or (from_state is not None and from_state not in STATES):raise ValueError("invalid state")
 if to_state not in ALLOWED[from_state]:raise ValueError(f"invalid transition:{from_state}->{to_state}")
 if not evidence:raise ValueError("transition requires causal evidence")
 avail=max(int(x["availability_time"]) for x in evidence)
 event=max(int(x.get("event_time",x["availability_time"])) for x in evidence)
 if event>avail:raise ValueError("transition event_time after availability_time")
 body={"setup_id":sid,"transition_ordinal":int(ordinal),"from_state":from_state,"to_state":to_state,
       "event_time":event,"availability_time":avail,"reason_code":reason_code,
       "evidence_ids":sorted(str(x["id"]) for x in evidence)}
 body["transition_id"]="g9t_"+stable(body);body["transition_hash"]=stable(body);return body

def linked_by_identity(a_sources:Iterable[tuple[str,str,str]],b_sources:Iterable[tuple[str,str,str]])->bool:
 return bool(set(a_sources)&set(b_sources))
