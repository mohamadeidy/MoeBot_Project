#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile, unittest, subprocess, sys, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/"Group_9"/"code"/"group9_dependency_intake.py"

def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def w(p,d,f):
 d=dict(d);d[f]=stable(d);p.write_text(json.dumps(d));return d

class IntakeTests(unittest.TestCase):
 def test_compiles_and_blocks_bad_checkpoint(self):
  subprocess.check_call([sys.executable,"-m","py_compile",str(SCRIPT)])
 def test_frozen_semantics_exist(self):
  g=json.loads((ROOT/"Group_9"/"01_DEFINITION_REGISTRY.json").read_text())
  x=dict(g);h=x.pop("registry_hash")
  self.assertEqual(stable(x),h)
  self.assertEqual(g["status"],"FROZEN")
  self.assertTrue(g["frozen_without_outcome_tuning"])
  self.assertEqual(set(g["setup_families"]),{"G9_ICT_LIQUIDITY_DELIVERY","G9_WYCKOFF_RANGE_RESOLUTION","G9_STRUCTURAL_PULLBACK_CONTINUATION"})
  self.assertTrue(g["global_rules"]["mere_time_proximity_never_proves_component_linkage"])
  self.assertTrue(g["global_rules"]["missing_is_right_censor_only"])

if __name__=="__main__":unittest.main(verbosity=2)
