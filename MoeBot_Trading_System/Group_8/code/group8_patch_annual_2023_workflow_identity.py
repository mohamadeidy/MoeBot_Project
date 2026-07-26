#!/usr/bin/env python3
"""Patch the Group 8 annual-2023 workflow to the re-frozen technical identity.

Fail closed: only the previously frozen engine SHA is accepted as the source
state, and the replacement pins both the corrected engine and strengthened
annual-validator identities from the new ENGINE_BUILD_MANIFEST.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OLD_ENGINE="10350f255f8853f9e4baa7a955403e914f24e75281c3b4b9d4f2b63b932d8c7f"
NEW_ENGINE="61aa4cb2328b3424008703392501d94d7cbaf5733944e55ae0e45db7926191e8"
NEW_ANNUAL_VALIDATOR="0521d536d575e756be815b3d23a6313ceeee2e0f5a464357aecf19dcabb2c293"


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--repo-root',type=Path,required=True);a=p.parse_args();root=a.repo_root.resolve()
    wf=root/'.github/workflows/moebot-group8-annual-2023-validation.yml'
    build_path=root/'MoeBot_Trading_System/Group_8/ENGINE_BUILD_MANIFEST.json'
    build=json.loads(build_path.read_text())
    if build.get('status')!='TECHNICAL_CANDIDATE_PASS' or build.get('format_version')!=2:raise SystemExit('technical build is not the expected re-frozen candidate')
    if build.get('identities',{}).get('engine',{}).get('sha256')!=NEW_ENGINE:raise SystemExit('new engine manifest identity mismatch')
    if build.get('identities',{}).get('annual_validator',{}).get('sha256')!=NEW_ANNUAL_VALIDATOR:raise SystemExit('new annual-validator manifest identity mismatch')
    text=wf.read_text()
    old=f'''          if build.get("identities",{{}}).get("engine",{{}}).get("sha256")!="{OLD_ENGINE}": raise SystemExit("unexpected engine identity")\n'''
    new=f'''          if build.get("identities",{{}}).get("engine",{{}}).get("sha256")!="{NEW_ENGINE}": raise SystemExit("unexpected engine identity")\n          if build.get("identities",{{}}).get("annual_validator",{{}}).get("sha256")!="{NEW_ANNUAL_VALIDATOR}": raise SystemExit("unexpected annual-validator identity")\n'''
    if text.count(old)!=1:raise SystemExit(f'authoritative old engine anchor count={text.count(old)}')
    if NEW_ENGINE in text or NEW_ANNUAL_VALIDATOR in text:raise SystemExit('new identity already present before patch')
    text=text.replace(old,new,1)
    if OLD_ENGINE in text:raise SystemExit('old engine identity remains after patch')
    if text.count(NEW_ENGINE)!=1 or text.count(NEW_ANNUAL_VALIDATOR)!=1:raise SystemExit('new identity multiplicity invalid')
    wf.write_text(text)
    print(json.dumps({'status':'PASS','workflow':str(wf.relative_to(root)),'engine_sha256':NEW_ENGINE,'annual_validator_sha256':NEW_ANNUAL_VALIDATOR},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
