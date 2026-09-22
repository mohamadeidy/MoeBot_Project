#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
for g in range(9,16):sys.path.insert(0,str(ROOT/f"Group_{g}"/"code"))
from group9_causal_core import setup_id,transition
from group10_outcome_math import Bar,excursion,assert_post_availability
from group11_visual_recipe import make_recipe,deterministic_sample
from group12_partition_guard import chronological_partition,assert_partition_disjoint
from group13_policy_guard import validate_splits,validate_action,training_manifest
from group14_holdout_guard import verify_holdout
from group15_risk_gate import DeploymentGate,reserve_risk

class AlgorithmsTests(unittest.TestCase):
 def test_g9_transition_availability_is_max_evidence(self):
  sid=setup_id("X","M15","BUY",["b","a"],"d")
  x=transition(sid=sid,from_state="FORMING",to_state="READY",evidence=[{"id":"a","event_time":5,"availability_time":7},{"id":"b","event_time":8,"availability_time":9}],reason_code="synthetic")
  self.assertEqual(x["availability_time"],9);self.assertEqual(sid,setup_id("X","M15","BUY",["a","b"],"d"))
 def test_g10_rejects_preavailability_and_measures(self):
  bars=[Bar(10,101,99,100),Bar(20,103,100,102)]
  assert_post_availability(setup_availability_time=10,bars=bars)
  self.assertEqual(excursion(bars=bars,reference_price=100,direction="BUY")["mfe_price"],3)
  with self.assertRaises(ValueError):assert_post_availability(setup_availability_time=11,bars=bars)
 def test_g11_recipe_and_sampling_deterministic(self):
  r=[make_recipe(subject_type="s",subject_id=str(i),symbol="X",timeframe="M15",window_start=1,window_end=2,renderer_version="v",overlay_spec={},annotation_spec={})|{"stratum":"A"} for i in range(5)]
  self.assertEqual([x["recipe_id"] for x in deterministic_sample(r,n=2,seed="x",stratum_key="stratum")],[x["recipe_id"] for x in deterministic_sample(r,n=2,seed="x",stratum_key="stratum")])
 def test_g12_temporal_partition(self):
  self.assertEqual(chronological_partition(availability_time=10,discovery_end=10,confirmation_start=20),"DISCOVERY")
  self.assertEqual(chronological_partition(availability_time=15,discovery_end=10,confirmation_start=20),"PURGE_GAP")
  self.assertEqual(chronological_partition(availability_time=20,discovery_end=10,confirmation_start=20),"CONFIRMATION")
  with self.assertRaises(ValueError):assert_partition_disjoint({"x"},{"x"})
 def test_g13_holdout_disjoint(self):
  validate_splits(train={"a"},validation={"b"},final_holdout={"c"});validate_action("WAIT")
  self.assertFalse(training_manifest(train_ids={"a"},validation_ids={"b"},final_holdout_ids={"c"})["final_holdout_accessed"])
  with self.assertRaises(ValueError):validate_splits(train={"a"},validation={"a"},final_holdout=set())
 def test_g14_identity_guard(self):
  import hashlib
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"d";p.write_bytes(b"abc");h=hashlib.sha256(b"abc").hexdigest()
   self.assertEqual(verify_holdout(plan={"status":"FROZEN","untouched":True,"policy_hash":"p","dataset_sha256":h},dataset=p,policy_hash="p")["status"],"PASS")
 def test_g15_demo_before_live_and_risk_ceiling(self):
  self.assertFalse(DeploymentGate(True,False).authorize("LIVE"));self.assertTrue(DeploymentGate(True,False).authorize("DEMO"))
  self.assertEqual(reserve_risk(requested=5,open_reserved=10,account_equity=1000,catastrophic_fraction=.02)["open_reserved_after"],15)
  with self.assertRaises(ValueError):reserve_risk(requested=11,open_reserved=10,account_equity=1000,catastrophic_fraction=.02)
if __name__=="__main__":unittest.main(verbosity=2)
