#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

GIB=1024**3
def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--probe-path",type=Path,required=True)
    p.add_argument("--projected-peak-bytes",type=int,required=True)
    p.add_argument("--projected-runtime-seconds",type=float,required=True)
    p.add_argument("--max-raw-shard-bytes",type=int,required=True)
    p.add_argument("--safety-floor-gib",type=float,default=120)
    p.add_argument("--target-hours",type=float,default=24)
    p.add_argument("--hard-hours",type=float,default=48)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    d=shutil.disk_usage(a.probe_path)
    floor=int(a.safety_floor_gib*GIB);usable=max(int(d.free)-floor,0);runtime_h=a.projected_runtime_seconds/3600.0
    gates={"storage_pass":a.projected_peak_bytes<=usable,"hard_shard_guard_pass":a.max_raw_shard_bytes<=2_500_000_000,"hard_runtime_pass":runtime_h<=a.hard_hours}
    r={"format_version":1,"status":"PASS" if all(gates.values()) else "BLOCKED","gates":gates,"drive_total_bytes":int(d.total),"drive_free_bytes":int(d.free),"safety_floor_bytes":floor,"usable_bytes_above_floor":usable,"projected_peak_bytes":a.projected_peak_bytes,"projected_runtime_hours":runtime_h,"target_runtime_hours":a.target_hours,"hard_runtime_hours":a.hard_hours,"runtime_target_met":runtime_h<=a.target_hours,"max_raw_shard_bytes":a.max_raw_shard_bytes}
    r["report_hash"]=stable(r)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    print(json.dumps(r,indent=2,sort_keys=True))
    return 0 if r["status"]=="PASS" else 2

if __name__=="__main__":raise SystemExit(main())
