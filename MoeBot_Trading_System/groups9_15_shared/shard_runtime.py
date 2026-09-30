#!/usr/bin/env python3
"""Reusable lossless shard/runtime primitives for MoeBot Groups 9-15.

Physical-execution helpers only. No trading semantics live here.
"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess
from pathlib import Path
from typing import Any

GIB=1024**3
DEFAULT_C_FLOOR=120*GIB
SOFT_RAW=1_500_000_000
HARD_RAW=2_500_000_000

def canonical(v:Any)->bytes:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def stable_hash(v:Any)->str:
    return hashlib.sha256(canonical(v)).hexdigest()

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(16*1024*1024),b""):h.update(b)
    return h.hexdigest()

def atomic_json(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    t=path.with_suffix(path.suffix+".tmp")
    t.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(t,path)

def bucket_for_id(row_id:str,bucket_count:int)->int:
    if bucket_count<1:raise ValueError("bucket_count must be >=1")
    return int.from_bytes(hashlib.sha256(row_id.encode()).digest()[:8],"big")%bucket_count

def disk_gate(path:Path,projected_peak_bytes:int,safety_floor_bytes:int=DEFAULT_C_FLOOR)->dict[str,Any]:
    d=shutil.disk_usage(path)
    usable=max(int(d.free)-int(safety_floor_bytes),0)
    return {"pass":projected_peak_bytes<=usable,"free_bytes":int(d.free),"floor_bytes":int(safety_floor_bytes),
            "usable_bytes":usable,"projected_peak_bytes":int(projected_peak_bytes)}

def raw_shard_gate(size_bytes:int)->None:
    if int(size_bytes)>HARD_RAW:raise RuntimeError(f"raw shard hard guard exceeded:{size_bytes}>{HARD_RAW}")

def _stream_decompressed_sha(zstd:Path,archive:Path)->str:
    p=subprocess.Popen([str(zstd),"-d","-c",str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    h=hashlib.sha256();assert p.stdout is not None
    try:
        for b in iter(lambda:p.stdout.read(8*1024*1024),b""):h.update(b)
        err=b"" if p.stderr is None else p.stderr.read();rc=p.wait()
    finally:
        p.stdout.close()
        if p.stderr is not None:p.stderr.close()
    if rc:raise RuntimeError(f"zstd decompression failed:{err.decode(errors='replace')}")
    return h.hexdigest()

def compress_verified(*,raw:Path,archive:Path,zstd:Path,level:int=6,delete_raw:bool=True)->dict[str,Any]:
    raw_shard_gate(raw.stat().st_size)
    before=sha256_file(raw);archive.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(zstd),f"-{level}","-T0","-f",str(raw),"-o",str(archive)],check=True)
    subprocess.run([str(zstd),"-t",str(archive)],check=True)
    after=_stream_decompressed_sha(zstd,archive)
    if after!=before:raise RuntimeError("lossless roundtrip SHA mismatch")
    rec={"raw_sha256":before,"raw_size_bytes":raw.stat().st_size,"compressed_sha256":sha256_file(archive),
         "compressed_size_bytes":archive.stat().st_size,"lossless_roundtrip_verified":True}
    if delete_raw:raw.unlink()
    return rec

def vault_copy_verified(*,archive:Path,vault_root:Path,relative:Path)->Path:
    dst=vault_root/relative;dst.parent.mkdir(parents=True,exist_ok=True)
    expected=sha256_file(archive)
    shutil.copy2(archive,dst)
    if dst.stat().st_size!=archive.stat().st_size or sha256_file(dst)!=expected:
        dst.unlink(missing_ok=True);raise RuntimeError("vault copy identity mismatch")
    return dst

def verify_self_hash(record:dict[str,Any],field:str)->None:
    if field not in record:raise RuntimeError(f"missing {field}")
    x=dict(record);saved=str(x.pop(field))
    if stable_hash(x)!=saved:raise RuntimeError(f"{field} mismatch")
