#!/usr/bin/env python3
"""Build a fail-closed evidence binding for the complete V3 Group 8 annual surface.

This receipt does not create domain rows. It proves that the verified V3 Stage6/7
base core, PA7 query catalog, three deterministic finalized-core reconstructions,
and three full distributed unions all refer to the same immutable logical dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from group8_shard_union_validator import DOMAIN_TABLES
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

REQUIRED_DOMAIN_TABLES=tuple(DOMAIN_TABLES)


def _verify(rec:dict[str,Any],field:str,label:str)->None:
    if field not in rec:
        raise RuntimeError(f"{label}:missing_{field}")
    payload=dict(rec);saved=str(payload.pop(field))
    if stable_hash(payload)!=saved:
        raise RuntimeError(f"{label}:{field}_mismatch")


def _load(path:Path,field:str,label:str)->dict[str,Any]:
    rec=json.loads(path.read_text())
    _verify(rec,field,label)
    return rec


def _catalog_identity(path:Path)->dict[str,Any]:
    con=sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1",uri=True)
    try:
        if con.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise RuntimeError("PA7 catalog quick_check failed")
        if con.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise RuntimeError("PA7 catalog integrity_check failed")
        tables={str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "pa7_candidate_catalog" not in tables:
            raise RuntimeError("PA7 catalog missing pa7_candidate_catalog")
        h=hashlib.sha256();count=0
        for cid,ch in con.execute("SELECT candidate_id,candidate_hash FROM pa7_candidate_catalog ORDER BY candidate_id"):
            h.update(str(cid).encode());h.update(b"\0");h.update(str(ch).encode());h.update(b"\n");count+=1
    finally:
        con.close()
    return {
        "database_sha256":sha256_file(path),
        "database_size_bytes":path.stat().st_size,
        "candidate_rows":count,
        "logical_candidate_sha256":h.hexdigest(),
    }


def build_binding(
    *,
    year:int,
    stage6_union_path:Path,
    stage7_union_path:Path,
    base_core_report_path:Path,
    pa7_release_path:Path,
    pa7_catalog_path:Path,
    pa7_catalog_report_path:Path,
    reconstruction_report_paths:list[Path],
    full_union_report_paths:list[Path],
    output:Path,
)->dict[str,Any]:
    oos=int(year)==2024
    s6=_load(stage6_union_path,"report_hash","stage6_union")
    s7=_load(stage7_union_path,"report_hash","stage7_union")
    base=_load(base_core_report_path,"report_hash","base_core")
    pa7=_load(pa7_release_path,"report_hash","pa7_release")
    catrep=_load(pa7_catalog_report_path,"report_hash","pa7_catalog")
    recs=[_load(p,"report_hash",f"reconstruction_{i}") for i,p in enumerate(reconstruction_report_paths)]
    unions=[_load(p,"report_hash",f"full_union_{i}") for i,p in enumerate(full_union_report_paths)]
    cat=_catalog_identity(pa7_catalog_path)

    fail:list[str]=[]
    if int(year) not in (2023,2024):fail.append("unsupported_year")
    if s6.get("status")!="PASS" or int(s6.get("year",0))!=int(year) or int(s6.get("stage",0))!=6:fail.append("stage6_union")
    if s7.get("status")!="PASS" or int(s7.get("year",0))!=int(year) or int(s7.get("stage",0))!=7:fail.append("stage7_union")
    if base.get("status")!="PASS" or int(base.get("year",0))!=int(year):fail.append("base_core")
    if base.get("stage6_union_report_hash")!=s6.get("report_hash"):fail.append("base_stage6_binding")
    if base.get("stage7_union_report_hash")!=s7.get("report_hash"):fail.append("base_stage7_binding")
    if (base.get("storage_preflight") or {}).get("storage_gate_pass") is not True:fail.append("base_storage_gate")
    if pa7.get("status")!="PASS" or int(pa7.get("year",0))!=int(year) or pa7.get("complete_once_only_coverage") is not True:fail.append("pa7_release")
    if pa7.get("free_only") is not True or pa7.get("paid_runner_used") is True or pa7.get("paid_service_used") is True:fail.append("pa7_free_only")
    if bool(pa7.get("oos_2024_accessed"))!=oos:fail.append("pa7_oos_flag")
    if catrep.get("status")!="PASS":fail.append("pa7_catalog_report")
    if int(catrep.get("candidate_rows",-1))!=int(cat["candidate_rows"]):fail.append("pa7_catalog_count")
    if catrep.get("logical_candidate_sha256")!=cat["logical_candidate_sha256"]:fail.append("pa7_catalog_logical_hash")
    for field in ("source_shard_count","pass1_shard_count","pass2_shard_count"):
        if catrep.get(field) is not None and int(catrep[field])!=int(pa7.get("shard_count",-1)):
            fail.append("pa7_catalog_"+field)

    if len(recs)!=3:fail.append("three_reconstructions_required")
    rec_logical:list[str|None]=[]
    for i,r in enumerate(recs):
        if r.get("status")!="PASS" or int(r.get("year",0))!=int(year):fail.append(f"reconstruction_{i}")
        if r.get("base_core_database_sha256")!=base.get("database_sha256"):fail.append(f"reconstruction_base_{i}")
        if r.get("pa7_catalog_sha256")!=cat["database_sha256"]:fail.append(f"reconstruction_catalog_{i}")
        if r.get("causality") not in ("PASS",True) or r.get("no_trading_outputs") is not True:fail.append(f"reconstruction_safety_{i}")
        if int(r.get("unresolved_group8_reference_count",-1))!=0:fail.append(f"reconstruction_refs_{i}")
        if r.get("free_only") is not True or r.get("paid_runner_used") is True or r.get("paid_service_used") is True:fail.append(f"reconstruction_free_{i}")
        if bool(r.get("oos_2024_accessed"))!=oos:fail.append(f"reconstruction_oos_{i}")
        rec_logical.append(r.get("logical_sha256"))
    if rec_logical and (None in rec_logical or len(set(rec_logical))!=1):fail.append("reconstruction_logical_drift")

    if len(unions)!=3:fail.append("three_full_unions_required")
    union_logical:list[str|None]=[]
    first_counts:dict[str,Any]|None=None
    first_hashes:dict[str,Any]|None=None
    for i,u in enumerate(unions):
        if u.get("status")!="PASS" or int(u.get("year",0))!=int(year) or u.get("full_annual_union") is not True:fail.append(f"full_union_{i}")
        if u.get("pa7_release_report_hash")!=pa7.get("report_hash"):fail.append(f"full_union_pa7_{i}")
        if i<len(recs) and u.get("finalized_core_database_sha256")!=recs[i].get("database_sha256"):fail.append(f"full_union_core_{i}")
        if i<len(recs) and u.get("core_reference_report_hash")!=recs[i].get("cross_shard_reference_report_hash"):fail.append(f"full_union_refs_binding_{i}")
        if int(u.get("unresolved_group8_reference_count",-1))!=0:fail.append(f"full_union_refs_{i}")
        if int(u.get("duplicate_domain_id_count",-1))!=0:fail.append(f"full_union_duplicates_{i}")
        if int(u.get("registry_conflict_count",-1))!=0:fail.append(f"full_union_registry_{i}")
        if u.get("free_only") is not True or u.get("paid_runner_used") is True or u.get("paid_service_used") is True:fail.append(f"full_union_free_{i}")
        if bool(u.get("oos_2024_accessed"))!=oos:fail.append(f"full_union_oos_{i}")
        union_logical.append(u.get("global_logical_sha256"))
        counts=dict(u.get("table_row_counts") or {});hashes=dict(u.get("table_logical_sha256") or {})
        if first_counts is None:first_counts=counts;first_hashes=hashes
        elif counts!=first_counts or hashes!=first_hashes:fail.append("full_union_table_drift")
    if union_logical and (None in union_logical or len(set(union_logical))!=1):fail.append("full_union_logical_drift")

    coverage:dict[str,Any]={}
    counts=first_counts or {};hashes=first_hashes or {}
    for table in REQUIRED_DOMAIN_TABLES:
        count=counts.get(table);logical=hashes.get(table)
        verified=count is not None and logical is not None and len(str(logical))==64
        coverage[table]={"verified":bool(verified),"row_count":None if count is None else int(count),"logical_sha256":logical}
        if not verified:fail.append("domain_table:"+table)

    if fail:
        raise RuntimeError("v3_surface_binding_invalid:"+";".join(sorted(set(fail))))

    out={
        "format_version":1,"status":"PASS","scope":"GROUP8_V3_FULL_SURFACE_BINDING","group":8,"year":int(year),
        "stage6_union_report_hash":s6["report_hash"],"stage7_union_report_hash":s7["report_hash"],
        "base_core_report_hash":base["report_hash"],"base_core_database_sha256":base["database_sha256"],
        "pa7_release_report_hash":pa7["report_hash"],"pa7_catalog_report_hash":catrep["report_hash"],
        "pa7_catalog_sha256":cat["database_sha256"],"pa7_catalog_logical_sha256":cat["logical_candidate_sha256"],
        "reconstruction_report_hashes":[r["report_hash"] for r in recs],
        "finalized_core_logical_sha256":rec_logical[0],
        "full_union_report_hashes":[u["report_hash"] for u in unions],
        "full_union_global_logical_sha256":union_logical[0],
        "domain_table_coverage":coverage,"complete_logical_annual_dataset":True,
        "unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,"registry_conflict_count":0,
        "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":oos,
    }
    out["report_hash"]=stable_hash(out)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    return out


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--stage6-union",type=Path,required=True)
    p.add_argument("--stage7-union",type=Path,required=True)
    p.add_argument("--base-core-report",type=Path,required=True)
    p.add_argument("--pa7-release",type=Path,required=True)
    p.add_argument("--pa7-catalog",type=Path,required=True)
    p.add_argument("--pa7-catalog-report",type=Path,required=True)
    p.add_argument("--reconstruction-report",type=Path,action="append",required=True)
    p.add_argument("--full-union-report",type=Path,action="append",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    r=build_binding(
        year=a.year,stage6_union_path=a.stage6_union.resolve(),stage7_union_path=a.stage7_union.resolve(),
        base_core_report_path=a.base_core_report.resolve(),pa7_release_path=a.pa7_release.resolve(),
        pa7_catalog_path=a.pa7_catalog.resolve(),pa7_catalog_report_path=a.pa7_catalog_report.resolve(),
        reconstruction_report_paths=[x.resolve() for x in a.reconstruction_report],
        full_union_report_paths=[x.resolve() for x in a.full_union_report],output=a.output.resolve(),
    )
    print(json.dumps(r,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
