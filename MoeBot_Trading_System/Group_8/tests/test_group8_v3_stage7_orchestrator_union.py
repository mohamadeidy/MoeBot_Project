#!/usr/bin/env python3
from __future__ import annotations
import json,shutil,sqlite3,tempfile,unittest
from pathlib import Path

from group8_segmented_annual_core import run_segment
from group8_v3_stage7_orchestrator import run_plan
from group8_v3_stage7_union_validator import validate_union
from group8_v3_stage7_shard_executor import Stage7ShardSpec,run_shard,STAGE7_DEFINITIONS
from group8_v3_stage6_range_shard_executor import epoch_month,stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file
from group8_annual_core_driver import AnnualCoreEngine
from test_group8_engine_v0_8_0 import ART,make_stage
SYMBOL="XAUUSD_"

def _hash_rows(db:Path,table:str,idc:str,hc:str,where:str="",params=()):
 import hashlib
 h=hashlib.sha256();con=sqlite3.connect(db)
 try:
  sql=f"SELECT {idc},{hc} FROM {table}"+((" WHERE "+where) if where else "")+f" ORDER BY {idc}"
  for rid,rh in con.execute(sql,params):
   h.update(str(rid).encode());h.update(b"\0");h.update(str(rh).encode());h.update(b"\n")
  return h.hexdigest()
 finally:con.close()

class Stage7OrchestratorUnionTests(unittest.TestCase):
 def test_orchestrator_release_and_streaming_union_match_reference(self):
  zstd=shutil.which("zstd")
  if not zstd:self.skipTest("zstd unavailable")
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);staging=td/"staging.sqlite";stage5=td/"stage5.sqlite";make_stage(staging)
   run_segment(staging_db=staging,output_db=stage5,artifacts_root=ART,year=2023,symbol=SYMBOL,start=0,end=5)
   ref=td/"ref.sqlite";shutil.copy2(stage5,ref)
   e=AnnualCoreEngine(staging_db=staging,output_db=ref,artifacts_root=ART,year=2023,symbol=SYMBOL)
   try:e.load_bars();e.process_ict()
   finally:e.close()
   con=sqlite3.connect(ref)
   try:
    q=",".join("?" for _ in STAGE7_DEFINITIONS)
    expected_i=int(con.execute(f"SELECT COUNT(*) FROM school_interpretation WHERE definition_id IN ({q})",STAGE7_DEFINITIONS).fetchone()[0])
    expected_e=int(con.execute(f"""SELECT COUNT(*) FROM evidence_chain e JOIN school_interpretation i ON i.interpretation_id=e.subject_id WHERE i.definition_id IN ({q})""",STAGE7_DEFINITIONS).fetchone()[0])
   finally:con.close()

   # Minimal complete shard plan from fixture windows, one bucket each.
   s5=sha256_file(stage5);shards=[]
   con=sqlite3.connect(stage5)
   try:
    rw={(str(tf),epoch_month(int(t))) for tf,t in con.execute("SELECT timeframe,event_time FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'")}
   finally:con.close()
   con=sqlite3.connect(staging)
   try:
    sw={(str(tf),epoch_month(int(t))) for tf,t in con.execute("SELECT timeframe,close_time FROM source__bars WHERE symbol=?",(SYMBOL,))}
   finally:con.close()
   for fam,wins in (("range_chain",rw),("school_core",sw)):
    for tf,m in sorted(wins):shards.append({"family":fam,"year":2023,"symbol":SYMBOL,"timeframe":tf,"root_month":m,"bucket_count":1,"bucket_index":0,"window_projected_raw_bytes_with_safety":1000000})
   freeze=json.loads((ART/"DESIGN_FREEZE_MANIFEST.json").read_text());contract=json.loads((ART/"SHARDED_STORAGE_CONTRACT.json").read_text())
   import subprocess
   commit=subprocess.check_output(["git","-C",str(ART.parent.parent),"rev-parse","HEAD"],text=True).strip()
   plan={"format_version":1,"scope":"fixture","status":"PASS","full_annual_stage7_permitted_by_plan_gate":True,"year":2023,"symbol":SYMBOL,"validated_commit":commit,"stage5_database_sha256":s5,"stage6_release_hash":"r6","stage6_union_report_hash":"u6","storage_contract_hash":contract["storage_contract_hash"],"design_freeze_hash":freeze["design_freeze_hash"],"shard_count":len(shards),"shards":shards,"expected_cardinality":{"total_stage7_interpretations":expected_i},"execution_policy":{"oos_2024_forbidden":True,"stage7_auto_launch":False,"zstd_level":6}}
   plan["plan_hash"]=stable_hash(plan);pp=td/"plan.json";pp.write_text(json.dumps(plan))
   out=td/"out";rel=run_plan(plan_path=pp,staging_db=staging,stage5_db=stage5,artifacts_root=ART,output_root=out,progress_path=td/"progress.json",release_path=td/"release.json",zstd_exe=Path(zstd),expected_commit=commit,safety_floor_gb=0.0,chunk_interpretations=2)
   self.assertEqual(rel["status"],"PASS");self.assertEqual(rel["table_row_counts"]["school_interpretation"],expected_i);self.assertEqual(rel["table_row_counts"]["evidence_chain"],expected_e)
   self.assertFalse(any((out/"raw").glob("*.sqlite")))
   u=validate_union(release_path=td/"release.json",plan_path=pp,stage5_db=stage5,output_root=out,work_root=td/"union_work",zstd_exe=Path(zstd),output_path=td/"union.json",fan_in=4)
   self.assertEqual(u["status"],"PASS");self.assertTrue(u["stage7_official_pass_eligible"]);self.assertEqual(u["duplicate_domain_id_count"],0)
   self.assertEqual(u["table_logical_sha256"]["school_interpretation"],_hash_rows(ref,"school_interpretation","interpretation_id","interpretation_hash",f"definition_id IN ({q})",STAGE7_DEFINITIONS))
   self.assertEqual(u["table_logical_sha256"]["evidence_chain"],_hash_rows(ref,"evidence_chain","evidence_chain_id","evidence_hash",f"subject_id IN (SELECT interpretation_id FROM school_interpretation WHERE definition_id IN ({q}))",STAGE7_DEFINITIONS))

if __name__=="__main__":unittest.main()
