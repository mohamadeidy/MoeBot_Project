#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil
from pathlib import Path

GIB=1024**3
def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main()->int:
    p=argparse.ArgumentParser(description="Projection-only sizing gate for MoeBot Groups 9-15")
    p.add_argument("--group",type=int,choices=range(9,16),required=True)
    p.add_argument("--candidate-count",type=int,required=True)
    p.add_argument("--sample-count",type=int,required=True)
    p.add_argument("--sample-seconds",type=float,required=True)
    p.add_argument("--sample-output-bytes",type=int,required=True)
    p.add_argument("--sample-peak-bytes",type=int,required=True)
    p.add_argument("--probe-path",type=Path,required=True)
    p.add_argument("--floor-gib",type=float,default=120.0)
    p.add_argument("--soft-shard-bytes",type=int,default=1_500_000_000)
    p.add_argument("--hard-shard-bytes",type=int,default=2_500_000_000)
    p.add_argument("--target-hours",type=float,default=24.0)
    p.add_argument("--hard-hours",type=float,default=48.0)
    p.add_argument("--parallel-workers",type=int,default=1)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    if a.sample_count<=0 or a.candidate_count<0 or a.sample_seconds<0:
        raise SystemExit("invalid sizing inputs")
    scale=(a.candidate_count/a.sample_count) if a.sample_count else 0
    serial_seconds=a.sample_seconds*scale
    workers=max(1,a.parallel_workers)
    projected_seconds=serial_seconds/workers
    projected_output=int(math.ceil(a.sample_output_bytes*scale))
    projected_peak_worker=int(math.ceil(a.sample_peak_bytes))
    target_shards=max(1,math.ceil(projected_output/max(1,a.soft_shard_bytes))) if a.candidate_count else 1
    projected_peak_active=min(workers,target_shards)*min(projected_peak_worker,a.hard_shard_bytes)
    d=shutil.disk_usage(a.probe_path);floor=int(a.floor_gib*GIB);usable=max(int(d.free)-floor,0)
    hours=projected_seconds/3600.0
    gates={
      "sample_nonzero":a.sample_count>0,
      "hard_runtime_pass":hours<=a.hard_hours,
      "c_storage_pass":projected_peak_active<=usable,
      "per_worker_peak_pass":projected_peak_worker<=a.hard_shard_bytes
    }
    r={"format_version":1,"group":a.group,"status":"PASS" if all(gates.values()) else "BLOCKED",
       "candidate_count":a.candidate_count,"sample_count":a.sample_count,"scale_factor":scale,
       "parallel_workers":workers,"cpu_count":os.cpu_count(),"projected_runtime_seconds":projected_seconds,
       "projected_runtime_hours":hours,"target_runtime_hours":a.target_hours,"hard_runtime_hours":a.hard_hours,
       "runtime_target_met":hours<=a.target_hours,"projected_output_bytes":projected_output,
       "recommended_shard_count":target_shards,"projected_peak_active_bytes":projected_peak_active,
       "drive_free_bytes":int(d.free),"safety_floor_bytes":floor,"usable_bytes_above_floor":usable,
       "gates":gates}
    r["report_hash"]=stable(r)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    print(json.dumps(r,indent=2,sort_keys=True))
    return 0 if r["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
