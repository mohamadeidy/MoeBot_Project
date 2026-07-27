#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_pa7_shard_executor import ShardSpec,run_shard
from group8_shard_union_validator import validate
from group8_streaming_union_validator import init_ledger,append_shard,finalize
from test_group8_engine_v0_8_0 import ART,make_stage

class StreamingUnionValidatorTest(unittest.TestCase):
    def test_streaming_union_matches_existing_validator_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);pairs=[]
            for b in range(4):
                work=t/f'w{b}.sqlite';db=t/f's{b}.sqlite';mp=t/f'm{b}.json';run_shard(staging_db=stage,work_db=work,output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',None,4,b),manifest_path=mp);pairs.append((db,mp))
            idx=t/'index.json';idx.write_text(json.dumps({'year':2023,'symbol':'XAUUSD_','full_annual_union':False,'shards':[{'database':str(d),'manifest':str(m)} for d,m in pairs]}));legacy=validate(idx,t/'legacy.json')
            ledger=t/'ledger.sqlite';init_ledger(ledger,year=2023,symbol='XAUUSD_',full_annual_union=False)
            for db,mp in pairs:self.assertEqual(append_shard(ledger,db,mp)['status'],'PASS')
            stream=finalize(ledger,t/'stream.json')
            for key in ('status','year','symbol','full_annual_union','shard_count','total_shard_bytes','storage_contract_hash','design_freeze_hash','engine_sha256','table_row_counts','table_logical_sha256','global_logical_sha256','unresolved_group8_reference_count','duplicate_domain_id_count','registry_conflict_count','oos_2024_accessed'):
                self.assertEqual(stream[key],legacy[key],key)
            with self.assertRaisesRegex(RuntimeError,'duplicate shard append'):
                append_shard(ledger,pairs[0][0],pairs[0][1])

if __name__=='__main__':unittest.main()
