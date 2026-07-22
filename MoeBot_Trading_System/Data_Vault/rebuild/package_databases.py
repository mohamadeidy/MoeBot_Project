#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

DEFAULT_PART_BYTES = 1_900 * 1024 * 1024


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(chunk_size): h.update(chunk)
    return h.hexdigest()


def compress_and_split(db: Path, output_dir: Path, part_bytes: int, base_url: str) -> dict:
    zstd=shutil.which('zstd')
    if not zstd: raise RuntimeError('zstd executable is required')
    compressed=output_dir/(db.name+'.zst')
    subprocess.run([zstd,'-19','--long=31','-T0','-f',str(db),'-o',str(compressed)],check=True)
    compressed_sha=sha256_file(compressed)
    parts=[]
    with compressed.open('rb') as src:
        index=0
        while True:
            data=src.read(part_bytes)
            if not data: break
            part=output_dir/f'{compressed.name}.part-{index:03d}'
            part.write_bytes(data)
            parts.append({'filename':part.name,'size_bytes':part.stat().st_size,'sha256':sha256_file(part),'url':f'{base_url}/{part.name}'})
            index+=1
    compressed_size=compressed.stat().st_size
    compressed.unlink()
    return {'database_filename':db.name,'database_size_bytes':db.stat().st_size,'database_sha256':sha256_file(db),
            'compression':'zstd -19 --long=31','compressed_filename':compressed.name,
            'compressed_size_bytes':compressed_size,'compressed_sha256':compressed_sha,'parts':parts}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--year',type=int,required=True,choices=(2023,2024)); ap.add_argument('--source',type=Path,required=True); ap.add_argument('--group6',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); ap.add_argument('--repository',default='mohamadeidy/MoeBot_Project'); ap.add_argument('--tag',default='moebot-sqlite-rebuild-v1'); ap.add_argument('--part-bytes',type=int,default=DEFAULT_PART_BYTES)
    a=ap.parse_args(); a.output_dir.mkdir(parents=True,exist_ok=True)
    base=f'https://github.com/{a.repository}/releases/download/{a.tag}'
    result={'format_version':1,'lineage':'dukascopy_rebuild_v1','year':a.year,'release_tag':a.tag,'repository':a.repository,
            'warning':'New validated rebuild lineage; not byte-identical to unavailable legacy Collector databases',
            'databases':{'source':compress_and_split(a.source,a.output_dir,a.part_bytes,base),'group6':compress_and_split(a.group6,a.output_dir,a.part_bytes,base)}}
    manifest=a.output_dir/f'moebot_sqlite_{a.year}_manifest.json'; manifest.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__': main()
