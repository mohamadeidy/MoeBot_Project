#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SH=ROOT/"groups9_15_shared"
class FrameworkTests(unittest.TestCase):
 def test_all_groups_have_complete_preparation_plan(self):
  required={"group","name","purpose","predecessor_gates","required_inputs","outputs","semantic_rules","forbidden","partition_strategy","execution_stages","handoff"}
  for g in range(9,16):
   p=json.loads((ROOT/f"Group_{g}"/"PREPARATION_PLAN.json").read_text())
   self.assertTrue(required.issubset(p),f"group {g}")
   self.assertEqual(p["status"],"DRAFT_PREPARATION")
   self.assertFalse(p["real_execution_authorized"])
 def test_sizing_blocks_huge_projection(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td)/"r.json"
   cp=subprocess.run([sys.executable,str(SH/"group_sizing.py"),"--group","9","--candidate-count","1000000","--sample-count","1","--sample-seconds","3600","--sample-output-bytes","1","--sample-peak-bytes","1","--probe-path",td,"--hard-hours","1","--report",str(r)])
   self.assertEqual(cp.returncode,2);self.assertEqual(json.loads(r.read_text())["status"],"BLOCKED")
 def test_planner_is_deterministic(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);inv=td/"i.json";inv.write_text(json.dumps({"items":[{"root_id":"a"},{"root_id":"b"},{"root_id":"c"}]}))
   outs=[]
   for n in (1,2):
    o=td/f"p{n}.json";subprocess.check_call([sys.executable,str(SH/"group_shard_planner.py"),"--group-dir",str(ROOT/"Group_9"),"--inventory",str(inv),"--bucket-count","4","--output",str(o)]);outs.append(json.loads(o.read_text())["plan_hash"])
   self.assertEqual(outs[0],outs[1])
if __name__=="__main__":unittest.main(verbosity=2)
