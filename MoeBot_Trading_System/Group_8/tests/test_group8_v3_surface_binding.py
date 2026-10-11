#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_shard_union_validator import DOMAIN_TABLES
from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_surface_binding import build_binding
from moebot_group8_engine_v0_8_0 import sha256_file


def hashed(value:dict,field:str="report_hash")->dict:
    value=dict(value)
    value[field]=stable_hash(value)
    return value


def write(path:Path,value:dict)->None:
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")


class V3SurfaceBindingTests(unittest.TestCase):
    def fixture(self,td:Path):
        catalog=td/"catalog.sqlite"
        con=sqlite3.connect(catalog)
        con.execute("CREATE TABLE pa7_candidate_catalog(candidate_id TEXT PRIMARY KEY,candidate_hash TEXT NOT NULL)")
        con.execute("INSERT INTO pa7_candidate_catalog VALUES('c1','h1')")
        con.commit();con.close()
        h=hashlib.sha256();h.update(b"c1\0h1\n")
        cat_logical=h.hexdigest();cat_sha=sha256_file(catalog)

        s6=hashed({"status":"PASS","stage":6,"year":2023})
        s7=hashed({"status":"PASS","stage":7,"year":2023})
        write(td/"s6.json",s6);write(td/"s7.json",s7)

        base_sha="a"*64
        base=hashed({
            "status":"PASS","year":2023,"database_sha256":base_sha,
            "stage6_union_report_hash":s6["report_hash"],"stage7_union_report_hash":s7["report_hash"],
            "storage_preflight":{"storage_gate_pass":True},
        })
        write(td/"base.json",base)

        pa7=hashed({
            "status":"PASS","year":2023,"shard_count":2,"complete_once_only_coverage":True,
            "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,
        })
        write(td/"pa7.json",pa7)
        catrep=hashed({
            "status":"PASS","candidate_rows":1,"logical_candidate_sha256":cat_logical,
            "pass1_shard_count":2,"pass2_shard_count":2,
        })
        write(td/"catalog.json",catrep)

        table_counts={t:i+1 for i,t in enumerate(DOMAIN_TABLES)}
        table_hashes={t:hashlib.sha256(t.encode()).hexdigest() for t in DOMAIN_TABLES}
        rec_paths=[];union_paths=[]
        for i in range(3):
            dbsha=hashlib.sha256(f"db{i}".encode()).hexdigest()
            refs=hashlib.sha256(f"refs{i}".encode()).hexdigest()
            rec=hashed({
                "status":"PASS","year":2023,"base_core_database_sha256":base_sha,
                "pa7_catalog_sha256":cat_sha,"cross_shard_reference_report_hash":refs,
                "unresolved_group8_reference_count":0,"causality":"PASS","no_trading_outputs":True,
                "logical_sha256":"b"*64,"database_sha256":dbsha,
                "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,
            })
            rp=td/f"rec{i}.json";write(rp,rec);rec_paths.append(rp)
            union=hashed({
                "status":"PASS","year":2023,"full_annual_union":True,
                "pa7_release_report_hash":pa7["report_hash"],"finalized_core_database_sha256":dbsha,
                "core_reference_report_hash":refs,"table_row_counts":table_counts,
                "table_logical_sha256":table_hashes,"global_logical_sha256":"c"*64,
                "unresolved_group8_reference_count":0,"duplicate_domain_id_count":0,"registry_conflict_count":0,
                "free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":False,
            })
            up=td/f"union{i}.json";write(up,union);union_paths.append(up)
        return catalog,rec_paths,union_paths

    def test_complete_binding_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            td=Path(raw);catalog,recs,unions=self.fixture(td)
            out=build_binding(
                year=2023,stage6_union_path=td/"s6.json",stage7_union_path=td/"s7.json",
                base_core_report_path=td/"base.json",pa7_release_path=td/"pa7.json",
                pa7_catalog_path=catalog,pa7_catalog_report_path=td/"catalog.json",
                reconstruction_report_paths=recs,full_union_report_paths=unions,output=td/"binding.json",
            )
            self.assertEqual(out["status"],"PASS")
            self.assertTrue(out["complete_logical_annual_dataset"])
            self.assertEqual(set(out["domain_table_coverage"]),set(DOMAIN_TABLES))
            self.assertTrue(all(x["verified"] for x in out["domain_table_coverage"].values()))

    def test_wrong_pa7_union_binding_fails_even_with_valid_self_hash(self):
        with tempfile.TemporaryDirectory() as raw:
            td=Path(raw);catalog,recs,unions=self.fixture(td)
            bad=json.loads(unions[1].read_text());bad.pop("report_hash")
            bad["pa7_release_report_hash"]="0"*64
            bad["report_hash"]=stable_hash(bad);write(unions[1],bad)
            with self.assertRaisesRegex(RuntimeError,"full_union_pa7_1"):
                build_binding(
                    year=2023,stage6_union_path=td/"s6.json",stage7_union_path=td/"s7.json",
                    base_core_report_path=td/"base.json",pa7_release_path=td/"pa7.json",
                    pa7_catalog_path=catalog,pa7_catalog_report_path=td/"catalog.json",
                    reconstruction_report_paths=recs,full_union_report_paths=unions,output=td/"binding.json",
                )


if __name__=="__main__":
    unittest.main()
