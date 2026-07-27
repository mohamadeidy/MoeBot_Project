#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from group8_pa7_shard_executor import ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from group8_pa7_catalog import build_catalog,init_catalog,append_shards,finalize_catalog
from test_group8_engine_v0_8_0 import ART,make_stage


def rows(db:Path):
    c=sqlite3.connect(db)
    try:return {str(r[0]):str(r[1]) for r in c.execute('SELECT candidate_id,candidate_hash FROM pa7_candidate_catalog')}
    finally:c.close()

class StreamingCatalogEquivalence(unittest.TestCase):
    def test_streaming_append_equals_one_shot_catalog_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);shards=[]
            for tf in ('M15','H1'):
                for scope in ('upstream','group8_range'):
                    for b in range(4):
                        out=t/f's_{tf}_{scope}_{b}.sqlite';man=t/f'm_{tf}_{scope}_{b}.json';run_annual_pa7_shard(staging_db=stage,work_db=t/f'w_{tf}_{scope}_{b}.sqlite',output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,b),boundary_scope=scope,manifest_path=man);shards.append(out)
            one=t/'one.sqlite';stream=t/'stream.sqlite';r1=build_catalog(shards,one);init_catalog(stream,replace=True)
            for s in shards:append_shards(stream,[s])
            r2=finalize_catalog(stream)
            self.assertEqual(rows(one),rows(stream));self.assertEqual(r1['candidate_rows'],r2['candidate_rows']);self.assertEqual(r1['definition_counts'],r2['definition_counts']);self.assertEqual(r1['logical_candidate_sha256'],r2['logical_candidate_sha256']);self.assertEqual(r2['source_shard_count'],len(shards))
    def test_duplicate_shard_append_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';make_stage(stage);out=t/'s.sqlite';man=t/'m.json';run_annual_pa7_shard(staging_db=stage,work_db=t/'w.sqlite',output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_','M15',None,1,0),boundary_scope='upstream',manifest_path=man);cat=t/'c.sqlite';init_catalog(cat,replace=True);append_shards(cat,[out])
            with self.assertRaises(RuntimeError):append_shards(cat,[out])

if __name__=='__main__':unittest.main()
