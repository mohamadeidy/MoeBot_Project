#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MOD=ROOT/"Group_9"/"code"/"group9_preflight.py"
spec=importlib.util.spec_from_file_location("group9_preflight", MOD)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def stable(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

class HashPrecedenceTests(unittest.TestCase):
    def test_handoff_uses_manifest_hash_not_parent_closure_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"handoff.json"
            rec={"status":"FROZEN_HANDOFF","closure_hash":"parent-closure","source_group":8,"target_group":9}
            rec["manifest_hash"]=stable(rec)
            p.write_text(json.dumps(rec))
            got=m.load_hash(p)
            self.assertEqual(got["manifest_hash"],rec["manifest_hash"])

if __name__=="__main__":
    unittest.main(verbosity=2)
