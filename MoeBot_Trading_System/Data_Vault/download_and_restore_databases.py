#!/usr/bin/env python3
"""Download, verify, reassemble, decompress and validate public MoeBot SQLite release assets."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, time, urllib.error, urllib.request
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_URL='https://raw.githubusercontent.com/mohamadeidy/MoeBot_Project/main/MoeBot_Trading_System/Data_Vault/registry/DATABASE_REGISTRY.json'


def sha256_file(path:Path,chunk_size:int=8*1024*1024)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(chunk_size): h.update(chunk)
    return h.hexdigest()


def load_json(location:str)->dict[str,Any]:
    p=Path(location)
    if p.exists(): return json.loads(p.read_text(encoding='utf-8'))
    headers={'User-Agent':'MoeBot-Data-Vault-Restore/1.1'}
    token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token: headers['Authorization']=f'Bearer {token}'
    req=urllib.request.Request(location,headers=headers)
    with urllib.request.urlopen(req,timeout=180) as r: return json.loads(r.read())


def download(url:str,dest:Path,expected_sha:str,attempts:int=6)->None:
    if dest.exists() and sha256_file(dest)==expected_sha: return
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix(dest.suffix+'.tmp')
    headers={
        'User-Agent':'MoeBot-Data-Vault-Restore/1.1',
        'Accept':'application/octet-stream',
    }
    token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token: headers['Authorization']=f'Bearer {token}'
    last_error:Exception|None=None
    for attempt in range(1,attempts+1):
        tmp.unlink(missing_ok=True)
        try:
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=600) as response,tmp.open('wb') as out:
                shutil.copyfileobj(response,out,length=8*1024*1024)
            actual=sha256_file(tmp)
            if actual!=expected_sha:
                raise RuntimeError(f'Part checksum mismatch: expected={expected_sha}, actual={actual}, url={url}')
            tmp.replace(dest)
            return
        except (OSError,RuntimeError,urllib.error.URLError,urllib.error.HTTPError) as exc:
            last_error=exc
            tmp.unlink(missing_ok=True)
            if attempt==attempts: break
            delay=min(2**attempt,30)
            print(f'Download attempt {attempt}/{attempts} failed for {url}: {exc}; retrying in {delay}s',flush=True)
            time.sleep(delay)
    raise RuntimeError(f'Unable to download verified release asset after {attempts} attempts: {url}: {last_error}')


def sqlite_check(path:Path)->None:
    c=sqlite3.connect(f'file:{path}?mode=ro',uri=True); quick=c.execute('PRAGMA quick_check').fetchone()[0]; integrity=c.execute('PRAGMA integrity_check').fetchone()[0]; fk=c.execute('PRAGMA foreign_key_check').fetchall(); c.close()
    if quick!='ok' or integrity!='ok' or fk: raise RuntimeError(f'SQLite validation failed for {path}: quick={quick}, integrity={integrity}, fk={len(fk)}')


def restore(entry:dict[str,Any],download_dir:Path,output_dir:Path)->Path:
    part_paths=[]
    for part in entry['parts']:
        p=download_dir/part['filename']; download(part['url'],p,part['sha256']); part_paths.append(p)
    compressed=download_dir/entry['compressed_filename']
    with compressed.open('wb') as out:
        for p in part_paths:
            with p.open('rb') as src: shutil.copyfileobj(src,out,length=8*1024*1024)
    if compressed.stat().st_size!=entry['compressed_size_bytes'] or sha256_file(compressed)!=entry['compressed_sha256']: raise RuntimeError(f"Compressed checksum mismatch for {compressed}")
    zstd=shutil.which('zstd')
    if not zstd: raise RuntimeError('zstd executable is required')
    output_dir.mkdir(parents=True,exist_ok=True); db=output_dir/entry['database_filename']
    subprocess.run([zstd,'-d','-f',str(compressed),'-o',str(db)],check=True)
    if db.stat().st_size!=entry['database_size_bytes'] or sha256_file(db)!=entry['database_sha256']: raise RuntimeError(f'Database identity mismatch: {db}')
    sqlite_check(db); return db


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--registry',default=DEFAULT_REGISTRY_URL); ap.add_argument('--year',choices=('2023','2024','both'),default='both'); ap.add_argument('--download-dir',type=Path,default=Path('.moebot_downloads')); ap.add_argument('--output-dir',type=Path,default=Path('moebot_databases'))
    a=ap.parse_args(); reg=load_json(a.registry)
    if reg.get('status')!='published': raise SystemExit('Database registry is not published yet')
    years=('2023','2024') if a.year=='both' else (a.year,); restored={}
    for year in years:
        restored[year]={kind:str(restore(entry,a.download_dir/year,a.output_dir)) for kind,entry in reg['years'][year]['databases'].items()}
    print(json.dumps({'restored':restored},indent=2,sort_keys=True))
if __name__=='__main__': main()
