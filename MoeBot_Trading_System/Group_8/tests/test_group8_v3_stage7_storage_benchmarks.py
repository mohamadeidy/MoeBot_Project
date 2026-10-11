#!/usr/bin/env python3
from __future__ import annotations
import json,shutil,tempfile,unittest
from pathlib import Path
from group8_segmented_annual_core import run_segment
from group8_v3_stage7_compression_gate import run_gate
from group8_v3_stage7_school_core_benchmark import run_benchmark
from moebot_group8_engine_v0_8_0 import sha256_file
from test_group8_engine_v0_8_0 import ART,make_stage
SYMBOL="XAUUSD_"

class Stage7StorageBenchTests(unittest.TestCase):
 def _fixture(self,td:Path):
  staging=td/"staging.sqlite";stage5=td/"stage5.sqlite";make_stage(staging)
  run_segment(staging_db=staging,output_db=stage5,artifacts_root=ART,year=2023,symbol=SYMBOL,start=0,end=5)
  return staging,stage5
 def test_school_core_benchmark_passes_and_compresses(self):
  zstd=shutil.which("zstd")
  if not zstd:self.skipTest("zstd unavailable")
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);staging,stage5=self._fixture(td)
   pf={"status":"PASS","stage5_database_sha256":sha256_file(stage5),"stage6_release_hash":"r","stage6_union_report_hash":"u","report_hash":"p","definition_cardinality_current_engine":{"ict_liquidity_sweep_displacement":1,"ict_mss_fvg_delivery":1,"ict_premium_discount_context":1,"ict_return_to_imbalance_fvg_ce_current_engine":1,"ict_block_delivery_context":1,"ict_draw_on_liquidity_context":1}}
   p=td/"pf.json";p.write_text(json.dumps(pf))
   r=run_benchmark(staging_db=staging,stage5_db=stage5,preflight_report=p,artifacts_root=ART,output_root=td/"bench",zstd_exe=Path(zstd),output=td/"school.json",symbol=SYMBOL,windows_per_timeframe=1,chunk_interpretations=2,runtime_safety_factor=1.5)
   self.assertEqual(r["status"],"PASS");self.assertFalse(r["stage7_authorized"]);self.assertGreater(r["sample"]["compressed_bytes"],0)
   self.assertTrue(all(not (td/"bench"/"raw"/f"school_core_{s['timeframe']}_{s['root_month']}.sqlite").exists() for s in r["shards"]))
 def test_compression_gate_roundtrip(self):
  zstd=shutil.which("zstd")
  if not zstd:self.skipTest("zstd unavailable")
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db=td/"sample.sqlite";db.write_bytes((b"abc123"*100000))
   b={"status":"PASS","report_hash":"b","projection":{"projected_total_bytes_with_storage_safety_factor":db.stat().st_size,"projected_max_range_chain_shard_bytes":1024}}
   bp=td/"b.json";bp.write_text(json.dumps(b))
   r=run_gate(benchmark_report=bp,sample_db=db,zstd_exe=Path(zstd),archive=td/"s.zst",output=td/"gate.json",level=6,safety_floor_gb=0.0)
   self.assertEqual(r["status"],"PASS");self.assertTrue(r["lossless_roundtrip_verified"]);self.assertEqual(r["sample_raw_sha256"],r["sample_roundtrip_sha256"])

if __name__=="__main__":unittest.main()
