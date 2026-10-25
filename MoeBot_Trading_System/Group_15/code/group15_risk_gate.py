#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class DeploymentGate:
 group14_pass:bool
 demo_pass:bool
 def authorize(self,mode:str)->bool:
  if mode=="DEMO":return self.group14_pass
  if mode=="LIVE":return self.group14_pass and self.demo_pass
  return False
def reserve_risk(*,requested:float,open_reserved:float,account_equity:float,catastrophic_fraction:float)->dict:
 if min(requested,open_reserved,account_equity,catastrophic_fraction)<0:raise ValueError("negative risk input")
 ceiling=account_equity*catastrophic_fraction
 available=max(0.0,ceiling-open_reserved)
 if requested>available:raise ValueError("catastrophic risk ceiling exceeded")
 return {"requested_risk":requested,"open_reserved_before":open_reserved,"ceiling":ceiling,"available_before":available,"open_reserved_after":open_reserved+requested}
