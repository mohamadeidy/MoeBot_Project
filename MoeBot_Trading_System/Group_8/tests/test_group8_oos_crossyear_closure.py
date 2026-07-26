#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import group8_cross_year_validation as cross_year
import group8_finalize_annual_2024_oos as finalize24
import group8_prepare_closure_candidate as prepare_close
import group8_finalize_official_release_closure as official_close

ART = Path(__file__).resolve().parents[1]


def rh(d):
    x = dict(d); x["report_hash"] = hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); return x


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


class OOSCrossYearClosureTests(unittest.TestCase):
    def _base(self, root: Path):
        for rel in ("ENGINE_BUILD_MANIFEST.json", "DESIGN_FREEZE_MANIFEST.json", "FROZEN_CONFIG.json"):
            shutil.copy2(ART / rel, root / rel)
        build = json.loads((root / "ENGINE_BUILD_MANIFEST.json").read_text()); status = json.loads((ART / "STATUS.json").read_text())
        annual23 = {
            "format_version":1,"status":"ANNUAL_2023_PASS","group":8,"year":2023,"engine_version":build["engine_version"],"schema_version":build["schema_version"],"config_id":build["config_id"],
            "engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":build["identities"]["engine"]["sha256"],"postprocessor_sha256":build["identities"]["postprocessor"]["sha256"],"materializer_sha256":build["identities"]["materializer"]["sha256"],
            "logical_fingerprint":"logical23","manifest_hash":"annual23hash","idempotence":"PASS","clean_reconstruction":"PASS","causality":"PASS","no_lookahead":"PASS","no_backdating":"PASS","duplicate_prevention":"PASS","upstream_reference_integrity":"PASS","no_trading_outputs":True,
            "database":{"filename":"g8_2023.sqlite","size_bytes":10,"sha256":"db23","logical_sha256":"logical23"},"compressed_asset":{"filename":"g8_2023.sqlite.zst","size_bytes":5,"sha256":"z23"},"validation_run_id":"111","artifact_name":"artifact23",
        }
        write(root/"ANNUAL_2023_VALIDATION_MANIFEST.json",annual23); status["annual_validation_2023"]={"status":"PASS","manifest_hash":annual23["manifest_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":annual23["engine_sha256"],"config_id":build["config_id"]}
        return build,status,annual23

    def test_2024_oos_finalizer_revokes_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);build,status,a23=self._base(root)
            freeze={"status":"FROZEN_FOR_2024_OOS","manifest_hash":"ooshash","annual_2023_manifest_hash":a23["manifest_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":a23["engine_sha256"],"postprocessor_sha256":a23["postprocessor_sha256"],"materializer_sha256":a23["materializer_sha256"],"config_id":build["config_id"],"identities":{}};write(root/"OOS_FREEZE_MANIFEST.json",freeze)
            status["annual_execution_authorized"]=True;status["annual_execution_2023_authorized"]=False;status["annual_execution_2024_authorized"]=True;status["status"]="OOS_2024_FROZEN_AND_AUTHORIZED";write(root/"STATUS.json",status)
            material=rh({"status":"PASS","year":2024,"config_id":build["config_id"]});engine=rh({"status":"PASS","year":2024,"config_id":build["config_id"]})
            annual_base={"status":"PASS","year":2024,"engine_version":build["engine_version"],"schema_version":build["schema_version"],"config_id":build["config_id"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":a23["engine_sha256"],"postprocessor_sha256":a23["postprocessor_sha256"],"causality_errors":{},"upstream_reference_integrity":{"unresolved_group8":0,"unresolved_upstream":0,"unknown_source_types":[]},"lifecycle":{"hypotheses":1,"initial":1,"terminal":1,"before_creation":0},"counts":{"narrative_hypothesis":1},"distributions":{"hypotheses_by_school":{"school":1}},"no_trading_outputs":True,"read_only_upstream":True,"failures":[]}
            annuals=[];fps=[]
            for n in ("initial","rerun","clean"):
                ap=root/f"a_{n}.json";write(ap,rh(annual_base));annuals.append(ap);fp=root/f"f_{n}.json";write(fp,rh({"status":"PASS","logical_sha256":"logical24","tables":{"t":{"logical_sha256":"th"}},"quick_check":"ok","integrity_check":"ok","foreign_key_errors":0}));fps.append(fp)
            mp=root/"material.json";ep=root/"engine.json";write(mp,material);write(ep,engine);db=root/"g8_2024.sqlite";z=root/"g8_2024.sqlite.zst";db.write_bytes(b"db24");z.write_bytes(b"z24");out=root/"ANNUAL_2024_OOS_VALIDATION_MANIFEST.json";argv=sys.argv
            try:
                sys.argv=["x","--group8-root",str(root),"--materializer-report",str(mp),"--engine-audit",str(ep),"--annual-initial",str(annuals[0]),"--annual-rerun",str(annuals[1]),"--annual-clean",str(annuals[2]),"--fingerprint-initial",str(fps[0]),"--fingerprint-rerun",str(fps[1]),"--fingerprint-clean",str(fps[2]),"--output-db",str(db),"--compressed-output",str(z),"--validation-run-id","222","--artifact-name","artifact24","--manifest-output",str(out)];self.assertEqual(finalize24.main(),0)
            finally:sys.argv=argv
            m=json.loads(out.read_text());s=json.loads((root/"STATUS.json").read_text());self.assertEqual(m["status"],"ANNUAL_2024_OOS_PASS");self.assertFalse(m["frozen_identity_drift"]);self.assertFalse(s["annual_execution_authorized"]);self.assertFalse(s["annual_execution_2024_authorized"]);self.assertEqual(s["status"],"ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED")

    def test_cross_year_accepts_descriptive_frequency_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);build,status,a23=self._base(root);freeze={"status":"FROZEN_FOR_2024_OOS","manifest_hash":"ooshash","annual_2023_manifest_hash":a23["manifest_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":a23["engine_sha256"],"config_id":build["config_id"]};write(root/"OOS_FREEZE_MANIFEST.json",freeze)
            a24={**a23,"status":"ANNUAL_2024_OOS_PASS","year":2024,"manifest_hash":"annual24hash","oos_freeze_manifest_hash":"ooshash","logical_fingerprint":"logical24"};write(root/"ANNUAL_2024_OOS_VALIDATION_MANIFEST.json",a24);status["annual_execution_authorized"]=False;status["annual_execution_2023_authorized"]=False;status["annual_execution_2024_authorized"]=False;status["status"]="ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED";write(root/"STATUS.json",status)
            base={"status":"PASS","failures":[],"no_trading_outputs":True,"read_only_upstream":True,"causality_errors":{},"upstream_reference_integrity":{"unresolved_group8":0,"unresolved_upstream":0,"unknown_source_types":[]},"lifecycle":{"hypotheses":2,"initial":2,"terminal":2,"before_creation":0}}
            write(root/"reports/32_ANNUAL_2023_VALIDATION.json",{**base,"counts":{"x":10},"distributions":{"d":{"a":10}}});write(root/"reports/42_ANNUAL_2024_OOS_VALIDATION.json",{**base,"counts":{"x":25},"distributions":{"d":{"a":5,"b":20}}});out=root/"reports/50_CROSS_YEAR_VALIDATION.json";argv=sys.argv
            try:sys.argv=["x","--group8-root",str(root),"--output",str(out)];self.assertEqual(cross_year.main(),0)
            finally:sys.argv=argv
            r=json.loads(out.read_text());self.assertTrue(r["identity_stable_across_oos_boundary"]);self.assertEqual(r["counts"]["x"]["2023"],10);self.assertEqual(r["counts"]["x"]["2024"],25)

    def test_release_gated_official_closure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);build,status,a23=self._base(root);oos={"status":"FROZEN_FOR_2024_OOS","manifest_hash":"ooshash","annual_2023_manifest_hash":a23["manifest_hash"],"engine_build_manifest_hash":build["manifest_hash"],"engine_sha256":a23["engine_sha256"],"config_id":build["config_id"]};write(root/"OOS_FREEZE_MANIFEST.json",oos)
            a24={**a23,"status":"ANNUAL_2024_OOS_PASS","year":2024,"manifest_hash":"annual24hash","oos_freeze_manifest_hash":"ooshash","logical_fingerprint":"logical24","database":{"filename":"g8_2024.sqlite","size_bytes":11,"sha256":"db24","logical_sha256":"logical24"},"compressed_asset":{"filename":"g8_2024.sqlite.zst","size_bytes":6,"sha256":"z24"},"validation_run_id":"222","artifact_name":"artifact24"};write(root/"ANNUAL_2024_OOS_VALIDATION_MANIFEST.json",a24)
            cross=rh({"status":"PASS","identity_stable_across_oos_boundary":True,"no_trading_outputs_both_years":True,"read_only_upstream_both_years":True});write(root/"reports/50_CROSS_YEAR_VALIDATION.json",cross);status["status"]="ANNUAL_2024_OOS_PASS_CROSS_YEAR_REQUIRED";status["annual_execution_authorized"]=False;status["annual_execution_2023_authorized"]=False;status["annual_execution_2024_authorized"]=False;write(root/"STATUS.json",status)
            required=["00_DESIGN_LOCK.md","01_DEFINITION_REGISTRY.json","02_SCHEMA.sql","contracts/UPSTREAM_INPUT_CONTRACT.json","UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json","UPSTREAM_ADAPTER_MAP.json","UPSTREAM_VALUE_BINDINGS.json","UPSTREAM_REFERENCE_RESOLUTION.json","code/moebot_group8_engine_v0_8_0.py","code/group8_materialize_inputs.py","code/group8_postprocess_v0_8_0.py","tests/test_group8_engine_v0_8_0.py","tests/test_group8_lifecycle_persistence_v0_8_0.py","reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json","reports/30_ANNUAL_2023_MATERIALIZATION.json","reports/31_ANNUAL_2023_ENGINE_AUDIT.json","reports/32_ANNUAL_2023_VALIDATION.json","reports/33_ANNUAL_2023_OUTPUT_FINGERPRINT.json","reports/34_ANNUAL_2023_CLEAN_RECONSTRUCTION.json","reports/40_ANNUAL_2024_MATERIALIZATION.json","reports/41_ANNUAL_2024_ENGINE_AUDIT.json","reports/42_ANNUAL_2024_OOS_VALIDATION.json","reports/43_ANNUAL_2024_OUTPUT_FINGERPRINT.json","reports/44_ANNUAL_2024_CLEAN_RECONSTRUCTION.json"]
            for rel in required:
                p=root/rel
                if p.exists():continue
                src=ART/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,p) if src.is_file() else p.write_text(f"fixture:{rel}\n")
            argv=sys.argv
            try:
                sys.argv=["x","--group8-root",str(root),"--cross-year",str(root/"reports/50_CROSS_YEAR_VALIDATION.json"),"--final-audit-output",str(root/"reports/51_FINAL_INDEPENDENT_AUDIT.json"),"--next-group-output",str(root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json"),"--candidate-output",str(root/"CLOSURE_CANDIDATE_MANIFEST.json"),"--handoff-output",str(root/"12_HANDOFF_REQUIREMENTS.md")];self.assertEqual(prepare_close.main(),0)
            finally:sys.argv=argv
            s=json.loads((root/"STATUS.json").read_text());self.assertFalse(s["officially_closed"]);self.assertFalse(s["next_group_start_authorized"]);self.assertEqual(s["status"],"CLOSURE_CANDIDATE_RELEASE_REQUIRED")
            cand=json.loads((root/"CLOSURE_CANDIDATE_MANIFEST.json").read_text());n=json.loads((root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json").read_text());audit=json.loads((root/"reports/51_FINAL_INDEPENDENT_AUDIT.json").read_text())
            pub=rh({"status":"PASS","release_tag":"moebot-group8-v0.8.0","release_url":"https://github.test/release","candidate_hash":cand["candidate_hash"],"pre_release_next_group_manifest_hash":n["manifest_hash"],"final_audit_hash":audit["report_hash"],"assets":{"2023":{"name":a23["compressed_asset"]["filename"],"size_bytes":a23["compressed_asset"]["size_bytes"],"sha256":a23["compressed_asset"]["sha256"],"download_verified":True},"2024":{"name":a24["compressed_asset"]["filename"],"size_bytes":a24["compressed_asset"]["size_bytes"],"sha256":a24["compressed_asset"]["sha256"],"download_verified":True}}});write(root/"RELEASE_PUBLICATION_MANIFEST.json",pub)
            try:
                sys.argv=["x","--group8-root",str(root),"--publication",str(root/"RELEASE_PUBLICATION_MANIFEST.json"),"--closure-output",str(root/"CLOSURE_MANIFEST.json"),"--handoff-output",str(root/"12_HANDOFF_REQUIREMENTS.md")];self.assertEqual(official_close.main(),0)
            finally:sys.argv=argv
            s=json.loads((root/"STATUS.json").read_text());n=json.loads((root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json").read_text());c=json.loads((root/"CLOSURE_MANIFEST.json").read_text());self.assertTrue(s["officially_closed"]);self.assertTrue(s["next_group_start_authorized"]);self.assertEqual(c["status"],"OFFICIALLY_CLOSED");self.assertTrue(n["consumption_policy"]["read_only"]);self.assertEqual(n["status"],"FROZEN_HANDOFF");self.assertTrue(n["release_publication_verified"])


if __name__=="__main__":unittest.main(verbosity=2)
