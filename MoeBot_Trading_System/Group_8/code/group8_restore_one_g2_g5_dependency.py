#!/usr/bin/env python3
"""Restore one exact Group2-5 annual dependency from a Group8 upstream manifest."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--group',choices=('group2','group3','group4','group5'),required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    m=json.loads(a.manifest.read_text()); row=m['packages'][a.group]; out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    comp=out/row['compressed_filename']
    with comp.open('wb') as dst:
        for part in row['parts']:
            p=out/part['filename']; proc=subprocess.run(['curl','-L','--fail','--retry','5','--retry-all-errors',part['url'],'-o',str(p)],text=True,capture_output=True)
            if proc.returncode:raise RuntimeError(proc.stderr[-2000:])
            if p.stat().st_size!=int(part['size_bytes']) or sha(p)!=part['sha256']:raise RuntimeError(f'part mismatch {p.name}')
            with p.open('rb') as src:shutil.copyfileobj(src,dst,length=16*1024*1024)
            p.unlink()
    if comp.stat().st_size!=int(row['compressed_size_bytes']) or sha(comp)!=row['compressed_sha256']:raise RuntimeError('compressed mismatch')
    db=out/row['database_filename'];proc=subprocess.run(['zstd','-d','--long=31','-f',str(comp),'-o',str(db)],text=True,capture_output=True)
    if proc.returncode:raise RuntimeError(proc.stderr[-2000:])
    comp.unlink()
    if db.stat().st_size!=int(row['database_size_bytes']) or sha(db)!=row['database_sha256']:raise RuntimeError('database mismatch')
    print(json.dumps({'status':'PASS','group':a.group,'database':str(db),'size_bytes':db.stat().st_size,'sha256':sha(db)},indent=2))
if __name__=='__main__':main()
