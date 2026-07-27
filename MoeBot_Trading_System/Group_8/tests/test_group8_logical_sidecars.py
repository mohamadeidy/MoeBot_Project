#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_pa7_shard_executor import ShardSpec,run_shard
from group8_shard_union_validator import validate
from group8_logical_sidecars import HEX,create_sidecars,merge_prefix,table_hash
from test_group8_engine_v0_8_0 import ART,make_stage

class DistributedFingerprintTest(unittest.TestCase):
 def test_exact_candidate_state_hashes_match_frozen_union_validator(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';make_stage(stage);pairs=[];side=[]
   for b in range(4):
    db=t/f's{b}.sqlite';mp=t/f'm{b}.json';run_shard(staging_db=stage,work_db=t/f'w{b}.sqlite',output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',None,4,b),manifest_path=mp);pairs.append({'database':str(db),'manifest':str(mp)});sd=t/f'side{b}';rep=create_sidecars([db],sd);self.assertEqual(rep['status'],'PASS');side.append(sd)
   idx=t/'index.json';idx.write_text(json.dumps({'year':2023,'symbol':'XAUUSD_','full_annual_union':False,'shards':pairs}));legacy=validate(idx,t/'legacy.json')
   for short,table in (('candidate','price_action_pattern_candidate'),('state','price_action_pattern_state')):
    merged=[]
    for p in HEX:
     out=t/f'{short}_{p}.canonical';r=merge_prefix([sd/f'{short}_{p}.pairs' for sd in side],out);self.assertEqual(r['status'],'PASS');merged.append(out)
    got=table_hash(merged);self.assertEqual(got['logical_sha256'],legacy['table_logical_sha256'][table]);self.assertEqual(sum(merge_prefix([sd/f'{short}_{p}.pairs' for sd in side],t/f'check_{short}_{p}')['row_count'] for p in HEX),legacy['table_row_counts'][table])
   # Duplicate shard inclusion must be rejected by exact prefix merge.
   nonempty=None
   for p in HEX:
    if (side[0]/f'candidate_{p}.pairs').stat().st_size:nonempty=p;break
   self.assertIsNotNone(nonempty)
   with self.assertRaisesRegex(RuntimeError,'duplicate domain ID across sidecars'):
    merge_prefix([side[0]/f'candidate_{nonempty}.pairs',side[0]/f'candidate_{nonempty}.pairs'],t/'dup')

if __name__=='__main__':unittest.main()
