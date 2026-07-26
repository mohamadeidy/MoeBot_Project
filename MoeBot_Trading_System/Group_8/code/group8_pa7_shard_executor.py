#!/usr/bin/env python3
"""Deterministic free-only PA7 causal-root shard executor for Group 8.

This module changes physical execution only. It imports the frozen Group8 engine,
filters the PA7 boundary catalog by immutable causal root, and emits exactly the
same PA7 / failed-breakout / retest rows for those roots. Immutable IDs/hashes
remain reference-engine IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from moebot_group8_engine_v0_8_0 import EXPECTED_LOGICAL_LINEAGE, Group8Engine, Group8InvariantError, sha256_file

CHAIN_DEFINITIONS=("pa_breakout_exact","pa_breakout_point_buffer","pa_breakout_atr_buffer","pa_failed_breakout","pa_retest")
EXPECTED_STORAGE_CONTRACT="d9d46f4f09c2558ef1373084be4aba8ec9c9744b8e0a6861c32b841f1f59e34a"
EXPECTED_DESIGN_FREEZE="213a7f6384462bc00e44366062d56edf1f5ed9c2bcce6307e44aff3bf2f0ea7a"
EXPECTED_ENGINE_SHA="ab674be7601aed36d4d9e83eaedf7a1855f8e86297f7e9fc50ba01a9200dd4a0"
PA7_REQUIRED_TABLES:dict[str,tuple[str,...]]={"source":("bars",),"group4":("zones","zone_transitions","zone_interactions"),"group5":("liquidity_pools",),"group6":("fvg_events","fvg_state_transitions","imbalance_variants","liquidity_voids","bpr_relations"),"group7":("institutional_zones","zone_state_transitions")}

def _quoted(name:str)->str:return '"'+name.replace('"','""')+'"'
def canonical_json(value:Any)->str:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
def stable_hash(value:Any)->str:return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def partition_root_id(boundary:Mapping[str,Any])->str:return f"{boundary['group']}:{boundary['type']}:{boundary['id']}"
def bucket_for_root(root_id:str,bucket_count:int)->int:
    if bucket_count<=0 or bucket_count&(bucket_count-1):raise ValueError("bucket_count must be a positive power of two")
    return int(hashlib.sha256(root_id.encode()).hexdigest()[:16],16)%bucket_count
def epoch_month(epoch:int)->str:return datetime.fromtimestamp(int(epoch),tz=timezone.utc).strftime("%Y-%m")

class _ExtremaTree:
    def __init__(self,bars:list[Any])->None:
        n=1
        while n<len(bars):n<<=1
        self.n=n;inf=float("inf");self.min_close=[inf]*(2*n);self.max_close=[-inf]*(2*n);self.min_high=[inf]*(2*n);self.max_low=[-inf]*(2*n);self.max_high=[-inf]*(2*n);self.min_low=[inf]*(2*n)
        for i,bar in enumerate(bars):p=n+i;self.min_close[p]=self.max_close[p]=float(bar.close);self.min_high[p]=self.max_high[p]=float(bar.high);self.max_low[p]=self.min_low[p]=float(bar.low)
        for p in range(n-1,0,-1):l,r=p*2,p*2+1;self.min_close[p]=min(self.min_close[l],self.min_close[r]);self.max_close[p]=max(self.max_close[l],self.max_close[r]);self.min_high[p]=min(self.min_high[l],self.min_high[r]);self.max_low[p]=max(self.max_low[l],self.max_low[r]);self.max_high[p]=max(self.max_high[l],self.max_high[r]);self.min_low[p]=min(self.min_low[l],self.min_low[r])
        self.length=len(bars)
    def _first(self,start:int,possible,leaf_ok)->int|None:
        if start>=self.length:return None
        def visit(node:int,left:int,right:int)->int|None:
            if right<=start or left>=self.length or not possible(node):return None
            if right-left==1:return left if leaf_ok(node) else None
            mid=(left+right)//2;hit=visit(node*2,left,mid);return hit if hit is not None else visit(node*2+1,mid,right)
        return visit(1,0,self.n)
    def first_close_below(self,start:int,level:float)->int|None:return self._first(start,lambda p:self.min_close[p]<level,lambda p:self.min_close[p]<level)
    def first_close_above(self,start:int,level:float)->int|None:return self._first(start,lambda p:self.max_close[p]>level,lambda p:self.max_close[p]>level)
    def first_non_overlap(self,start:int,lo:float,hi:float)->int|None:return self._first(start,lambda p:self.min_high[p]<lo or self.max_low[p]>hi,lambda p:self.min_high[p]<lo or self.max_low[p]>hi)
    def first_overlap(self,start:int,lo:float,hi:float)->int|None:return self._first(start,lambda p:self.max_high[p]>=lo and self.min_low[p]<=hi,lambda p:self.max_high[p]>=lo and self.min_low[p]<=hi)

@dataclass(frozen=True)
class ShardSpec:
    year:int;symbol:str;timeframe:str;root_month:str|None;bucket_count:int;bucket_index:int
    def validate(self)->None:
        if self.bucket_count<=0 or self.bucket_count&(self.bucket_count-1):raise ValueError("bucket_count must be a positive power of two")
        if not 0<=self.bucket_index<self.bucket_count:raise ValueError("bucket_index outside bucket_count")
        if self.root_month is not None:
            year,month=self.root_month.split("-")
            if int(year)!=self.year or not 1<=int(month)<=12:raise ValueError("root_month must be YYYY-MM within shard year")

class PA7ShardEngine(Group8Engine):
    def __init__(self,*,spec:ShardSpec,**kwargs:Any)->None:
        self.shard_spec=spec;spec.validate();super().__init__(**kwargs);contract=json.loads((self.root/"SHARDED_STORAGE_CONTRACT.json").read_text());freeze=json.loads((self.root/"DESIGN_FREEZE_MANIFEST.json").read_text())
        if contract.get("storage_contract_hash")!=EXPECTED_STORAGE_CONTRACT:raise RuntimeError("unexpected sharded storage contract")
        if freeze.get("design_freeze_hash")!=EXPECTED_DESIGN_FREEZE:raise RuntimeError("unexpected sharded design freeze")
        if self.year==2024:
            status=json.loads((self.root/"STATUS.json").read_text())
            if status.get("annual_execution_2024_authorized") is not True:raise RuntimeError("2024 OOS is not authorized")
    def _verify_staging_contract(self)->None:
        manifest={r["key"]:r["value"] for r in self.input.execute("SELECT key,value FROM stage_manifest")};common={"year":str(self.year),"engine_version":self.config["engine_version"],"schema_version":self.config["schema_version"],"config_id":self.config["config_id"],"logical_dependency_lineage_id":EXPECTED_LOGICAL_LINEAGE,"adapter_map_hash":self.adapter["adapter_map_hash"]}
        for key,expected in common.items():
            if manifest.get(key)!=expected:raise Group8InvariantError(f"staging manifest {key} mismatch: {manifest.get(key)!r} != {expected!r}")
        if manifest.get("status")!="PASS":raise Group8InvariantError("staging materialization is not PASS")
        tables=self._tables(self.input);compact=manifest.get("materialization_scope")=="PA7_COMPACT_V1";required_tables={"stage_manifest","staging_metadata"}
        if compact:
            for group,names in PA7_REQUIRED_TABLES.items():required_tables.update(f"{group}__{name}" for name in names)
        else:
            for group,group_adapters in self.adapter["adapters"].items():required_tables.update(f"{group}__{name}" for name in group_adapters)
        missing=sorted(required_tables-tables)
        if missing:raise Group8InvariantError(f"staging tables missing: {missing}")
        targets=PA7_REQUIRED_TABLES if compact else {g:tuple(v) for g,v in self.adapter["adapters"].items()}
        for group,names in targets.items():
            for name in names:
                rec=self.adapter["adapters"][group][name];table=f"{group}__{name}";actual={r[1] for r in self.input.execute(f"PRAGMA table_info({_quoted(table)})")};missing_cols=sorted(set(rec["required_columns"])-actual)
                if missing_cols:raise Group8InvariantError(f"{table} missing columns: {missing_cols}")
        if compact:
            identities=json.loads(manifest.get("database_identities_json","{}"));consumed=set(json.loads(manifest.get("materialized_groups_json","[]")))
            if set(identities)!={"source","group2","group3","group4","group5","group6","group7"}:raise Group8InvariantError("compact staging identity registry incomplete")
            if consumed!=set(PA7_REQUIRED_TABLES):raise Group8InvariantError("compact staging materialized group set mismatch")
    def retain_target_timeframe(self)->None:
        key=(self.shard_spec.symbol,self.shard_spec.timeframe);bars=self.bars_by_tf.get(key)
        if not bars:raise RuntimeError(f"no bars for shard {key}")
        self.bars_by_tf={key:bars};self.bar_pos={bar.id:(key,i) for i,bar in enumerate(bars)}
    def _root_selected(self,boundary:Mapping[str,Any])->bool:
        if self.shard_spec.root_month is not None and epoch_month(int(boundary["event"]))!=self.shard_spec.root_month:return False
        return bucket_for_root(partition_root_id(boundary),self.shard_spec.bucket_count)==self.shard_spec.bucket_index
    def _pa7_boundary_catalog(self,symbol:str,tf:str)->list[dict[str,Any]]:
        if symbol!=self.shard_spec.symbol or tf!=self.shard_spec.timeframe:return []
        return [b for b in super()._pa7_boundary_catalog(symbol,tf) if self._root_selected(b)]
    def process_failed_breakouts_and_retests_fast(self)->None:
        key=(self.shard_spec.symbol,self.shard_spec.timeframe);bars=self.bars_by_tf[key];tree=_ExtremaTree(bars);retest_cache:dict[tuple[int,float,float],int|None]={};sql="""SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer') AND symbol=? AND timeframe=? ORDER BY availability_time,candidate_id"""
        for br in self.out.execute(sql,key):
            src=self._bar_by_id(br["source_bar_id"])
            if src is None:continue
            _,idx=self.bar_pos[src.id];feats=json.loads(br["features_json"]);level=float(feats["locked_level"]);direction=str(br["direction"]);fail_idx=tree.first_close_below(idx+1,level) if direction=="bullish" else tree.first_close_above(idx+1,level)
            if fail_idx is not None:
                failed=bars[fail_idx];self._write_pattern("pa_failed_breakout",symbol=src.symbol,timeframe=src.timeframe,direction="bearish" if direction=="bullish" else "bullish",source_bar_id=failed.id,related_source_bar_id=src.id,event_time=failed.close_time,confirmation_time=failed.close_time,availability_time=failed.available_at,lower=level,upper=level,features={"breakout_candidate_id":br["candidate_id"],"boundary_identity":feats["boundary_identity"],"locked_level":level},upstream_refs=[self._ref("group8","price_action_pattern_candidate",br["candidate_id"],br["availability_time"]),self._ref("source","bars",failed.id,failed.available_at,event_time=failed.close_time,timeframe=src.timeframe)])
            band_lo=band_hi=level
            if br["definition_id"]=="pa_breakout_point_buffer":inc=float(feats.get("verified_increment",0));band_lo,band_hi=level-inc,level+inc
            elif br["definition_id"]=="pa_breakout_atr_buffer":buf=float(feats.get("buffer",0));band_lo,band_hi=level-buf,level+buf
            cache_key=(idx,band_lo,band_hi)
            if cache_key in retest_cache:ret_idx=retest_cache[cache_key]
            else:non_idx=tree.first_non_overlap(idx+1,band_lo,band_hi);ret_idx=tree.first_overlap(non_idx+1,band_lo,band_hi) if non_idx is not None else None;retest_cache[cache_key]=ret_idx
            if ret_idx is not None:
                ret=bars[ret_idx];max_pen=max(0.0,min(ret.high,band_hi)-max(ret.low,band_lo));duration=ret_idx-idx;self._write_pattern("pa_retest",symbol=src.symbol,timeframe=src.timeframe,direction=direction,source_bar_id=ret.id,related_source_bar_id=src.id,event_time=ret.close_time,confirmation_time=ret.close_time,availability_time=ret.available_at,lower=band_lo,upper=band_hi,features={"breakout_candidate_id":br["candidate_id"],"touch":True,"penetration":max_pen,"close_side":"above" if ret.close>level else "below" if ret.close<level else "equal","duration_bars":duration,"max_penetration":max_pen,"right_censored":False},upstream_refs=[self._ref("group8","price_action_pattern_candidate",br["candidate_id"],br["availability_time"]),self._ref("source","bars",ret.id,ret.available_at,event_time=ret.close_time,timeframe=src.timeframe)])
        self.out.commit()

