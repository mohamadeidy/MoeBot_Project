#!/usr/bin/env python3
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from group8_pa7_shard_executor import ShardSpec, run_shard
from group8_shard_union_validator import validate
from test_group8_engine_v0_8_0 import ART, make_stage


class ShardUnionValidatorTest(unittest.TestCase):
    def test_partial_pa7_union_passes_and_duplicate_domain_shard_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);pairs=[]
            for b in range(4):
                work=t/f'w{b}.sqlite';db=t/f's{b}.sqlite';manifest=t/f'm{b}.json'
                run_shard(staging_db=stage,work_db=work,output_db=db,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',None,4,b),manifest_path=manifest)
                pairs.append({'database':str(db),'manifest':str(manifest)})
            index=t/'index.json';index.write_text(json.dumps({'year':2023,'symbol':'XAUUSD_','full_annual_union':False,'shards':pairs}))
            report=validate(index,t/'report.json')
            self.assertEqual(report['status'],'PASS');self.assertEqual(report['shard_count'],4);self.assertGreater(report['table_row_counts'].get('price_action_pattern_candidate',0),0);self.assertEqual(report['duplicate_domain_id_count'],0)
            dup=t/'dup.json';dup.write_text(json.dumps({'year':2023,'symbol':'XAUUSD_','full_annual_union':False,'shards':pairs+[pairs[0]]}))
            with self.assertRaisesRegex(RuntimeError,'duplicate domain IDs'):
                validate(dup,t/'dup-report.json')

if __name__=='__main__':unittest.main()
