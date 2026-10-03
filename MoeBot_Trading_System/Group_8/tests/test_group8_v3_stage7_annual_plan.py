#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from group8_segmented_annual_core import run_segment
from group8_v3_stage7_annual_plan import _git_head,run_plan
from group8_v3_stage7_preflight import run_preflight
from group8_v3_stage7_benchmark import run_benchmark as run_premium
from moebot_group8_engine_v0_8_0 import sha256_file,stable_hash
from test_group8_engine_v0_8_0 import ART,make_stage

SYMBOL="XAUUSD_"

class Stage7AnnualPlanTests(unittest.TestCase):
 def test_plan_is_fail_closed_and_never_auto_launches(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);staging=td/"staging.sqlite";stage5=td/"stage5.sqlite";make_stage(staging)
   run_segment(staging_db=staging,output_db=stage5,artifacts_root=ART,year=2023,symbol=SYMBOL,start=0,end=5)
   s5=sha256_file(stage5)
   rel={"format_version":1,"status":"PASS","stage":6,"stage5_database_sha256":s5,"total_output_bytes":1000000};rel["release_hash"]=stable_hash(rel);(td/"rel.json").write_text(json.dumps(rel))
   uni={"format_version":1,"status":"PASS","stage":6,"stage6_official_pass_eligible":True,"stage6_release_hash":rel["release_hash"],"stage5_database_sha256":s5,"table_row_counts":{"school_interpretation":1000,"evidence_chain":2000}};uni["report_hash"]=stable_hash(uni);(td/"uni.json").write_text(json.dumps(uni))
   pf=run_preflight(staging_db=staging,stage5_db=stage5,stage6_release_path=td/"rel.json",stage6_union_path=td/"uni.json",artifacts_root=ART,year=2023,symbol=SYMBOL,validated_commit=_git_head(ART),report_path=td/"pf.json")
   # Minimal PASS evidence with correct self-hashes/lineage. The plan recomputes school exact counts.
   pb={"status":"PASS","report_hash":"","stage7_preflight_report_hash":pf["report_hash"],"sample":{"bytes_per_interpretation_with_two_evidence_rows":100.0,"seconds_per_interpretation":0.0001},"projection":{"full_premium_discount_interpretations":pf["definition_cardinality_current_engine"]["ict_premium_discount_context"],"premium_projected_bytes_from_measured_sample":1000}};pb["report_hash"]=stable_hash({k:v for k,v in pb.items() if k!="report_hash"});(td/"pb.json").write_text(json.dumps(pb))
   cg={"status":"PASS","report_hash":"","storage_gate_pass":True,"lossless_roundtrip_verified":True,"stage7_benchmark_report_hash":pb["report_hash"],"measured_compression_ratio":5.0,"required_compression_ratio_for_peak_gate":2.0};cg["report_hash"]=stable_hash({k:v for k,v in cg.items() if k!="report_hash"});(td/"cg.json").write_text(json.dumps(cg))
   sb={"status":"PASS","report_hash":"","stage7_preflight_report_hash":pf["report_hash"],"stage5_database_sha256":s5,"sample":{"bytes_per_logical_row":100.0,"seconds_per_interpretation":0.0001},"projection":{"projected_compressed_bytes":1000}};sb["report_hash"]=stable_hash({k:v for k,v in sb.items() if k!="report_hash"});(td/"sb.json").write_text(json.dumps(sb))
   report=run_plan(staging_db=staging,stage5_db=stage5,artifacts_root=ART,preflight_path=td/"pf.json",premium_benchmark_path=td/"pb.json",compression_gate_path=td/"cg.json",school_benchmark_path=td/"sb.json",output_root=td,expected_commit=_git_head(ART),safety_floor_gb=0,max_runtime_hours=1000,storage_safety_factor=1.5,runtime_safety_factor=1.5,report_path=td/"report.json",plan_path=td/"plan.json")
   self.assertEqual(report["status"],"PASS")
   self.assertTrue(report["full_annual_stage7_permitted_by_plan_gate"])
   self.assertFalse(report["stage7_authorized"]);self.assertFalse(report["stage7_auto_launch"])
   plan=json.loads((td/"plan.json").read_text())
   self.assertFalse(plan["execution_policy"]["stage7_auto_launch"])
   self.assertTrue(plan["execution_policy"]["oos_2024_forbidden"])
   self.assertGreater(plan["shard_count"],0)
   self.assertEqual(plan["expected_cardinality"]["school_core_interpretations"],sum(pf["definition_cardinality_current_engine"][k] for k in ("ict_liquidity_sweep_displacement","ict_mss_fvg_delivery","ict_return_to_imbalance_fvg_ce_current_engine","ict_block_delivery_context","ict_draw_on_liquidity_context")))

if __name__=="__main__":unittest.main()
