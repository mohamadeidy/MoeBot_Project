#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import group8_finalize_annual_2023 as finalizer

ART = Path(__file__).resolve().parents[1]


def rh(d):
    x=dict(d);x["report_hash"]=hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest();return x


class AnnualFinalizerTests(unittest.TestCase):
    def test_finalize_revokes_execution_and_binds_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            shutil.copy2(ART/"STATUS.json",root/"STATUS.json")
            shutil.copy2(ART/"ENGINE_BUILD_MANIFEST.json",root/"ENGINE_BUILD_MANIFEST.json")
            material=rh({"status":"PASS","year":2023})
            engine=rh({"status":"PASS","year":2023})
            annual_base={"status":"PASS","year":2023,"engine_version":"0.8.0","schema_version":"8.0.0","config_id":json.loads((ART/"ENGINE_BUILD_MANIFEST.json").read_text())["config_id"],"engine_build_manifest_hash":json.loads((ART/"ENGINE_BUILD_MANIFEST.json").read_text())["manifest_hash"],"engine_sha256":json.loads((ART/"ENGINE_BUILD_MANIFEST.json").read_text())["identities"]["engine"]["sha256"],"postprocessor_sha256":json.loads((ART/"ENGINE_BUILD_MANIFEST.json").read_text())["identities"]["postprocessor"]["sha256"],"causality_errors":{},"upstream_reference_integrity":{"unresolved_group8":0,"unresolved_upstream":0,"unknown_source_types":[]},"lifecycle":{"hypotheses":2,"initial":2,"terminal":2,"before_creation":0},"counts":{"narrative_hypothesis":2},"distributions":{"x":{"a":2}},"no_trading_outputs":True,"read_only_upstream":True,"failures":[]}
            paths=[]
            for name in ("initial","rerun","clean"):
                p=root/f"annual_{name}.json";p.write_text(json.dumps(rh(annual_base),indent=2)+"\n");paths.append(p)
            fp=rh({"status":"PASS","logical_sha256":"abc","tables":{"t":{"logical_sha256":"def"}},"quick_check":"ok","integrity_check":"ok","foreign_key_errors":0})
            fpaths=[]
            for name in ("initial","rerun","clean"):
                p=root/f"fp_{name}.json";p.write_text(json.dumps(fp,indent=2)+"\n");fpaths.append(p)
            mp=root/"material.json";mp.write_text(json.dumps(material)+"\n")
            ep=root/"engine.json";ep.write_text(json.dumps(engine)+"\n")
            db=root/"MoeBot_Group8_XAUUSD_2023_v0.8.0.sqlite";db.write_bytes(b"sqlite-candidate")
            z=root/(db.name+".zst");z.write_bytes(b"compressed")
            manifest=root/"ANNUAL_2023_VALIDATION_MANIFEST.json"
            argv=sys.argv
            try:
                sys.argv=["x","--group8-root",str(root),"--materializer-report",str(mp),"--engine-audit",str(ep),"--annual-initial",str(paths[0]),"--annual-rerun",str(paths[1]),"--annual-clean",str(paths[2]),"--fingerprint-initial",str(fpaths[0]),"--fingerprint-rerun",str(fpaths[1]),"--fingerprint-clean",str(fpaths[2]),"--output-db",str(db),"--compressed-output",str(z),"--validation-run-id","123","--artifact-name","candidate","--manifest-output",str(manifest)]
                self.assertEqual(finalizer.main(),0)
            finally:
                sys.argv=argv
            m=json.loads(manifest.read_text());s=json.loads((root/"STATUS.json").read_text())
            self.assertEqual(m["status"],"ANNUAL_2023_PASS")
            self.assertEqual(m["logical_fingerprint"],"abc")
            self.assertFalse(s["annual_execution_authorized"])
            self.assertFalse(s["annual_execution_2023_authorized"])
            self.assertFalse(s["annual_execution_2024_authorized"])
            self.assertEqual(s["status"],"ANNUAL_2023_PASS_OOS_FREEZE_REQUIRED")


if __name__=="__main__":unittest.main(verbosity=2)