def _copy_table(src:sqlite3.Connection,dst:sqlite3.Connection,table:str,where:str="",params:Iterable[Any]=())->None:
    info=src.execute(f'PRAGMA table_info("{table}")').fetchall();cols=[row[1] for row in info]
    if not cols:return
    select=f'SELECT {",".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"'+((" WHERE "+where) if where else "");marks=",".join("?" for _ in cols);insert=f'INSERT INTO "{table}" ({",".join(chr(34)+c+chr(34) for c in cols)}) VALUES ({marks})';dst.executemany(insert,src.execute(select,tuple(params)))
def logical_table_hash(con:sqlite3.Connection,table:str,id_col:str,hash_col:str)->str:
    h=hashlib.sha256()
    for row in con.execute(f'SELECT "{id_col}","{hash_col}" FROM "{table}" ORDER BY "{id_col}"'):h.update(str(row[0]).encode());h.update(b"\0");h.update(str(row[1]).encode());h.update(b"\n")
    return h.hexdigest()
def export_chain_shard(work_db:Path,output_db:Path,artifacts_root:Path,spec:ShardSpec)->dict[str,Any]:
    if output_db.exists():output_db.unlink()
    src=sqlite3.connect(work_db);src.row_factory=sqlite3.Row;dst=sqlite3.connect(output_db);dst.row_factory=sqlite3.Row
    try:
        dst.execute("PRAGMA foreign_keys=OFF");dst.executescript((artifacts_root/"02_SCHEMA.sql").read_text())
        for table in ("config_registry","school_registry","pattern_definition_registry","interpretation_definition_registry","dataset_registry","dependency_registry","metadata"):_copy_table(src,dst,table)
        defs=CHAIN_DEFINITIONS;q=",".join("?" for _ in defs);_copy_table(src,dst,"price_action_pattern_candidate",f"definition_id IN ({q})",defs);ids=[r[0] for r in dst.execute("SELECT candidate_id FROM price_action_pattern_candidate")]
        for start in range(0,len(ids),500):
            chunk=ids[start:start+500]
            if chunk:q2=",".join("?" for _ in chunk);_copy_table(src,dst,"price_action_pattern_state",f"candidate_id IN ({q2})",chunk)
        dst.commit();dst.execute("PRAGMA foreign_keys=ON");qc=dst.execute("PRAGMA quick_check").fetchone()[0];ic=dst.execute("PRAGMA integrity_check").fetchone()[0];fk=dst.execute("PRAGMA foreign_key_check").fetchall()
        if qc!="ok" or ic!="ok" or fk:raise RuntimeError(f"shard sqlite validation failed qc={qc} ic={ic} fk={len(fk)}")
        counts={t:dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in ("price_action_pattern_candidate","price_action_pattern_state")};by_def={r[0]:r[1] for r in dst.execute("SELECT definition_id,COUNT(*) FROM price_action_pattern_candidate GROUP BY definition_id")};times=dst.execute("SELECT MIN(event_time),MAX(event_time),MIN(availability_time),MAX(availability_time) FROM price_action_pattern_candidate").fetchone();logical={"price_action_pattern_candidate":logical_table_hash(dst,"price_action_pattern_candidate","candidate_id","candidate_hash"),"price_action_pattern_state":logical_table_hash(dst,"price_action_pattern_state","state_event_id","state_hash")}
    finally:dst.close();src.close()
    freeze=json.loads((artifacts_root/"DESIGN_FREEZE_MANIFEST.json").read_text());contract=json.loads((artifacts_root/"SHARDED_STORAGE_CONTRACT.json").read_text());shard_payload={"family":"pa7_chain","year":spec.year,"symbol":spec.symbol,"timeframe":spec.timeframe,"causal_root_window":spec.root_month or "ALL","partition_root_rule":contract["partitioning"]["partition_root_rules"]["pa7_chain"],"bucket_index":spec.bucket_index,"bucket_count":spec.bucket_count};shard_id="g8shard_"+stable_hash(shard_payload);manifest={"format_version":1,"status":"PASS","shard_id":shard_id,**shard_payload,"file_size_bytes":output_db.stat().st_size,"sha256":sha256_file(output_db),"compressed_sha256":None,"table_row_counts":counts,"table_logical_sha256":logical,"definition_coverage":by_def,"min_event_time":times[0],"max_event_time":times[1],"min_availability_time":times[2],"max_availability_time":times[3],"upstream_lineage_id":freeze["logical_dependency_lineage_id"],"engine_sha256":sha256_file(artifacts_root/"code/moebot_group8_engine_v0_8_0.py"),"design_freeze_hash":freeze["design_freeze_hash"],"storage_contract_hash":contract["storage_contract_hash"],"oos_2024_accessed":spec.year==2024};manifest["manifest_hash"]=stable_hash(manifest);return manifest
