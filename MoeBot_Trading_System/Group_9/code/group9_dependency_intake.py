#!/usr/bin/env python3
"""Fast fail-closed intake gate for real Group 9 work.

This verifies the final Group 8 V3 closure chain, Checkpoint 3, frozen Group 9
semantics, Stage5 archive proofs, Stage6/7 releases, and scratch capacity.
It does not read outcome data and does not start annual materialization.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
from typing import Any

GIB=1024**3

def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def load_hashed(path:Path, fields=("manifest_hash","report_hash","release_hash","registry_hash","closure_hash"))->dict[str,Any]:
    r=json.loads(path.read_text())
    for f in fields:
        if f in r:
            x=dict(r);saved=str(x.pop(f))
            if stable(x)!=saved: raise RuntimeError(f"{path.name}:{f}_mismatch")
            return r
    raise RuntimeError(f"{path.name}:no_self_hash")

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--closure",type=Path,required=True)
    p.add_argument("--handoff",type=Path,required=True)
    p.add_argument("--checkpoint3",type=Path,required=True)
    p.add_argument("--g9-definitions",type=Path,required=True)
    p.add_argument("--g9-adapter",type=Path,required=True)
    p.add_argument("--g8-definitions",type=Path,required=True)
    p.add_argument("--stage5-archive-report",type=Path,action="append",required=True)
    p.add_argument("--stage5-archive",type=Path,action="append",required=True)
    p.add_argument("--stage6-release",type=Path,action="append",required=True)
    p.add_argument("--stage7-release",type=Path,action="append",required=True)
    p.add_argument("--scratch-root",type=Path,required=True)
    p.add_argument("--scratch-reserve-gib",type=float,default=20.0)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()

    failures=[]
    closure=load_hashed(a.closure)
    handoff=load_hashed(a.handoff)
    cp=load_hashed(a.checkpoint3)
    g9=load_hashed(a.g9_definitions)
    g8=load_hashed(a.g8_definitions)
    adapter=json.loads(a.g9_adapter.read_text())

    if closure.get("status")!="OFFICIALLY_CLOSED_V3" or closure.get("officially_closed") is not True: failures.append("group8_closure")
    if closure.get("group9_authorized") is not True: failures.append("group8_did_not_authorize_group9")
    if handoff.get("status")!="FROZEN_HANDOFF" or handoff.get("closure_hash")!=closure.get("closure_hash"): failures.append("group8_handoff")
    if cp.get("status")!="PASS" or cp.get("checkpoint") not in (3,"3","CHECKPOINT_3"): failures.append("checkpoint3")
    if cp.get("group8_closure_hash")!=closure.get("closure_hash"): failures.append("checkpoint3_closure_lineage")
    if cp.get("group8_handoff_manifest_hash")!=handoff.get("manifest_hash"): failures.append("checkpoint3_handoff_lineage")
    if g9.get("status")!="FROZEN" or g9.get("frozen_without_outcome_tuning") is not True: failures.append("group9_semantics_not_frozen")
    if g9.get("source_group8_definition_registry_hash")!=g8.get("registry_hash"): failures.append("group8_definition_identity_drift")
    if adapter.get("status")!="FROZEN" or adapter.get("source_definition_registry_hash")!=g8.get("registry_hash"): failures.append("adapter_not_frozen")

    if len(a.stage5_archive_report)!=len(a.stage5_archive): failures.append("stage5_archive_argument_count")
    archive_rows=[]
    max_raw=0
    if not failures:
        for rp,ap in zip(a.stage5_archive_report,a.stage5_archive):
            r=load_hashed(rp)
            if r.get("status")!="PASS" or r.get("lossless_roundtrip_verified") is not True or r.get("raw_deleted") is not True:
                failures.append(f"stage5_archive_report_{r.get('year')}")
                continue
            if not ap.is_file() or ap.stat().st_size!=int(r.get("archive_size_bytes",-1)):
                failures.append(f"stage5_archive_file_{r.get('year')}")
                continue
            max_raw=max(max_raw,int(r["raw_size_bytes"]))
            archive_rows.append({"year":int(r["year"]),"raw_size_bytes":int(r["raw_size_bytes"]),"archive_size_bytes":int(r["archive_size_bytes"]),"raw_sha256":r["raw_sha256"],"archive_sha256":r["archive_sha256"],"path":str(ap.resolve())})

    s6=[]
    for rp in a.stage6_release:
        r=load_hashed(rp)
        if r.get("status")!="PASS" or int(r.get("stage",0))!=6: failures.append(f"stage6_release_{r.get('year')}")
        s6.append({"year":int(r.get("year",0)),"release_hash":r.get("release_hash"),"shard_count":int(r.get("shard_count",0))})
    s7=[]
    for rp in a.stage7_release:
        r=load_hashed(rp)
        if r.get("status")!="PASS" or int(r.get("stage",0))!=7: failures.append(f"stage7_release_{r.get('year')}")
        school=sum(1 for x in r.get("shards",[]) if (x.get("spec") or {}).get("family")=="school_core")
        s7.append({"year":int(r.get("year",0)),"release_hash":r.get("release_hash"),"shard_count":int(r.get("shard_count",0)),"school_core_shards":school})

    a.scratch_root.mkdir(parents=True,exist_ok=True)
    du=shutil.disk_usage(a.scratch_root)
    reserve=int(a.scratch_reserve_gib*GIB)
    required=max_raw+reserve
    scratch_pass=int(du.free)>=required
    if not scratch_pass: failures.append("scratch_capacity_for_largest_stage5_restore")

    out={
      "format_version":1,"group":9,"status":"PASS" if not failures else "BLOCKED",
      "failures":sorted(set(failures)),
      "dependency_intake_authorized":not failures,
      "real_annual_materialization_authorized":False,
      "semantic_definition_version":g9.get("definition_version"),
      "semantic_registry_hash":g9.get("registry_hash"),
      "group8_closure_hash":closure.get("closure_hash"),
      "checkpoint3_report_hash":cp.get("report_hash"),
      "group8_handoff_manifest_hash":handoff.get("manifest_hash"),
      "stage5_archives":archive_rows,
      "stage6_releases":s6,"stage7_releases":s7,
      "scratch":{"path":str(a.scratch_root.resolve()),"free_bytes":int(du.free),"largest_stage5_raw_bytes":max_raw,"reserve_bytes":reserve,"required_bytes":required,"pass":scratch_pass},
      "next_gate":"exact root inventory + representative extraction benchmark + sizing/resource PASS"
    }
    out["report_hash"]=stable(out)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps(out,indent=2,sort_keys=True))
    return 0 if out["status"]=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
