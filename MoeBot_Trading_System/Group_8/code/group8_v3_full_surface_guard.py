#!/usr/bin/env python3
"""Fail-closed proof gate for the complete frozen Group 8 logical annual surface."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash

REQUIRED_DOMAIN_TABLES=(
 "price_action_pattern_candidate","price_action_pattern_state","school_interpretation",
 "shared_evidence","conflicting_evidence","narrative_hypothesis","hypothesis_lifecycle_event",
 "multi_timeframe_context_relation","evidence_chain","invalidation_record",
)

def _verify(rec:dict[str,Any],field:str,label:str)->None:
 if field not in rec:raise RuntimeError(f"{label}:missing_{field}")
 x=dict(rec);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{label}:{field}_mismatch")

def _load(path:Path,field:str,label:str)->dict[str,Any]:
 r=json.loads(path.read_text());_verify(r,field,label);return r

def load_full_surface_receipt(path:Path,*,year:int,stage6_union_report_hash:str,stage7_union_report_hash:str)->dict[str,Any]:
 r=_load(path,"report_hash","full_surface_receipt");fail=[]
 if r.get("status")!="PASS_FULL_LOGICAL_SURFACE":fail.append("status")
 if r.get("group")!=8:fail.append("group")
 if int(r.get("year",0))!=int(year):fail.append("year")
 for k in ("complete_logical_annual_dataset","pa7_complete_once_only_coverage","full_annual_union"):
  if r.get(k) is not True:fail.append(k)
 for k in ("unresolved_group8_reference_count","duplicate_domain_id_count","registry_conflict_count"):
  if int(r.get(k,-1))!=0:fail.append(k)
 if r.get("free_only") is not True or r.get("paid_runner_used") is True or r.get("paid_service_used") is True:fail.append("free_only")
 if bool(r.get("oos_2024_accessed"))!=(int(year)==2024):fail.append("oos_flag")
 if len(list(r.get("reconstruction_report_hashes") or []))!=3:fail.append("reconstruction_receipts")
 if len(list(r.get("full_union_report_hashes") or []))!=3:fail.append("full_union_receipts")
 if len(str(r.get("binding_report_hash") or ""))!=64:fail.append("binding_report_hash")
 if r.get("stage6_union_report_hash")!=stage6_union_report_hash:fail.append("stage6_union_binding")
 if r.get("stage7_union_report_hash")!=stage7_union_report_hash:fail.append("stage7_union_binding")
 cov=r.get("domain_table_coverage")
 if not isinstance(cov,dict):fail.append("domain_table_coverage")
 else:
  for t in REQUIRED_DOMAIN_TABLES:
   if t not in cov or (cov.get(t) or {}).get("verified") is not True:fail.append("domain_table:"+t)
 if len(str(r.get("logical_fingerprint") or ""))!=64:fail.append("logical_fingerprint")
 if fail:raise RuntimeError("full_surface_receipt_invalid:"+";".join(sorted(set(fail))))
 return r

def build_receipt(*,year:int,stage6_union_path:Path,stage7_union_path:Path,pa7_release_path:Path,reconstruction_report_paths:list[Path],full_union_report_paths:list[Path],binding_report_path:Path,output:Path)->dict[str,Any]:
 oos=int(year)==2024
 s6=_load(stage6_union_path,"report_hash","stage6_union");s7=_load(stage7_union_path,"report_hash","stage7_union")
 pa7=_load(pa7_release_path,"report_hash","pa7_release");bind=_load(binding_report_path,"report_hash","v3_surface_binding")
 recs=[_load(p,"report_hash",f"reconstruction_{i}") for i,p in enumerate(reconstruction_report_paths)]
 unions=[_load(p,"report_hash",f"full_union_{i}") for i,p in enumerate(full_union_report_paths)]
 fail=[]
 if int(year) not in (2023,2024):fail.append("unsupported_year")
 if s6.get("status")!="PASS" or int(s6.get("stage",0))!=6 or int(s6.get("year",0))!=int(year):fail.append("stage6_union")
 if s7.get("status")!="PASS" or int(s7.get("stage",0))!=7 or int(s7.get("year",0))!=int(year):fail.append("stage7_union")
 if pa7.get("status")!="PASS" or int(pa7.get("year",0))!=int(year) or pa7.get("complete_once_only_coverage") is not True:fail.append("pa7_release")
 if pa7.get("free_only") is not True or pa7.get("paid_runner_used") is True or pa7.get("paid_service_used") is True:fail.append("pa7_free_only")
 if bool(pa7.get("oos_2024_accessed"))!=oos:fail.append("pa7_oos_flag")
 if bind.get("status")!="PASS" or int(bind.get("year",0))!=int(year):fail.append("binding_report")
 if bind.get("complete_logical_annual_dataset") is not True:fail.append("binding_complete_surface")
 if bind.get("stage6_union_report_hash")!=s6.get("report_hash"):fail.append("binding_stage6")
 if bind.get("stage7_union_report_hash")!=s7.get("report_hash"):fail.append("binding_stage7")
 if bind.get("pa7_release_report_hash")!=pa7.get("report_hash"):fail.append("binding_pa7")
 for k in ("unresolved_group8_reference_count","duplicate_domain_id_count","registry_conflict_count"):
  if int(bind.get(k,-1))!=0:fail.append("binding_"+k)
 if bind.get("free_only") is not True or bind.get("paid_runner_used") is True or bind.get("paid_service_used") is True:fail.append("binding_free_only")
 if bool(bind.get("oos_2024_accessed"))!=oos:fail.append("binding_oos")
 cov=bind.get("domain_table_coverage")
 if not isinstance(cov,dict):cov={};fail.append("binding_domain_table_coverage")
 for t in REQUIRED_DOMAIN_TABLES:
  if t not in cov or (cov.get(t) or {}).get("verified") is not True:fail.append("binding_table:"+t)
 if len(recs)!=3:fail.append("three_reconstructions_required")
 rh=[]
 for i,r in enumerate(recs):
  if r.get("status")!="PASS" or int(r.get("year",0))!=int(year):fail.append(f"reconstruction_{i}")
  if r.get("causality") not in ("PASS",True) or r.get("no_trading_outputs") is not True:fail.append(f"reconstruction_safety_{i}")
  if int(r.get("unresolved_group8_reference_count",0))!=0:fail.append(f"reconstruction_refs_{i}")
  if r.get("free_only") is not True or r.get("paid_runner_used") is True or r.get("paid_service_used") is True:fail.append(f"reconstruction_free_{i}")
  if bool(r.get("oos_2024_accessed"))!=oos:fail.append(f"reconstruction_oos_{i}")
  rh.append(r.get("logical_sha256"))
 if rh and (None in rh or len(set(rh))!=1):fail.append("reconstruction_logical_drift")
 if len(unions)!=3:fail.append("three_full_unions_required")
 uh=[]
 for i,r in enumerate(unions):
  if r.get("status")!="PASS" or int(r.get("year",0))!=int(year) or r.get("full_annual_union") is not True:fail.append(f"full_union_{i}")
  if int(r.get("unresolved_group8_reference_count",-1))!=0:fail.append(f"full_union_refs_{i}")
  if int(r.get("duplicate_domain_id_count",-1))!=0:fail.append(f"full_union_duplicates_{i}")
  if int(r.get("registry_conflict_count",-1))!=0:fail.append(f"full_union_registry_{i}")
  if r.get("free_only") is not True or r.get("paid_runner_used") is True or r.get("paid_service_used") is True:fail.append(f"full_union_free_{i}")
  if bool(r.get("oos_2024_accessed"))!=oos:fail.append(f"full_union_oos_{i}")
  uh.append(r.get("global_logical_sha256"))
 if uh and (None in uh or len(set(uh))!=1):fail.append("full_union_logical_drift")
 if bind.get("reconstruction_report_hashes")!=[r["report_hash"] for r in recs]:fail.append("binding_reconstruction_reports")
 if bind.get("full_union_report_hashes")!=[r["report_hash"] for r in unions]:fail.append("binding_full_union_reports")
 if bind.get("finalized_core_logical_sha256") and rh and bind.get("finalized_core_logical_sha256")!=rh[0]:fail.append("binding_reconstruction_logical")
 if bind.get("full_union_global_logical_sha256") and uh and bind.get("full_union_global_logical_sha256")!=uh[0]:fail.append("binding_full_union_logical")
 if fail:raise RuntimeError("full_surface_evidence_invalid:"+";".join(sorted(set(fail))))
 out={"format_version":1,"status":"PASS_FULL_LOGICAL_SURFACE","group":8,"year":int(year),"complete_logical_annual_dataset":True,
 "stage6_union_report_hash":s6["report_hash"],"stage7_union_report_hash":s7["report_hash"],"pa7_release_report_hash":pa7["report_hash"],
 "pa7_complete_once_only_coverage":True,"binding_report_hash":bind["report_hash"],"reconstruction_report_hashes":[r["report_hash"] for r in recs],
 "reconstruction_logical_sha256":rh[0],"full_union_report_hashes":[r["report_hash"] for r in unions],"full_annual_union":True,
 "logical_fingerprint":uh[0],"domain_table_coverage":cov,"unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,
 "registry_conflict_count":0,"free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":oos}
 out["report_hash"]=stable_hash(out);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");return out

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--year",type=int,required=True);p.add_argument("--stage6-union",type=Path,required=True);p.add_argument("--stage7-union",type=Path,required=True);p.add_argument("--pa7-release",type=Path,required=True);p.add_argument("--reconstruction-report",type=Path,action="append",required=True);p.add_argument("--full-union-report",type=Path,action="append",required=True);p.add_argument("--binding-report",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args();r=build_receipt(year=a.year,stage6_union_path=a.stage6_union.resolve(),stage7_union_path=a.stage7_union.resolve(),pa7_release_path=a.pa7_release.resolve(),reconstruction_report_paths=[x.resolve() for x in a.reconstruction_report],full_union_report_paths=[x.resolve() for x in a.full_union_report],binding_report_path=a.binding_report.resolve(),output=a.output.resolve());print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
