#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,tempfile,unittest
from pathlib import Path
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_onepass_month_partition import run_onepass_bucket
from test_group8_engine_v0_8_0 import ART,make_stage


def pairs(db:Path,table:str,idc:str,hc:str):
 c=sqlite3.connect(db)
 try:return [(str(a),str(b)) for a,b in c.execute(f'SELECT {idc},{hc} FROM {table} ORDER BY {idc}')]
 finally:c.close()

class PA7OnePassMonthPartitionParity(unittest.TestCase):
 def test_all_month_partition_matches_twelve_independent_annual_shards(self):
  with tempfile.TemporaryDirectory() as td:
   t=Path(td);stage=t/'stage.sqlite';make_stage(stage);months=[f'2023-{m:02d}' for m in range(1,13)]
   for scope in ('upstream','group8_range'):
    out=t/f'one_{scope}';r=run_onepass_bucket(staging_db=stage,work_db=t/f'one_{scope}.work.sqlite',output_dir=out,artifacts_root=ART,year=2023,symbol='XAUUSD_',timeframe='M15',root_months=months,bucket_count=1,bucket_index=0,boundary_scope=scope);self.assertEqual(r['status'],'PASS');self.assertEqual(len(r['shards']),12)
    by_month={x['root_month']:x for x in r['shards']}
    for month in months:
     olddb=t/f'old_{scope}_{month}.sqlite';oldmp=t/f'old_{scope}_{month}.json';old=run_annual_pa7_shard(staging_db=stage,work_db=t/f'old_{scope}_{month}.work.sqlite',output_db=olddb,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',month,1,0),boundary_scope=scope,manifest_path=oldmp);new=by_month[month];newdb=Path(new['database']);newm=json.loads(Path(new['manifest']).read_text())
     self.assertEqual(newm['shard_id'],old['shard_id'],(scope,month,'shard_id'))
     self.assertEqual(newm['table_row_counts'],old['table_row_counts'],(scope,month,'counts'))
     self.assertEqual(newm['table_logical_sha256'],old['table_logical_sha256'],(scope,month,'logical'))
     self.assertEqual(newm['definition_coverage'],old['definition_coverage'],(scope,month,'defs'))
     self.assertEqual(newm['annual_breakout_followup_finalized'],True)
     self.assertEqual(pairs(newdb,'price_action_pattern_candidate','candidate_id','candidate_hash'),pairs(olddb,'price_action_pattern_candidate','candidate_id','candidate_hash'),(scope,month,'candidate_pairs'))
     self.assertEqual(pairs(newdb,'price_action_pattern_state','state_event_id','state_hash'),pairs(olddb,'price_action_pattern_state','state_event_id','state_hash'),(scope,month,'state_pairs'))

if __name__=='__main__':unittest.main()
