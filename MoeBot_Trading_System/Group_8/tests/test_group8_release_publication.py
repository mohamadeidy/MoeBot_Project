#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import group8_finalize_release_publication as publication

ART=Path(__file__).resolve().parents[1]
GAP_ID="G8-ICT-LOCKED-CONTEXT-005"


def h(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def write(p:Path,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,indent=2,sort_keys=True)+"\n")


class ReleasePublicationTests(unittest.TestCase):
    def test_verified_source_and_redownload_assets_finalize_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shutil.copy2(ART/"ENGINE_BUILD_MANIFEST.json",root/"ENGINE_BUILD_MANIFEST.json");build=json.loads((root/"ENGINE_BUILD_MANIFEST.json").read_text());status=json.loads((ART/"STATUS.json").read_text())
            engine=build["identities"]["engine"]["sha256"];validator=build["identities"]["annual_validator"]["sha256"]
            b23=b"annual-2023-zst-fixture";b24=b"annual-2024-zst-fixture";n23="MoeBot_Group8_XAUUSD_2023_v0.8.0.sqlite.zst";n24="MoeBot_Group8_XAUUSD_2024_v0.8.0.sqlite.zst"
            nextg={"format_version":2,"status":"FROZEN_HANDOFF_PENDING_RELEASE_VERIFICATION","required_release_tag":"moebot-group8-v0.8.0","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID,"annual_database_assets":{"2023":{"release_asset_name":n23,"compressed_size_bytes":len(b23),"compressed_sha256":h(b23),"source_workflow_run_id":"111","source_artifact_name":"artifact23"},"2024":{"release_asset_name":n24,"compressed_size_bytes":len(b24),"compressed_sha256":h(b24),"source_workflow_run_id":"222","source_artifact_name":"artifact24"}},"manifest_hash":"next-hash"};write(root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json",nextg)
            audit={"format_version":2,"status":"PASS","report_hash":"audit-hash","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID};write(root/"reports/51_FINAL_INDEPENDENT_AUDIT.json",audit)
            candidate={"format_version":2,"status":"CLOSURE_CANDIDATE_RELEASE_REQUIRED","officially_closed":False,"release_tag":"moebot-group8-v0.8.0","candidate_hash":"candidate-hash","next_group_dependency_manifest_hash":"next-hash","final_audit_hash":"audit-hash","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID};write(root/"CLOSURE_CANDIDATE_MANIFEST.json",candidate)
            status["officially_closed"]=False;status["status"]="CLOSURE_CANDIDATE_RELEASE_REQUIRED";write(root/"STATUS.json",status)
            source23=root/n23;source24=root/n24;source23.write_bytes(b23);source24.write_bytes(b24);rd=root/"redownload";rd.mkdir();r23=rd/n23;r24=rd/n24;r23.write_bytes(b23);r24.write_bytes(b24);out=root/"RELEASE_PUBLICATION_MANIFEST.json";argv=sys.argv
            try:
                sys.argv=["x","--group8-root",str(root),"--release-url","https://github.test/release","--release-target-sha","abc123","--asset-2023",str(source23),"--asset-2024",str(source24),"--redownload-2023",str(r23),"--redownload-2024",str(r24),"--output",str(out)];self.assertEqual(publication.main(),0)
            finally:sys.argv=argv
            m=json.loads(out.read_text());self.assertEqual(m["format_version"],2);self.assertEqual(m["status"],"PASS");self.assertTrue(m["all_release_assets_redownload_verified"]);self.assertEqual(m["annual_validator_sha256"],validator);self.assertEqual(m["closed_blocking_gap_id"],GAP_ID);self.assertTrue(m["assets"]["2023"]["download_verified"]);self.assertTrue(m["assets"]["2024"]["download_verified"])

    def test_mismatched_redownload_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shutil.copy2(ART/"ENGINE_BUILD_MANIFEST.json",root/"ENGINE_BUILD_MANIFEST.json");build=json.loads((root/"ENGINE_BUILD_MANIFEST.json").read_text());status=json.loads((ART/"STATUS.json").read_text());engine=build["identities"]["engine"]["sha256"];validator=build["identities"]["annual_validator"]["sha256"]
            b23=b"a";b24=b"b";n23="23.zst";n24="24.zst";nextg={"status":"FROZEN_HANDOFF_PENDING_RELEASE_VERIFICATION","required_release_tag":"moebot-group8-v0.8.0","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID,"annual_database_assets":{"2023":{"release_asset_name":n23,"compressed_size_bytes":1,"compressed_sha256":h(b23)},"2024":{"release_asset_name":n24,"compressed_size_bytes":1,"compressed_sha256":h(b24)}},"manifest_hash":"n"};write(root/"NEXT_GROUP_DEPENDENCY_MANIFEST.json",nextg);write(root/"reports/51_FINAL_INDEPENDENT_AUDIT.json",{"status":"PASS","report_hash":"a","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID});write(root/"CLOSURE_CANDIDATE_MANIFEST.json",{"status":"CLOSURE_CANDIDATE_RELEASE_REQUIRED","officially_closed":False,"release_tag":"moebot-group8-v0.8.0","candidate_hash":"c","next_group_dependency_manifest_hash":"n","final_audit_hash":"a","engine_sha256":engine,"annual_validator_sha256":validator,"closed_blocking_gap_id":GAP_ID});status["officially_closed"]=False;status["status"]="CLOSURE_CANDIDATE_RELEASE_REQUIRED";write(root/"STATUS.json",status)
            s23=root/n23;s24=root/n24;s23.write_bytes(b23);s24.write_bytes(b24);rd=root/"r";rd.mkdir();r23=rd/n23;r24=rd/n24;r23.write_bytes(b"X");r24.write_bytes(b24);argv=sys.argv
            try:
                sys.argv=["x","--group8-root",str(root),"--release-url","x","--release-target-sha","y","--asset-2023",str(s23),"--asset-2024",str(s24),"--redownload-2023",str(r23),"--redownload-2024",str(r24),"--output",str(root/"out.json")]
                with self.assertRaises(SystemExit):publication.main()
            finally:sys.argv=argv


if __name__=="__main__":unittest.main(verbosity=2)