def run_shard(*,staging_db:Path,work_db:Path,output_db:Path,artifacts_root:Path,spec:ShardSpec,manifest_path:Path)->dict[str,Any]:
    if spec.year==2024:
        status=json.loads((artifacts_root/"STATUS.json").read_text())
        if status.get("annual_execution_2024_authorized") is not True:raise RuntimeError("2024 OOS is forbidden")
    if work_db.exists():work_db.unlink()
    engine=PA7ShardEngine(staging_db=staging_db,output_db=work_db,artifacts_root=artifacts_root,year=spec.year,symbol=spec.symbol,spec=spec)
    try:engine.load_bars();engine.retain_target_timeframe();engine.process_bounded_ranges();engine.process_breakouts();engine.process_failed_breakouts_and_retests_fast()
    finally:engine.close()
    manifest=export_chain_shard(work_db,output_db,artifacts_root,spec);manifest_path.parent.mkdir(parents=True,exist_ok=True);manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n");return manifest
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--work-db",type=Path,required=True);p.add_argument("--output-db",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--year",type=int,required=True);p.add_argument("--symbol",required=True);p.add_argument("--timeframe",required=True);p.add_argument("--root-month");p.add_argument("--bucket-count",type=int,required=True);p.add_argument("--bucket-index",type=int,required=True);p.add_argument("--manifest",type=Path,required=True);a=p.parse_args();spec=ShardSpec(a.year,a.symbol,a.timeframe,a.root_month,a.bucket_count,a.bucket_index);report=run_shard(staging_db=a.staging_db.resolve(),work_db=a.work_db.resolve(),output_db=a.output_db.resolve(),artifacts_root=a.artifacts_root.resolve(),spec=spec,manifest_path=a.manifest.resolve());print(json.dumps(report,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
