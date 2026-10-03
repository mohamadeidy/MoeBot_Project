#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_full_surface_guard import REQUIRED_DOMAIN_TABLES, build_receipt, load_full_surface_receipt


def w(path:Path, value:dict)->dict:
    rec=dict(value);rec["report_hash"]=stable_hash(rec)
    path.write_text(json.dumps(rec))
    return rec


class FullSurfaceGuardTests(unittest.TestCase):
    def fixture(self, root:Path, year:int=2023):
        oos=year==2024
        s6=w(root/"s6",{"status":"PASS","stage":6,"year":year})
        s7=w(root/"s7",{"status":"PASS","stage":7,"year":year})
        pa=w(root/"pa",{
            "status":"PASS","year":year,"complete_once_only_coverage":True,
            "free_only":True,"paid_runner_used":False,"paid_service_used":False,
            "oos_2024_accessed":oos,
        })
        recs=[];unions=[]
        for i in range(3):
            recs.append(w(root/f"r{i}",{
                "status":"PASS","year":year,"causality":"PASS","no_trading_outputs":True,
                "unresolved_group8_reference_count":0,"free_only":True,
                "paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":oos,
                "logical_sha256":"a"*64,
            }))
            unions.append(w(root/f"u{i}",{
                "status":"PASS","year":year,"full_annual_union":True,
                "unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,
                "registry_conflict_count":0,"free_only":True,"paid_runner_used":False,
                "paid_service_used":False,"oos_2024_accessed":oos,
                "global_logical_sha256":"b"*64,
            }))
        cov={t:{"verified":True} for t in REQUIRED_DOMAIN_TABLES}
        binding=w(root/"b",{
            "status":"PASS","year":year,"complete_logical_annual_dataset":True,
            "stage6_union_report_hash":s6["report_hash"],"stage7_union_report_hash":s7["report_hash"],
            "pa7_release_report_hash":pa["report_hash"],"domain_table_coverage":cov,
            "reconstruction_report_hashes":[r["report_hash"] for r in recs],
            "full_union_report_hashes":[u["report_hash"] for u in unions],
            "finalized_core_logical_sha256":"a"*64,"full_union_global_logical_sha256":"b"*64,
            "unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,
            "registry_conflict_count":0,"free_only":True,"paid_runner_used":False,
            "paid_service_used":False,"oos_2024_accessed":oos,
        })
        return s6,s7,pa,binding

    def test_build_and_reload(self):
        with tempfile.TemporaryDirectory() as raw:
            d=Path(raw);y=2023;s6,s7,_pa,_binding=self.fixture(d,y)
            out=d/"o"
            r=build_receipt(
                year=y,stage6_union_path=d/"s6",stage7_union_path=d/"s7",
                pa7_release_path=d/"pa",reconstruction_report_paths=[d/f"r{i}" for i in range(3)],
                full_union_report_paths=[d/f"u{i}" for i in range(3)],
                binding_report_path=d/"b",output=out,
            )
            self.assertTrue(r["complete_logical_annual_dataset"])
            loaded=load_full_surface_receipt(
                out,year=y,stage6_union_report_hash=s6["report_hash"],
                stage7_union_report_hash=s7["report_hash"],
            )
            self.assertEqual(loaded["logical_fingerprint"],"b"*64)

    def test_binding_with_nonzero_integrity_error_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            d=Path(raw);self.fixture(d,2023)
            b=json.loads((d/"b").read_text());b.pop("report_hash")
            b["duplicate_domain_id_count"]=1;b["report_hash"]=stable_hash(b)
            (d/"b").write_text(json.dumps(b))
            with self.assertRaisesRegex(RuntimeError,"binding_duplicate_domain_id_count"):
                build_receipt(
                    year=2023,stage6_union_path=d/"s6",stage7_union_path=d/"s7",
                    pa7_release_path=d/"pa",reconstruction_report_paths=[d/f"r{i}" for i in range(3)],
                    full_union_report_paths=[d/f"u{i}" for i in range(3)],
                    binding_report_path=d/"b",output=d/"o",
                )

    def test_loaded_receipt_rejects_paid_execution_flag(self):
        with tempfile.TemporaryDirectory() as raw:
            d=Path(raw);s6,s7,_pa,_binding=self.fixture(d,2023)
            out=d/"o"
            r=build_receipt(
                year=2023,stage6_union_path=d/"s6",stage7_union_path=d/"s7",
                pa7_release_path=d/"pa",reconstruction_report_paths=[d/f"r{i}" for i in range(3)],
                full_union_report_paths=[d/f"u{i}" for i in range(3)],
                binding_report_path=d/"b",output=out,
            )
            r=dict(r);r.pop("report_hash");r["paid_runner_used"]=True;r["report_hash"]=stable_hash(r)
            out.write_text(json.dumps(r))
            with self.assertRaisesRegex(RuntimeError,"free_only"):
                load_full_surface_receipt(
                    out,year=2023,stage6_union_report_hash=s6["report_hash"],
                    stage7_union_report_hash=s7["report_hash"],
                )


if __name__=="__main__":
    unittest.main()
