#!/usr/bin/env python3
"""Representative Stage 7 school_core benchmark using the production shard executor."""
from __future__ import annotations
import argparse,json,shutil,sqlite3,time
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import epoch_month,stable_hash
from group8_v3_stage7_shard_executor import Stage7ShardSpec,compress_verified_shard,run_shard
from moebot_group8_engine_v0_8_0 import sha256_file

HARD_GUARD=2_500_000_000


def _windows(staging:Path,symbol:str)->dict[str,list[str]]:
    con=sqlite3.connect(f"file:{staging.resolve()}?mode=ro&immutable=1",uri=True)
    try:
        d:dict[str,set[str]]={}
        for tf,t in con.execute("SELECT timeframe,close_time FROM source__bars WHERE symbol=? ORDER BY timeframe,close_time",(symbol,)):
            d.setdefault(str(tf),set()).add(epoch_month(int(t)))
        return {tf:sorted(v) for tf,v in sorted(d.items())}
    finally: con.close()


def _sample_months(months:list[str],n:int)->list[str]:
    if not months or n<=0:return []
    if len(months)<=n:return months
    if n==1:return [months[len(months)//2]]
    idx=[round(i*(len(months)-1)/(n-1)) for i in range(n)]
    return [months[i] for i in sorted(set(idx))]


def run_benchmark(*,staging_db:Path,stage5_db:Path,preflight_report:Path,artifacts_root:Path,output_root:Path,zstd_exe:Path,output:Path,symbol:str,windows_per_timeframe:int,chunk_interpretations:int,runtime_safety_factor:float)->dict[str,Any]:
    pf=json.loads(preflight_report.read_text())
    if pf.get("status")!="PASS":raise RuntimeError("Stage 7 preflight not PASS")
    if sha256_file(stage5_db)!=pf["stage5_database_sha256"]:raise RuntimeError("Stage5 hash drift")
    windows=_windows(staging_db,symbol)
    selected=[(tf,m) for tf,months in windows.items() for m in _sample_months(months,windows_per_timeframe)]
    if not selected:raise RuntimeError("no representative school_core windows")

    shards=[]
    raw_total=compressed_total=interp_total=evidence_total=0
    elapsed_total=0.0
    max_raw=0
    for tf,month in selected:
        stem=f"school_core_{tf}_{month}"
        db=output_root/"raw"/f"{stem}.sqlite"
        cp=output_root/"checkpoints"/f"{stem}.json"
        mf=output_root/"manifests"/f"{stem}.json"
        zst=output_root/"compressed"/f"{stem}.sqlite.zst"
        for p in (db,cp,mf,zst):
            p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists():p.unlink()
        spec=Stage7ShardSpec("school_core",2023,symbol,tf,month,1,0)
        t=time.monotonic()
        m=run_shard(staging_db=staging_db,stage5_db=stage5_db,output_db=db,checkpoint_path=cp,manifest_path=mf,artifacts_root=artifacts_root,spec=spec,chunk_interpretations=chunk_interpretations,hard_guard_bytes=HARD_GUARD,stage6_release_hash=pf["stage6_release_hash"],stage6_union_report_hash=pf["stage6_union_report_hash"])
        elapsed=time.monotonic()-t
        if m.get("status")!="PASS":raise RuntimeError(f"school_core sample shard not PASS:{tf}:{month}")
        raw=int(m["file_size_bytes"]);max_raw=max(max_raw,raw)
        c=compress_verified_shard(database=db,manifest_path=mf,archive=zst,zstd_exe=zstd_exe,level=6,remove_raw=True)
        inter=int(c["table_row_counts"]["school_interpretation"]);ev=int(c["table_row_counts"]["evidence_chain"])
        raw_total+=raw;compressed_total+=int(c["compressed_size_bytes"]);interp_total+=inter;evidence_total+=ev;elapsed_total+=elapsed
        shards.append({"timeframe":tf,"root_month":month,"interpretations":inter,"evidence_chain_rows":ev,"raw_bytes":raw,"compressed_bytes":int(c["compressed_size_bytes"]),"compression_ratio":raw/max(int(c["compressed_size_bytes"]),1),"elapsed_seconds":elapsed,"manifest_hash":c["manifest_hash"]})
    logical=interp_total+evidence_total
    counts=pf["definition_cardinality_current_engine"]
    full_interps=sum(int(counts[k]) for k in counts if k!="ict_premium_discount_context")
    full_evidence=3*int(counts["ict_liquidity_sweep_displacement"])+2*int(counts["ict_mss_fvg_delivery"])+2*int(counts["ict_return_to_imbalance_fvg_ce_current_engine"])+2*int(counts["ict_block_delivery_context"])+3*int(counts["ict_draw_on_liquidity_context"])
    full_logical=full_interps+full_evidence
    bytes_per_logical=raw_total/max(logical,1)
    compressed_per_logical=compressed_total/max(logical,1)
    seconds_per_interp=elapsed_total/max(interp_total,1)
    r={
      "format_version":1,"scope":"GROUP8_V3_STAGE7_SCHOOL_CORE_REPRESENTATIVE_BENCHMARK","status":"PASS",
      "stage7_authorized":False,"full_annual_stage7_permitted":False,
      "stage5_database_sha256":pf["stage5_database_sha256"],"stage7_preflight_report_hash":pf["report_hash"],
      "selected_windows":len(selected),"windows_per_timeframe":windows_per_timeframe,"shards":shards,
      "sample":{"interpretations":interp_total,"evidence_chain_rows":evidence_total,"logical_rows":logical,"raw_bytes":raw_total,"compressed_bytes":compressed_total,"compression_ratio":raw_total/max(compressed_total,1),"elapsed_seconds":elapsed_total,"bytes_per_logical_row":bytes_per_logical,"compressed_bytes_per_logical_row":compressed_per_logical,"seconds_per_interpretation":seconds_per_interp,"max_raw_shard_bytes":max_raw},
      "projection":{"full_school_core_interpretations":full_interps,"full_school_core_evidence_chain_rows":full_evidence,"full_school_core_logical_rows":full_logical,"projected_raw_bytes":int(full_logical*bytes_per_logical),"projected_compressed_bytes":int(full_logical*compressed_per_logical),"projected_runtime_seconds_with_safety_factor":seconds_per_interp*full_interps*runtime_safety_factor,"runtime_safety_factor":runtime_safety_factor,"hard_guard_bytes":HARD_GUARD},
      "next_gate":"freeze Stage 7 annual shard plan; annual execution remains blocked until plan/CI gate PASS",
    }
    r["report_hash"]=stable_hash(r)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    return r


def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--preflight-report",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True);p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--symbol",required=True);p.add_argument("--windows-per-timeframe",type=int,default=2);p.add_argument("--chunk-interpretations",type=int,default=5000);p.add_argument("--runtime-safety-factor",type=float,default=1.5)
    a=p.parse_args();r=run_benchmark(staging_db=a.staging_db.resolve(),stage5_db=a.stage5_db.resolve(),preflight_report=a.preflight_report.resolve(),artifacts_root=a.artifacts_root.resolve(),output_root=a.output_root.resolve(),zstd_exe=a.zstd_exe.resolve(),output=a.output.resolve(),symbol=a.symbol,windows_per_timeframe=a.windows_per_timeframe,chunk_interpretations=a.chunk_interpretations,runtime_safety_factor=a.runtime_safety_factor)
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
