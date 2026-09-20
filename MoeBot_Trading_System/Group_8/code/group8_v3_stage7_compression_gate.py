#!/usr/bin/env python3
"""Formal Stage 7 zstd storage gate over the measured premium/discount sample."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file


def _stream_sha(zstd: Path, archive: Path) -> str:
    h=hashlib.sha256()
    p=subprocess.Popen([str(zstd),"-d","-c",str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert p.stdout is not None
    for chunk in iter(lambda:p.stdout.read(1024*1024),b""): h.update(chunk)
    err=b"" if p.stderr is None else p.stderr.read()
    rc=p.wait()
    if rc: raise RuntimeError(f"zstd decompression failed rc={rc}:{err.decode(errors='replace')}")
    return h.hexdigest()


def run_gate(*,benchmark_report:Path,sample_db:Path,zstd_exe:Path,archive:Path,output:Path,level:int,safety_floor_gb:float)->dict[str,Any]:
    b=json.loads(benchmark_report.read_text())
    if b.get("status")!="PASS": raise RuntimeError("Stage 7 benchmark is not PASS")
    if not sample_db.is_file(): raise RuntimeError("benchmark sample DB missing")
    raw_sha=sha256_file(sample_db); raw_bytes=sample_db.stat().st_size
    archive.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(zstd_exe),f"-{level}","-f",str(sample_db),"-o",str(archive)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([str(zstd_exe),"-t",str(archive)],check=True,stdout=subprocess.DEVNULL)
    roundtrip=_stream_sha(zstd_exe,archive)
    if roundtrip!=raw_sha: raise RuntimeError("zstd round-trip SHA mismatch")
    compressed_bytes=archive.stat().st_size
    ratio=raw_bytes/compressed_bytes
    proj=b["projection"]
    conservative_raw=int(proj["projected_total_bytes_with_storage_safety_factor"])
    max_raw=int(proj["projected_max_range_chain_shard_bytes"])
    disk=shutil.disk_usage(sample_db.parent)
    floor=int(safety_floor_gb*(1024**3)); usable=max(int(disk.free)-floor,0)
    conservative_compressed=int(conservative_raw/ratio)
    projected_peak=conservative_compressed+max_raw
    required_ratio=(conservative_raw/max(usable-max_raw,1)) if usable>max_raw else float("inf")
    status="PASS" if projected_peak<=usable else "BLOCKED"
    r={
      "format_version":1,
      "scope":"GROUP8_V3_STAGE7_ZSTD_STORAGE_GATE",
      "status":status,
      "stage7_authorized":False,
      "full_annual_stage7_permitted":False,
      "stage7_benchmark_report_hash":b["report_hash"],
      "sample_raw_sha256":raw_sha,
      "sample_roundtrip_sha256":roundtrip,
      "sample_raw_bytes":raw_bytes,
      "sample_compressed_bytes":compressed_bytes,
      "measured_compression_ratio":ratio,
      "space_saved_fraction":1-(compressed_bytes/raw_bytes),
      "zstd_level":level,
      "archive_sha256":sha256_file(archive),
      "conservative_raw_projection_bytes":conservative_raw,
      "conservative_compressed_projection_bytes":conservative_compressed,
      "projected_max_raw_shard_bytes":max_raw,
      "projected_peak_bytes_compressed_plus_one_raw_shard":projected_peak,
      "current_drive_free_bytes":int(disk.free),
      "safety_floor_bytes":floor,
      "usable_new_output_bytes":usable,
      "required_compression_ratio_for_peak_gate":required_ratio,
      "lossless_roundtrip_verified":True,
      "storage_gate_pass":status=="PASS",
    }
    r["report_hash"]=stable_hash(r)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    return r


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--benchmark-report",type=Path,required=True);p.add_argument("--sample-db",type=Path,required=True)
    p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--level",type=int,default=6)
    p.add_argument("--safety-floor-gb",type=float,default=120.0)
    a=p.parse_args()
    r=run_gate(benchmark_report=a.benchmark_report.resolve(),sample_db=a.sample_db.resolve(),zstd_exe=a.zstd_exe.resolve(),archive=a.archive.resolve(),output=a.output.resolve(),level=a.level,safety_floor_gb=a.safety_floor_gb)
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__": raise SystemExit(main())
