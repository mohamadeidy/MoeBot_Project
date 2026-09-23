#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SH=ROOT/"groups9_15_shared"

class SyntheticPipelineTests(unittest.TestCase):
    def test_planner_union_handoff_for_all_groups(self):
        with tempfile.TemporaryDirectory() as t:
            t=Path(t)
            inv=t/"inventory.json"
            inv.write_text(json.dumps({"items":[{"root_id":f"id-{i}"} for i in range(20)]}))
            for g in range(9,16):
                plan=t/f"g{g}.plan.json"
                subprocess.check_call([sys.executable,str(SH/"group_shard_planner.py"),"--group-dir",str(ROOT/f"Group_{g}"),"--inventory",str(inv),"--bucket-count","4","--output",str(plan)])
                p=json.loads(plan.read_text()); mr=t/f"g{g}_manifests";mr.mkdir()
                all_ids=[x["root_id"] for x in json.loads(inv.read_text())["items"]]
                buckets={i:[] for i in range(4)}
                for rid in all_ids:
                    b=int.from_bytes(hashlib.sha256(rid.encode()).digest()[:8],"big")%4
                    buckets[b].append(rid)
                for s in p["shards"]:
                    ids=buckets[s["bucket_index"]]
                    (mr/f'{s["shard_id"]}.manifest.json').write_text(json.dumps({
                      "shard_id":s["shard_id"],"status":"PASS","row_count":len(ids),"sample_or_all_ids":ids
                    }))
                ur=t/f"g{g}.union.json"
                subprocess.check_call([sys.executable,str(SH/"group_union_validator.py"),"--plan",str(plan),"--manifest-root",str(mr),"--report",str(ur)])
                self.assertEqual(json.loads(ur.read_text())["status"],"PASS")
                rel=t/f"g{g}.release.json";rel.write_text(json.dumps({"status":"PASS","group":g}))
                ho=t/f"g{g}.handoff.json"
                subprocess.check_call([sys.executable,str(SH/"group_handoff.py"),"--group-dir",str(ROOT/f"Group_{g}"),"--union-report",str(ur),"--release",str(rel),"--output",str(ho)])
                h=json.loads(ho.read_text())
                self.assertEqual(h["status"],"PASS")
                self.assertTrue(h["consumption_policy"]["read_only"])

if __name__=="__main__": unittest.main(verbosity=2)
