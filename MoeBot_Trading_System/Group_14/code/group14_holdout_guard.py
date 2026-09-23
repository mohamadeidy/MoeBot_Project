#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
def sha(path:Path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def verify_holdout(*,plan:dict,dataset:Path,policy_hash:str)->dict:
 if plan.get("status")!="FROZEN" or plan.get("untouched") is not True:raise ValueError("holdout plan not frozen untouched")
 if str(plan.get("policy_hash"))!=policy_hash:raise ValueError("policy hash mismatch")
 expected=str(plan.get("dataset_sha256",""))
 actual=sha(dataset)
 if not expected or actual!=expected:raise ValueError("holdout dataset identity mismatch")
 return {"status":"PASS","dataset_sha256":actual,"policy_hash":policy_hash,"untouched":True}
