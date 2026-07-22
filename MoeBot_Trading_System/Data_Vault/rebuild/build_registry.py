#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--manifests-dir',type=Path,required=True); ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(); manifests=[]
    for path in sorted(a.manifests_dir.rglob('moebot_sqlite_*_manifest.json')):
        manifests.append(json.loads(path.read_text(encoding='utf-8')))
    years={str(m['year']):m for m in manifests}
    if set(years)!={'2023','2024'}: raise SystemExit(f'Expected 2023 and 2024 manifests, found {sorted(years)}')
    registry={'format_version':1,'status':'published','lineage':'dukascopy_rebuild_v1','public_repository':'mohamadeidy/MoeBot_Project','release_tag':'moebot-sqlite-rebuild-v1',
              'legacy_identity_notice':{'legacy_files_unavailable':True,'legacy_hashes_are_not_reused':True,'requires_group7_annual_revalidation':True},'years':years}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(registry,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(registry,indent=2,sort_keys=True))
if __name__=='__main__': main()
