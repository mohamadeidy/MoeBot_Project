#!/usr/bin/env python3
"""Assemble the verified V3 Stage5+Stage6+Stage7 non-PA7 annual core.

This is a physical materialization bridge only. It does not recompute or alter
frozen domain semantics. It rebuilds the logical Stage5 boundary without
interrupted legacy Stage6 contamination, inserts only the already-verified
official Stage6 and Stage7 rows, and requires exact count/fingerprint parity
with their union reports before publishing the base core used by the existing
PA7-derived/global finalization pipeline.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,shutil,sqlite3,subprocess
from pathlib import Path
from typing import Any,Iterable

from group8_sqlite_fingerprint import fingerprint
from group8_v3_stage6_range_shard_executor import STAGE6_DEFINITIONS,stable_hash
from group8_v3_stage7_shard_executor import STAGE7_DEFINITIONS
from moebot_group8_engine_v0_8_0 import sha256_file

DOMAIN_COPY_ORDER=(
 "metadata","config_registry","dataset_registry","dependency_registry","school_registry",
 "pattern_definition_registry","interpretation_definition_registry",
 "price_action_pattern_candidate","price_action_pattern_state","school_interpretation",
 "shared_evidence","conflicting_evidence","narrative_hypothesis",
 "hypothesis_lifecycle_event","multi_timeframe_context_relation","evidence_chain",
 "invalidation_record","group8_audit_evidence","processing_checkpoint",
)
MERGE_TABLES=("school_interpretation","evidence_chain")
REPLACED_INTERPRETATION_DEFINITIONS=tuple(STAGE6_DEFINITIONS)+tuple(STAGE7_DEFINITIONS)
DEFAULT_DISK_SAFETY_FLOOR_GB=120.0
DEFAULT_SIZE_SAFETY_FACTOR=1.15
STAGE7_SCRATCH_RESERVE_BYTES=2_500_000_000

def _verify(rec:dict[str,Any],field:str,label:str)->None:
 if field not in rec:raise RuntimeError(f"{label}:missing_{field}")
 x=dict(rec);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{label}:{field}_mismatch")

def _load(path:Path,field:str,label:str)->dict[str,Any]:
 r=json.loads(path.read_text());_verify(r,field,label);return r

def _cols(con:sqlite3.Connection,schema:str,table:str)->tuple[str,...]:
 return tuple(str(r[1]) for r in con.execute(f'PRAGMA {schema}.table_info("{table}")'))

def _tables(con:sqlite3.Connection,schema:str="main")->set[str]:
 return {str(r[0]) for r in con.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

def _hash_rows(con:sqlite3.Connection,table:str,idc:str,hc:str,where:str="",params:Iterable[Any]=())->tuple[int,str]:
 h=hashlib.sha256();n=0;q=f'SELECT "{idc}","{hc}" FROM "{table}"'
 if where:q+=" WHERE "+where
 q+=f' ORDER BY "{idc}"'
 for rid,rh in con.execute(q,tuple(params)):
  h.update(str(rid).encode());h.update(b"\0");h.update(str(rh).encode());h.update(b"\n");n+=1
 return n,h.hexdigest()

def _release_raw_bytes(release:dict[str,Any],*,stage:int)->int:
 if stage==6:
  if release.get("total_output_bytes") is not None:return int(release["total_output_bytes"])
  vals=[int(x.get("file_size_bytes",-1)) for x in release.get("shards",[])]
  if not vals or any(x<0 for x in vals):raise RuntimeError("Stage6 release missing raw byte accounting")
  return sum(vals)
 if stage==7:
  if release.get("total_raw_bytes") is None:raise RuntimeError("Stage7 release missing total_raw_bytes")
  return int(release["total_raw_bytes"])
 raise ValueError("unsupported stage")

def _storage_projection(*,stage5_bytes:int,stage6_bytes:int,stage7_bytes:int,size_safety_factor:float)->int:
 if min(stage5_bytes,stage6_bytes,stage7_bytes)<0:raise ValueError("negative storage component")
 if float(size_safety_factor)<1.0:raise ValueError("size_safety_factor must be >=1")
 return int(math.ceil((int(stage5_bytes)+int(stage6_bytes)+int(stage7_bytes))*float(size_safety_factor)))

def _storage_preflight(*,stage5_db:Path,stage6_release:dict[str,Any],stage7_release:dict[str,Any],output_db:Path,work_root:Path,disk_safety_floor_gb:float,size_safety_factor:float)->dict[str,Any]:
 if float(disk_safety_floor_gb)<0:raise ValueError("disk_safety_floor_gb must be >=0")
 stage5_bytes=int(stage5_db.stat().st_size);stage6_bytes=_release_raw_bytes(stage6_release,stage=6);stage7_bytes=_release_raw_bytes(stage7_release,stage=7)
 projected=_storage_projection(stage5_bytes=stage5_bytes,stage6_bytes=stage6_bytes,stage7_bytes=stage7_bytes,size_safety_factor=size_safety_factor)
 output_db.parent.mkdir(parents=True,exist_ok=True);work_root.mkdir(parents=True,exist_ok=True)
 output_usage=shutil.disk_usage(output_db.parent);replace_credit=output_db.stat().st_size if output_db.exists() else 0
 output_available=int(output_usage.free)+int(replace_credit);floor=int(float(disk_safety_floor_gb)*(1024**3))
 same_volume=os.stat(output_db.parent).st_dev==os.stat(work_root).st_dev
 output_required=projected+floor+(STAGE7_SCRATCH_RESERVE_BYTES if same_volume else 0)
 scratch_available=output_available if same_volume else int(shutil.disk_usage(work_root).free)
 scratch_required=0 if same_volume else STAGE7_SCRATCH_RESERVE_BYTES
 rec={"stage5_bytes":stage5_bytes,"stage6_raw_bytes":stage6_bytes,"stage7_raw_bytes":stage7_bytes,
      "size_safety_factor":float(size_safety_factor),"projected_output_upper_bound_bytes":projected,
      "disk_safety_floor_bytes":floor,"stage7_scratch_reserve_bytes":STAGE7_SCRATCH_RESERVE_BYTES,
      "output_available_bytes":output_available,"output_required_bytes":output_required,
      "work_volume_separate":not same_volume,"scratch_available_bytes":scratch_available,
      "scratch_required_bytes":scratch_required,
      "storage_gate_pass":output_available>=output_required and scratch_available>=scratch_required}
 if not rec["storage_gate_pass"]:raise RuntimeError("V3 base-core storage preflight failed:"+json.dumps(rec,sort_keys=True))
 return rec

def _copy_stage5_logical(*,stage5_db:Path,output_db:Path,schema_sql:Path)->dict[str,int]:
 output_db.unlink(missing_ok=True);output_db.parent.mkdir(parents=True,exist_ok=True)
 out=sqlite3.connect(output_db);out.row_factory=sqlite3.Row
 try:
  out.execute("PRAGMA foreign_keys=OFF");out.execute("PRAGMA journal_mode=DELETE");out.execute("PRAGMA synchronous=NORMAL")
  out.executescript(schema_sql.read_text());out.execute("ATTACH DATABASE ? AS src",(str(stage5_db.resolve()),))
  src_tables=_tables(out,"src");dst_tables=_tables(out,"main")
  missing=[t for t in DOMAIN_COPY_ORDER if t in dst_tables and t not in src_tables]
  if missing:raise RuntimeError("Stage5 missing schema tables:"+",".join(missing))
  replaced=REPLACED_INTERPRETATION_DEFINITIONS;qs=",".join("?" for _ in replaced)
  q6=",".join("?" for _ in STAGE6_DEFINITIONS);q7=",".join("?" for _ in STAGE7_DEFINITIONS)
  excluded6=int(out.execute(f"SELECT COUNT(*) FROM src.school_interpretation WHERE definition_id IN ({q6})",STAGE6_DEFINITIONS).fetchone()[0])
  excluded7=int(out.execute(f"SELECT COUNT(*) FROM src.school_interpretation WHERE definition_id IN ({q7})",STAGE7_DEFINITIONS).fetchone()[0])
  excluded_evidence=int(out.execute(f"""SELECT COUNT(*) FROM src.evidence_chain e
    WHERE e.subject_id IN (SELECT interpretation_id FROM src.school_interpretation WHERE definition_id IN ({qs}))
       OR (lower(e.source_group)='group8' AND e.source_id IN
          (SELECT interpretation_id FROM src.school_interpretation WHERE definition_id IN ({qs})))""",tuple(replaced)*2).fetchone()[0])
  for table in DOMAIN_COPY_ORDER:
   if table not in dst_tables:continue
   sc=_cols(out,"src",table);dc=_cols(out,"main",table)
   if sc!=dc:raise RuntimeError(f"Stage5 schema drift:{table}")
   cols=",".join(f'"{c}"' for c in dc)
   if table=="school_interpretation":
    out.execute(f'INSERT INTO main."{table}"({cols}) SELECT {cols} FROM src."{table}" WHERE definition_id NOT IN ({qs})',replaced)
   elif table=="evidence_chain":
    out.execute(f"""INSERT INTO main."{table}"({cols}) SELECT {cols} FROM src."{table}" e
      WHERE e.subject_id NOT IN (SELECT interpretation_id FROM src.school_interpretation WHERE definition_id IN ({qs}))
        AND NOT (lower(e.source_group)='group8' AND e.source_id IN
          (SELECT interpretation_id FROM src.school_interpretation WHERE definition_id IN ({qs})))""",tuple(replaced)*2)
   else:
    out.execute(f'INSERT INTO main."{table}"({cols}) SELECT {cols} FROM src."{table}"')
  # Stage5 is a logical boundary. Any other record depending on removed legacy
  # Stage6/Stage7 IDs would make that boundary ambiguous and must fail closed.
  out.execute("CREATE TEMP TABLE excluded_v3_ids(id TEXT PRIMARY KEY)")
  out.execute(f"INSERT INTO excluded_v3_ids SELECT interpretation_id FROM src.school_interpretation WHERE definition_id IN ({qs})",replaced)
  checks={
   "candidate_upstream":"""SELECT COUNT(*) FROM price_action_pattern_candidate p,json_each(p.upstream_refs_json) j
     WHERE lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
       AND CAST(json_extract(j.value,'$.source_id') AS TEXT) IN (SELECT id FROM excluded_v3_ids)""",
   "interpretation_upstream":"""SELECT COUNT(*) FROM school_interpretation p,json_each(p.upstream_refs_json) j
     WHERE lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
       AND CAST(json_extract(j.value,'$.source_id') AS TEXT) IN (SELECT id FROM excluded_v3_ids)""",
   "hypothesis_upstream":"""SELECT COUNT(*) FROM narrative_hypothesis p,json_each(p.upstream_refs_json) j
     WHERE lower(COALESCE(json_extract(j.value,'$.source_group'),''))='group8'
       AND CAST(json_extract(j.value,'$.source_id') AS TEXT) IN (SELECT id FROM excluded_v3_ids)""",
   "shared_subject":"""SELECT COUNT(*) FROM shared_evidence s,json_each(s.subject_ids_json) j
     WHERE CAST(j.value AS TEXT) IN (SELECT id FROM excluded_v3_ids)""",
   "conflict_subject":"""SELECT COUNT(*) FROM conflicting_evidence
     WHERE left_subject_id IN (SELECT id FROM excluded_v3_ids) OR right_subject_id IN (SELECT id FROM excluded_v3_ids)""",
   "lifecycle_source":"""SELECT COUNT(*) FROM hypothesis_lifecycle_event
     WHERE source_id IN (SELECT id FROM excluded_v3_ids)""",
   "mtf_endpoint":"""SELECT COUNT(*) FROM multi_timeframe_context_relation
     WHERE subject_id IN (SELECT id FROM excluded_v3_ids) OR object_id IN (SELECT id FROM excluded_v3_ids)""",
   "invalidation_endpoint":"""SELECT COUNT(*) FROM invalidation_record
     WHERE subject_id IN (SELECT id FROM excluded_v3_ids) OR source_id IN (SELECT id FROM excluded_v3_ids)""",
  }
  contaminated={k:int(out.execute(q).fetchone()[0]) for k,q in checks.items()}
  if any(contaminated.values()):raise RuntimeError(f"Stage5 has descendants of legacy Stage6/Stage7 contamination:{contaminated}")
  post_stage5_cp=int(out.execute("SELECT COUNT(*) FROM processing_checkpoint WHERE stage IN ('wyckoff_core','ict_core') AND status='PASS'").fetchone()[0])
  if post_stage5_cp:raise RuntimeError("logical Stage5 copy contains post-Stage5 PASS checkpoints")
  out.commit();out.execute("DETACH DATABASE src");out.execute("PRAGMA foreign_keys=ON")
  fk=out.execute("PRAGMA foreign_key_check").fetchall()
  if fk:raise RuntimeError(f"Stage5 logical copy foreign-key errors:{len(fk)}")
  return {"stage6_contamination_interpretations_removed":excluded6,"stage7_contamination_interpretations_removed":excluded7,"replaced_contamination_evidence_removed":excluded_evidence}
 finally:out.close()

def _merge_db(out:sqlite3.Connection,db:Path)->dict[str,int]:
 out.execute("ATTACH DATABASE ? AS shard",(str(db.resolve()),));counts={}
 try:
  for table in MERGE_TABLES:
   if _cols(out,"main",table)!=_cols(out,"shard",table):raise RuntimeError(f"merge schema drift:{table}:{db}")
   cols=",".join(f'"{c}"' for c in _cols(out,"main",table))
   before=out.total_changes
   out.execute(f'INSERT OR ABORT INTO main."{table}"({cols}) SELECT {cols} FROM shard."{table}"')
   counts[table]=out.total_changes-before
  out.commit()
 finally:out.execute("DETACH DATABASE shard")
 return counts

def _resolve_stage6_db(entry:dict[str,Any],output_root:Path)->Path:
 p=Path(str(entry.get("database","")))
 if p.is_file():return p.resolve()
 alt=(output_root/"shards"/p.name).resolve()
 if alt.is_file():return alt
 raise RuntimeError(f"Stage6 shard missing:{p}")

def _verify_subset(out:sqlite3.Connection,defs:tuple[str,...],expected:dict[str,Any],label:str)->None:
 qs=",".join("?" for _ in defs)
 ids=f"SELECT interpretation_id FROM school_interpretation WHERE definition_id IN ({qs})"
 n,h=_hash_rows(out,"school_interpretation","interpretation_id","interpretation_hash",f"definition_id IN ({qs})",defs)
 en,eh=_hash_rows(out,"evidence_chain","evidence_chain_id","evidence_hash",f"subject_type='school_interpretation' AND subject_id IN ({ids})",defs)
 got={"school_interpretation":n,"evidence_chain":en};gh={"school_interpretation":h,"evidence_chain":eh}
 if got!= {k:int(v) for k,v in expected["table_row_counts"].items()}:raise RuntimeError(f"{label} count parity failed:{got}!={expected['table_row_counts']}")
 if gh!=expected["table_logical_sha256"]:raise RuntimeError(f"{label} logical fingerprint parity failed")

def assemble(*,stage5_db:Path,stage6_release_path:Path,stage6_union_path:Path,stage6_output_root:Path,stage7_release_path:Path,stage7_union_path:Path,stage7_output_root:Path,artifacts_root:Path,zstd_exe:Path,work_root:Path,output_db:Path,report_path:Path,disk_safety_floor_gb:float=DEFAULT_DISK_SAFETY_FLOOR_GB,size_safety_factor:float=DEFAULT_SIZE_SAFETY_FACTOR)->dict[str,Any]:
 s6r=_load(stage6_release_path,"release_hash","stage6_release");s6u=_load(stage6_union_path,"report_hash","stage6_union")
 s7r=_load(stage7_release_path,"release_hash","stage7_release");s7u=_load(stage7_union_path,"report_hash","stage7_union")
 if s6r.get("status")!="PASS" or s6u.get("status")!="PASS" or s7r.get("status")!="PASS" or s7u.get("status")!="PASS":raise RuntimeError("Stage6/7 evidence is not PASS")
 year=int(s6r.get("year",0));symbol=str(s6r.get("symbol",""))
 if year not in (2023,2024) or int(s6u.get("year",0))!=year or int(s7r.get("year",0))!=year or int(s7u.get("year",0))!=year:raise RuntimeError("Stage6/7 year lineage mismatch")
 if str(s6u.get("symbol",""))!=symbol or str(s7r.get("symbol",""))!=symbol or str(s7u.get("symbol",""))!=symbol:raise RuntimeError("Stage6/7 symbol lineage mismatch")
 stage5_sha=sha256_file(stage5_db)
 if any(x.get("stage5_database_sha256")!=stage5_sha for x in (s6r,s6u,s7r,s7u)):raise RuntimeError("Stage5 SHA lineage mismatch")
 if s6u.get("stage6_release_hash")!=s6r.get("release_hash"):raise RuntimeError("Stage6 release/union mismatch")
 if s7r.get("stage6_release_hash")!=s6r.get("release_hash") or s7r.get("stage6_union_report_hash")!=s6u.get("report_hash"):raise RuntimeError("Stage7 release not bound to Stage6")
 if s7u.get("stage7_release_hash")!=s7r.get("release_hash") or s7u.get("stage6_union_report_hash")!=s6u.get("report_hash"):raise RuntimeError("Stage7 union lineage mismatch")
 oos=(year==2024)
 if bool(s6u.get("oos_2024_accessed"))!=oos or bool(s7r.get("oos_2024_accessed"))!=oos or bool(s7u.get("oos_2024_accessed"))!=oos:raise RuntimeError("OOS flag/year mismatch")
 storage=_storage_preflight(stage5_db=stage5_db,stage6_release=s6r,stage7_release=s7r,output_db=output_db,work_root=work_root,disk_safety_floor_gb=disk_safety_floor_gb,size_safety_factor=size_safety_factor)
 cleanup=_copy_stage5_logical(stage5_db=stage5_db,output_db=output_db,schema_sql=artifacts_root/"02_SCHEMA.sql")
 out=sqlite3.connect(output_db);out.row_factory=sqlite3.Row
 try:
  out.execute("PRAGMA foreign_keys=OFF")
  merged6={"school_interpretation":0,"evidence_chain":0}
  for e in s6r.get("shards",[]):
   db=_resolve_stage6_db(e,stage6_output_root)
   if sha256_file(db)!=e.get("sha256") or db.stat().st_size!=int(e.get("file_size_bytes",-1)):raise RuntimeError(f"Stage6 shard identity mismatch:{db}")
   m=_merge_db(out,db)
   for k,v in m.items():merged6[k]+=v
  _verify_subset(out,tuple(STAGE6_DEFINITIONS),s6u,"Stage6")
  if merged6!={k:int(v) for k,v in s6u["table_row_counts"].items()}:raise RuntimeError("Stage6 inserted-row count mismatch")
  work_root.mkdir(parents=True,exist_ok=True);tmp=work_root/"v3_stage7_current.sqlite"
  merged7={"school_interpretation":0,"evidence_chain":0}
  try:
   for e in sorted(s7r.get("shards",[]),key=lambda x:int(x.get("ordinal",0))):
    arc=(stage7_output_root/str(e["archive_path"])).resolve()
    if not arc.is_file() or sha256_file(arc)!=e.get("compressed_sha256"):raise RuntimeError(f"Stage7 archive identity mismatch:{arc}")
    tmp.unlink(missing_ok=True)
    subprocess.run([str(zstd_exe),"-d","-f",str(arc),"-o",str(tmp)],check=True,stdout=subprocess.DEVNULL)
    if sha256_file(tmp)!=e.get("raw_sha256"):raise RuntimeError(f"Stage7 raw roundtrip mismatch:{arc}")
    m=_merge_db(out,tmp)
    for k,v in m.items():merged7[k]+=v
   _verify_subset(out,tuple(STAGE7_DEFINITIONS),s7u,"Stage7")
   if merged7!={k:int(v) for k,v in s7u["table_row_counts"].items()}:raise RuntimeError("Stage7 inserted-row count mismatch")
  finally:tmp.unlink(missing_ok=True)
  out.execute("PRAGMA foreign_keys=ON")
  qc=out.execute("PRAGMA quick_check").fetchone()[0];ic=out.execute("PRAGMA integrity_check").fetchone()[0];fk=out.execute("PRAGMA foreign_key_check").fetchall()
  if qc!="ok" or ic!="ok" or fk:raise RuntimeError(f"assembled base-core integrity failure qc={qc} ic={ic} fk={len(fk)}")
 finally:out.close()
 fp=fingerprint(output_db)
 rec={"format_version":1,"status":"PASS","scope":"GROUP8_V3_VERIFIED_NON_PA7_BASE_CORE","year":year,"symbol":symbol,
      "stage5_database_sha256":stage5_sha,"stage6_release_hash":s6r["release_hash"],"stage6_union_report_hash":s6u["report_hash"],
      "stage7_release_hash":s7r["release_hash"],"stage7_union_report_hash":s7u["report_hash"],"storage_preflight":storage,**cleanup,
      "stage6_official_rows_inserted":merged6,"stage7_official_rows_inserted":merged7,
      "database_sha256":fp["database_sha256"],"database_size_bytes":fp["database_size_bytes"],"logical_sha256":fp["logical_sha256"],
      "fingerprint_report_hash":fp["report_hash"],"quick_check":"ok","integrity_check":"ok","foreign_key_errors":0,
      "frozen_semantics_changed":False,"free_only":True,"paid_runner_used":False,"paid_service_used":False,"oos_2024_accessed":oos}
 rec["report_hash"]=stable_hash(rec);report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(rec,indent=2,sort_keys=True)+"\n");return rec

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--stage5-db",type=Path,required=True);p.add_argument("--stage6-release",type=Path,required=True);p.add_argument("--stage6-union",type=Path,required=True);p.add_argument("--stage6-output-root",type=Path,required=True);p.add_argument("--stage7-release",type=Path,required=True);p.add_argument("--stage7-union",type=Path,required=True);p.add_argument("--stage7-output-root",type=Path,required=True);p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--zstd-exe",type=Path,required=True);p.add_argument("--work-root",type=Path,required=True);p.add_argument("--output-db",type=Path,required=True);p.add_argument("--report",type=Path,required=True);p.add_argument("--disk-safety-floor-gb",type=float,default=DEFAULT_DISK_SAFETY_FLOOR_GB);p.add_argument("--size-safety-factor",type=float,default=DEFAULT_SIZE_SAFETY_FACTOR)
 a=p.parse_args();r=assemble(stage5_db=a.stage5_db.resolve(),stage6_release_path=a.stage6_release.resolve(),stage6_union_path=a.stage6_union.resolve(),stage6_output_root=a.stage6_output_root.resolve(),stage7_release_path=a.stage7_release.resolve(),stage7_union_path=a.stage7_union.resolve(),stage7_output_root=a.stage7_output_root.resolve(),artifacts_root=a.artifacts_root.resolve(),zstd_exe=a.zstd_exe.resolve(),work_root=a.work_root.resolve(),output_db=a.output_db.resolve(),report_path=a.report.resolve(),disk_safety_floor_gb=a.disk_safety_floor_gb,size_safety_factor=a.size_safety_factor);print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
