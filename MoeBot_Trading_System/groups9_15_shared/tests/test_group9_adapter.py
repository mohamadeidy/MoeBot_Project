#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class AdapterTests(unittest.TestCase):
 def test_adapter_roles_are_nonexclusive_and_complete(self):
  a=json.loads((ROOT/"Group_9"/"GROUP8_ADAPTER_MAP_DRAFT.json").read_text())
  self.assertEqual(a["status"],"DRAFT_NONEXCLUSIVE_NOT_FROZEN")
  self.assertEqual(set(a["component_roles"]),{"context","location","liquidity","displacement","structure","poi","retracement","confirmation"})
  flattened=[x for v in a["component_roles"].values() for x in v]
  self.assertLess(len(set(flattened)),len(flattened))
 def test_probe_passes_synthetic_compatible_db(self):
  a=json.loads((ROOT/"Group_9"/"GROUP8_ADAPTER_MAP_DRAFT.json").read_text())
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=td/"x.sqlite";con=sqlite3.connect(db)
   for t,cs in a["required_tables"].items():
    defs=",".join(f'"{c}" TEXT' for c in cs);con.execute(f'CREATE TABLE "{t}"({defs})')
   con.commit();con.close()
   ids=sorted({x for v in a["component_roles"].values() for x in v})
   reg=td/"defs.json";reg.write_text(json.dumps({"definitions":{x:{} for x in ids},"registry_hash":"synthetic"}))
   out=td/"r.json";cp=subprocess.run([sys.executable,str(ROOT/"Group_9"/"code"/"group9_group8_adapter_probe.py"),"--database",str(db),"--adapter",str(ROOT/"Group_9"/"GROUP8_ADAPTER_MAP_DRAFT.json"),"--definition-registry",str(reg),"--report",str(out)])
   self.assertEqual(cp.returncode,0);self.assertEqual(json.loads(out.read_text())["status"],"PASS")
if __name__=="__main__":unittest.main(verbosity=2)
