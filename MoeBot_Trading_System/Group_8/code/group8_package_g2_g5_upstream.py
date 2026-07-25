#!/usr/bin/env python3
"""Package annual Group 2-5 SQLite dependencies as additive Data Vault assets."""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
from typing import Any
MAX_PART_BYTES=1_900_000_000;GROUPS=("group2","group3","group4","group5")
def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(16*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def canonical_json(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def split_file(source:Path,output_dir:Path)->list[dict[str,Any]]:
    parts=[]
    with source.open('rb') as src:
        i=0
        while True:
            chunk=src.read(MAX_PART_BYTES)
            if not chunk:break
            name=f'{source.name}.part-{i:03d}';path=output_dir/name;path.write_bytes(chunk);parts.append({'filename':name,'size_bytes':len(chunk),'sha256':hashlib.sha256(chunk).hexdigest()});i+=1
    if not parts:raise RuntimeError(f'no parts generated for {source}')
    return parts
def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,required=True,choices=(2023,2024));ap.add_argument('--pipeline-report',type=Path,required=True);ap.add_argument('--runtime-v2-v3-equivalence',type=Path,required=True);ap.add_argument('--published-g6-reference-compatibility',type=Path,required=True);ap.add_argument('--g6-v2-vs-published',type=Path,required=True);ap.add_argument('--g6-v3-vs-published',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--repository',required=True);ap.add_argument('--release-tag',required=True);args=ap.parse_args()
    pipeline=json.loads(args.pipeline_report.read_text());lineage=json.loads(args.runtime_v2_v3_equivalence.read_text());compat=json.loads(args.published_g6_reference_compatibility.read_text());g6v2=json.loads(args.g6_v2_vs_published.read_text());g6v3=json.loads(args.g6_v3_vs_published.read_text())
    if lineage.get('status')!='PASS':raise RuntimeError('v2-v3 runtime lineage equivalence must PASS before packaging')
    if compat.get('status')!='PASS':raise RuntimeError('published Group6 reference compatibility must PASS before packaging')
    if int(pipeline.get('year',-1))!=args.year:raise RuntimeError('pipeline report year mismatch')
    out=args.output_dir.resolve();shutil.rmtree(out,ignore_errors=True);out.mkdir(parents=True)
    packages={}
    for group in GROUPS:
        row=pipeline['artifacts'][group];db=Path(row['path']).resolve()
        if not db.is_file():raise FileNotFoundError(db)
        actual_size=db.stat().st_size;actual_sha=sha256_file(db)
        if actual_size!=int(row['size_bytes']) or actual_sha!=row['sha256']:raise RuntimeError(f'pipeline artifact identity drift for {group}')
        compressed=out/f'{db.name}.zst';proc=subprocess.run(['zstd','-q','-19','--long=31','-T0','-f',str(db),'-o',str(compressed)],text=True,capture_output=True)
        if proc.returncode:raise RuntimeError(f'zstd failed {group}: {proc.stderr}')
        csize=compressed.stat().st_size;csha=sha256_file(compressed);parts=split_file(compressed,out);compressed.unlink()
        for part in parts:part['url']=f"https://github.com/{args.repository}/releases/download/{args.release_tag}/{part['filename']}"
        packages[group]={'database_filename':db.name,'database_size_bytes':actual_size,'database_sha256':actual_sha,'compressed_filename':f'{db.name}.zst','compressed_size_bytes':csize,'compressed_sha256':csha,'compression':'zstd -19 --long=31','parts':parts,'sqlite_check':pipeline['sqlite_checks'][group]}
    report={'format_version':2,'status':'PASS_PACKAGED','lineage':'dukascopy_rebuild_v1','purpose':'Group 8 real annual upstream dependencies for frozen Groups 2-5','year':args.year,'repository':args.repository,'release_tag':args.release_tag,'source_sha256':pipeline['source_sha256'],'runtime_engines':pipeline['engines'],'runtime_v2_v3_equivalence':{'status':lineage['status'],'report_hash':lineage['report_hash']},'published_group6_reference_compatibility':{'status':compat['status'],'report_hash':compat['report_hash']},'rerun_vs_published_group6_diagnostics':{'v2':{'status':g6v2.get('status'),'report_hash':g6v2.get('report_hash'),'failures':g6v2.get('failures',[])},'v3':{'status':g6v3.get('status'),'report_hash':g6v3.get('report_hash'),'failures':g6v3.get('failures',[])}},'packages':packages}
    report['manifest_hash']=hashlib.sha256(canonical_json(report)).hexdigest();manifest=out/f'MoeBot_Group8_Upstream_G2-G5_{args.year}_manifest.json';manifest.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'manifest':manifest.name,'manifest_hash':report['manifest_hash']},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
