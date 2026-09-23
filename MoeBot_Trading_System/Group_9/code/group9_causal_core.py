#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from typing import Iterable

STATES={"FORMING","READY","FAILED","MISSING","INVALIDATED"}
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def setup_id(symbol:str,timeframe:str,direction:str,root_ids:Iterable[str],definition_version:str)->str:
    payload={"symbol":symbol,"timeframe":timeframe,"direction":direction,"root_ids":sorted(map(str,root_ids)),"definition_version":definition_version}
    return "g9s_"+stable(payload)
def transition(*,sid:str,from_state:str|None,to_state:str,evidence:list[dict],reason_code:str)->dict:
    if to_state not in STATES or (from_state is not None and from_state not in STATES):raise ValueError("invalid state")
    if not evidence:raise ValueError("transition requires evidence")
    avail=max(int(x["availability_time"]) for x in evidence)
    event=max(int(x.get("event_time",x["availability_time"])) for x in evidence)
    body={"setup_id":sid,"from_state":from_state,"to_state":to_state,"event_time":event,"availability_time":avail,
          "reason_code":reason_code,"evidence_ids":sorted(str(x["id"]) for x in evidence)}
    body["transition_id"]="g9t_"+stable(body);body["transition_hash"]=stable(body);return body
