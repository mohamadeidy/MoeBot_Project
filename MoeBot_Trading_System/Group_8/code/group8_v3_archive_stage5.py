#!/usr/bin/env python3
"""Losslessly archive the immutable V3 Stage5 boundary after Annual 2023 PASS."""
from __future__ import annotations
import argparse,hashlib,json,subprocess
from pathlib import Path
from typing import Any
from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

def _stream_sha(zstd:Path,archive:Path)->str:
    h=hashlib.sha256();p=subprocess.Popen([str(zstd),"-d","-c",str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert p.stdout is not None
    try:
      for chunk in iter(lambda:p.stdout.read(8*1024*1024),b""):h.update(chunk)
      err=b"" if p.stderr is None else p.stderr.read();rc=p.wait()
    finally:
      p.stdout.close()
      if p.stderr is not None:p.stderr.close()
    if rc:raise RuntimeError(f"zstd streamed decompression failed:{err.decode(errors='replace')}")
    return h.hexdigest()

def archive_stage5(*,stage5_db:Path,annual_manifest:Path,zstd_exe:Path,archive:Path,report:Path,level:int,remove_raw:bool)->dict[str,Any]:
    m=json.loads(annual_manifest.read_text());x=dict(m);saved=x.pop("manifest_hash")
    if stable_hash(x)!=saved or m.get("status") not in {"ANNUAL_2023_PASS","ANNUAL_2024_OOS_PASS"}:raise RuntimeError("Annual manifest invalid")
    expected=m["stage5"]["sha256"];raw=sha256_file(stage5_db)
    if raw!=expected:raise RuntimeError("Stage5 SHA drift before archive")
    raw_bytes=stage5_db.stat().st_size;archive.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(zstd_exe),f"-{level}","-T0","-f",str(stage5_db),"-o",str(archive)],check=True)
    subprocess.run([str(zstd_exe),"-t",str(archive)],check=True)
    rt=_stream_sha(zstd_exe,archive)
    if rt!=raw:raise RuntimeError("Stage5 zstd roundtrip SHA mismatch")
    year=int(m.get("year",0))
    rec={"format_version":1,"scope":f"GROUP8_V3_STAGE5_{year}_ARCHIVE","status":"PASS","annual_manifest_hash":saved,"year":year,"raw_sha256":raw,"raw_size_bytes":raw_bytes,"archive_sha256":sha256_file(archive),"archive_size_bytes":archive.stat().st_size,"compression_ratio":raw_bytes/max(archive.stat().st_size,1),"zstd_level":level,"roundtrip_sha256":rt,"lossless_roundtrip_verified":True,"raw_deleted":False}
    if remove_raw:
      stage5_db.unlink();rec["raw_deleted"]=True
    rec["report_hash"]=stable_hash(rec);report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(rec,indent=2,sort_keys=True)+"\n");return rec

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--annual-manifest",type=Path,required=True);p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--archive",type=Path,required=True);p.add_argument("--report",type=Path,required=True);p.add_argument("--level",type=int,default=6);p.add_argument("--remove-raw",action="store_true")
    a=p.parse_args();r=archive_stage5(stage5_db=a.stage5_db.resolve(),annual_manifest=a.annual_manifest.resolve(),zstd_exe=a.zstd_exe.resolve(),archive=a.archive.resolve(),report=a.report.resolve(),level=a.level,remove_raw=a.remove_raw);print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
