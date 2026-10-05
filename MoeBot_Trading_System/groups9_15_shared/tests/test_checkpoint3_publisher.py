#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve()
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"groups9_15_shared"))

from publish_group8_checkpoint3 import publish, stable


def write_hashed(path:Path, rec:dict, field:str)->dict:
    x=dict(rec);x[field]=stable(x);path.write_text(json.dumps(x));return x


class Checkpoint3PublisherTests(unittest.TestCase):
    def test_pass_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            a23=write_hashed(td/"a23.json",{"status":"ANNUAL_2023_PASS"},"manifest_hash")
            a24=write_hashed(td/"a24.json",{"status":"ANNUAL_2024_OOS_PASS"},"manifest_hash")
            cross=write_hashed(td/"cross.json",{"status":"PASS","identity_stable_across_oos_boundary":True,"frozen_semantics_stable":True},"report_hash")
            closure=write_hashed(td/"closure.json",{
                "status":"OFFICIALLY_CLOSED_V3","officially_closed":True,"group9_authorized":True,
                "validated_commit":"v","oos_tooling_commit":"t",
                "annual_2023_manifest_hash":a23["manifest_hash"],
                "annual_2024_oos_manifest_hash":a24["manifest_hash"],
                "cross_year_report_hash":cross["report_hash"],
                "post_freeze_physical_tooling_amendment":True,
                "prior_pre_oos_freeze_manifest_hash":"prior",
            },"closure_hash")
            handoff=write_hashed(td/"handoff.json",{
                "status":"FROZEN_HANDOFF","source_group":8,"target_group":9,
                "closure_hash":closure["closure_hash"],"validated_commit":"v","oos_tooling_commit":"t",
                "annual_2023_manifest_hash":a23["manifest_hash"],
                "annual_2024_oos_manifest_hash":a24["manifest_hash"],
                "cross_year_report_hash":cross["report_hash"],
                "consumption_policy":{"read_only":True},
            },"manifest_hash")
            unions=[]
            for i in range(4):
                unions.append(write_hashed(td/f"u{i}.json",{
                    "status":"PASS","duplicate_domain_id_count":0,
                    "unresolved_local_evidence_subject_count":0
                },"report_hash"))
            out=td/"checkpoint3.json"
            r=publish(
                closure_path=td/"closure.json",handoff_path=td/"handoff.json",
                annual23_path=td/"a23.json",annual24_path=td/"a24.json",
                cross_path=td/"cross.json",
                stage6_2023_union_path=td/"u0.json",stage7_2023_union_path=td/"u1.json",
                stage6_2024_union_path=td/"u2.json",stage7_2024_union_path=td/"u3.json",
                explicit_approval=True,output=out)
            self.assertEqual(r["status"],"PASS")
            self.assertEqual(r["checkpoint"],3)
            self.assertTrue(r["real_group9_dependency_intake_authorized"])

    def test_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            with self.assertRaises(RuntimeError):
                publish(
                    closure_path=td/"x",handoff_path=td/"x",annual23_path=td/"x",
                    annual24_path=td/"x",cross_path=td/"x",
                    stage6_2023_union_path=td/"x",stage7_2023_union_path=td/"x",
                    stage6_2024_union_path=td/"x",stage7_2024_union_path=td/"x",
                    explicit_approval=False,output=td/"out")

if __name__=="__main__":
    unittest.main()
