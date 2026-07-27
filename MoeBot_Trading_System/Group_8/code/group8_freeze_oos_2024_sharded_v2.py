#!/usr/bin/env python3
"""Hardened OOS freeze entrypoint including all current FREE-sharded execution tools.

This does not alter the frozen OOS authorization semantics. It delegates to the
validated sharded freeze implementation after extending only its optional identity
list. Every listed tool that exists at freeze time becomes SHA/size-bound in the OOS
freeze manifest. This closes the governance gap created by post-refreeze physical
execution optimizations while remaining completely 2024-data-blind.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import group8_freeze_oos_2024_sharded as base

EXTRA_OPTIONAL_FROZEN_TOOLING=[
    'code/group8_freeze_oos_2024_sharded.py',
    'code/group8_freeze_oos_2024_sharded_v2.py',
    'code/group8_pa7_relevant_catalog.py',
    'code/group8_streaming_union_validator.py',
    'code/group8_logical_sidecars.py',
    'code/group8_distributed_union_validator.py',
    'code/group8_distributed_union_worker_aggregate.py',
    'code/group8_cross_shard_reference_audit.py',
    'code/group8_reconstruct_final_core.py',
    'code/group8_pa7_distributed_relevant_catalog.py',
    'code/group8_pa7_onepass_month_partition.py',
    'code/group8_segmented_annual_core.py',
]


def freeze(*,group8_root:Path,output:Path):
    old=list(base.OPTIONAL_FROZEN_TOOLING)
    try:
        merged=[]
        for rel in old+EXTRA_OPTIONAL_FROZEN_TOOLING:
            if rel not in merged:merged.append(rel)
        base.OPTIONAL_FROZEN_TOOLING[:]=merged
        manifest=base.freeze(group8_root=group8_root,output=output)
        present=[rel for rel in EXTRA_OPTIONAL_FROZEN_TOOLING if (group8_root/rel).is_file()]
        missing=[rel for rel in present if rel not in manifest.get('identities',{})]
        if missing:raise RuntimeError(f'oos_extra_tooling_not_frozen:{missing}')
        return manifest
    finally:
        base.OPTIONAL_FROZEN_TOOLING[:]=old


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();m=freeze(group8_root=a.group8_root.resolve(),output=a.output.resolve());print(json.dumps({'status':m['status'],'manifest_hash':m['manifest_hash'],'2024_oos_authorized':True,'extended_tooling_freeze':True},indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
