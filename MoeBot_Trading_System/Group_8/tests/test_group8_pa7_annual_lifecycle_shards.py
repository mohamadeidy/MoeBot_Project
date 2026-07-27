#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,tempfile,unittest
from pathlib import Path
from moebot_group8_engine_v0_8_0 import Group8Engine
from group8_pa7_shard_executor import CHAIN_DEFINITIONS,ShardSpec
from group8_pa7_annual_shard_executor import run_annual_pa7_shard
from test_group8_engine_v0_8_0 import ART,make_stage


def cmap(db:Path):
    con=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in CHAIN_DEFINITIONS)
        return {r[0]:r[1] for r in con.execute(f'SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ({q})',CHAIN_DEFINITIONS)}
    finally:con.close()

def smap(db:Path,cids:set[str]):
    con=sqlite3.connect(db);out={}
    try:
        ids=sorted(cids)
        for i in range(0,len(ids),500):
            chunk=ids[i:i+500]
            if not chunk:continue
            q=','.join('?' for _ in chunk)
            for r in con.execute(f'SELECT state_event_id,state_hash FROM price_action_pattern_state WHERE candidate_id IN ({q})',chunk):out[r[0]]=r[1]
        return out
    finally:con.close()

def emap(db:Path,cids:set[str]):
    con=sqlite3.connect(db);out={}
    try:
        ids=sorted(cids)
        for i in range(0,len(ids),500):
            chunk=ids[i:i+500]
            if not chunk:continue
            q=','.join('?' for _ in chunk)
            for r in con.execute(f"SELECT evidence_chain_id,evidence_hash FROM evidence_chain WHERE subject_type='price_action_pattern_candidate' AND subject_id IN ({q})",chunk):out[r[0]]=r[1]
        return out
    finally:con.close()

class PA7AnnualLifecycleParity(unittest.TestCase):
    def test_scoped_shard_union_matches_full_reference_candidates_states_and_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);stage=t/'stage.sqlite';refdb=t/'ref.sqlite';make_stage(stage)
            ref=Group8Engine(staging_db=stage,output_db=refdb,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            try:self.assertEqual(ref.run()['status'],'PASS')
            finally:ref.close()
            expc=cmap(refdb);exps=smap(refdb,set(expc));expe=emap(refdb,set(expc));self.assertGreater(len(expc),0);self.assertGreaterEqual(len(expe),len(expc))
            gotc={};gots={};gote={}
            for tf in ('M15','H1'):
                for scope in ('upstream','group8_range'):
                    for bucket in range(4):
                        work=t/f'w_{tf}_{scope}_{bucket}.sqlite';out=t/f'o_{tf}_{scope}_{bucket}.sqlite';man=t/f'm_{tf}_{scope}_{bucket}.json'
                        run_annual_pa7_shard(staging_db=stage,work_db=work,output_db=out,artifacts_root=ART,spec=ShardSpec(2023,'XAUUSD_',tf,None,4,bucket),boundary_scope=scope,manifest_path=man)
                        manifest=json.loads(man.read_text());self.assertTrue(manifest['annual_breakout_followup_finalized']);self.assertTrue(manifest['pa7_evidence_chain_complete']);self.assertIn('evidence_chain',manifest['table_row_counts']);self.assertIn('evidence_chain',manifest['table_logical_sha256'])
                        cm=cmap(out);sm=smap(out,set(cm));em=emap(out,set(cm))
                        for target,source in ((gotc,cm),(gots,sm),(gote,em)):
                            for k,v in source.items():self.assertNotIn(k,target);target[k]=v
            self.assertEqual(expc,gotc)
            self.assertEqual(exps,gots)
            self.assertEqual(expe,gote)
            con=sqlite3.connect(refdb)
            try:
                n=0;ids=sorted(expc)
                for i in range(0,len(ids),500):
                    chunk=ids[i:i+500];qq=','.join('?' for _ in chunk);n+=con.execute(f'SELECT COUNT(*) FROM price_action_pattern_state WHERE state_ordinal>0 AND candidate_id IN ({qq})',chunk).fetchone()[0]
                self.assertGreater(n,0)
            finally:con.close()

if __name__=='__main__':unittest.main()
