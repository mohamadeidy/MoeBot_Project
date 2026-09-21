#!/usr/bin/env python3
"""End-to-end Group8 V3 continuation after the running 2023 Stage7 process exits.

This script starts only after the 2023 Stage7 release already exists. It performs,
in order, the remaining evidence-gated steps:
  2023 Stage7 streaming union -> Annual2023 finalization -> lossless Stage5 archive
  -> pre-2024 OOS freeze -> verified 2024 upstream materialization -> Stage0-5
  -> frozen-policy Stage6 -> Stage6 union -> frozen-policy Stage7 -> Stage7 union
  -> Annual2024 OOS finalization -> cross-year validation -> official Group8 closure.

It is idempotent at published evidence boundaries and never changes trading semantics.
If C: cannot safely retain 2024 Stage7 output above the 120 GiB floor, D: is used
only as a temporary cache of reconstructable derived Stage7 shards while 2024
staging+Stage5 remain on C:. After Annual2024 PASS, Stage5 is losslessly archived,
the D: shard tree is copied back to C: with archive SHA verification, and D: is
deleted only after the verified copy exists.
"""
from __future__ import annotations
import argparse,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from group8_v3_stage6_union_validator import validate_union as validate_stage6_union
from group8_v3_stage7_union_validator import validate_union as validate_stage7_union
from group8_v3_finalize_annual_2023 import finalize as finalize_2023
from group8_v3_archive_stage5 import archive_stage5
from group8_v3_freeze_oos_2024 import freeze as freeze_oos
from group8_v3_oos_2024_stage5 import run as run_oos_stage5
from group8_v3_oos_2024_stage6 import build_plan as build_s6_plan,execute as execute_s6
from group8_v3_oos_2024_stage7 import build_plan as build_s7_plan,execute as execute_s7
from group8_v3_finalize_annual_2024_oos import finalize as finalize_2024
from group8_v3_cross_year_validate import validate as cross_validate
from group8_v3_close_group8 import close as close_group8
from moebot_group8_engine_v0_8_0 import sha256_file

FLOOR=120*(1024**3)
HARD=2_500_000_000

def _log(msg:str)->None:
 print(time.strftime("%Y-%m-%d %H:%M:%S"),msg,flush=True)

def _load_hashed(path:Path,field:str,status:str|None=None)->dict[str,Any]:
 r=json.loads(path.read_text());x=dict(r);saved=str(x.pop(field))
 if stable_hash(x)!=saved:raise RuntimeError(f"{path.name}:{field} mismatch")
 if status is not None and r.get("status")!=status:raise RuntimeError(f"{path.name}:status={r.get('status')}")
 return r

def _run(cmd:list[str],env:dict[str,str]|None=None)->None:
 _log("RUN "+" ".join(cmd))
 subprocess.run(cmd,check=True,env=env)

def _sqlite_ok(path:Path)->bool:
 if not path.is_file():return False
 con=sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1",uri=True)
 try:return con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
 finally:con.close()

def _copy_stage7_tree_verified(src:Path,dst:Path,release:dict[str,Any])->None:
 if src.resolve()==dst.resolve():return
 if dst.exists():shutil.rmtree(dst)
 shutil.copytree(src,dst)
 for x in release["shards"]:
  arc=dst/x["archive_path"]
  if not arc.is_file() or sha256_file(arc)!=x["compressed_sha256"]:raise RuntimeError(f"copied Stage7 archive mismatch:{arc}")
 _log(f"verified Stage7 tree copied {src} -> {dst}")
 shutil.rmtree(src)

def continue_all(*,work:Path,repo:Path,zstd:Path,d_temp_root:Path)->dict[str,Any]:
 art=repo/"MoeBot_Trading_System"/"Group_8"
 commit=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
 py=sys.executable
 env=os.environ.copy();env["PATH"]=str(zstd.parent)+os.pathsep+env.get("PATH","")
 if not zstd.is_file():raise RuntimeError("zstd executable missing")

 # Existing 2023 identities.
 stage5_23=work/"group8_annual_2023_core_completion"/"annual_2023_core.sqlite"
 staging23=work/"group8_annual_2023_core_completion"/"staging"/"MoeBot_Group8_FULL_2023_STAGING_v1.sqlite"
 s6plan23=work/"group8_v3_stage6_plan.json";s6rel23=work/"group8_v3_stage6_release.json";s6u23=work/"group8_v3_stage6_union_report.json"
 s7plan23=work/"group8_v3_stage7_annual_plan.json";s7rel23=work/"group8_v3_stage7_release.json";s7u23=work/"group8_v3_stage7_union_report.json"
 out7_23=work/"group8_v3_stage7_output"

 if not s7rel23.is_file():raise RuntimeError("2023 Stage7 release missing; execution did not finish cleanly")
 _load_hashed(s7rel23,"release_hash","PASS")
 _log("2023 Stage7 release detected")

 # 2023 Stage7 streaming union.
 if not s7u23.is_file():
  uw23=work/"group8_v3_stage7_union_work"
  try:
   if d_temp_root.anchor and shutil.disk_usage(d_temp_root.anchor).free>80*(1024**3):
    uw23=d_temp_root.parent/"group8_v3_stage7_2023_union_scratch"
  except Exception:pass
  if uw23.exists():shutil.rmtree(uw23)
  validate_stage7_union(release_path=s7rel23,plan_path=s7plan23,stage5_db=stage5_23,output_root=out7_23,work_root=uw23,zstd_exe=zstd,output_path=s7u23,fan_in=16)
  if uw23.exists():shutil.rmtree(uw23)
 _load_hashed(s7u23,"report_hash","PASS");_log("2023 Stage7 streaming union PASS")

 # Annual 2023 V3 finalization.
 annual23=work/"group8_v3_annual_2023_manifest.json"
 if not annual23.is_file():
  finalize_2023(artifacts_root=art,stage5_db=stage5_23,stage6_release_path=s6rel23,stage6_union_path=s6u23,stage7_plan_path=s7plan23,stage7_release_path=s7rel23,stage7_union_path=s7u23,expected_commit=commit,output=annual23)
 a23=_load_hashed(annual23,"manifest_hash","ANNUAL_2023_PASS");_log("Annual 2023 V3 PASS")

 # Archive 2023 Stage5 losslessly before freeing raw boundary.
 s5arc23=work/"group8_v3_stage5_2023.sqlite.zst";s5arcr23=work/"group8_v3_stage5_2023_archive_report.json"
 if stage5_23.exists():
  archive_stage5(stage5_db=stage5_23,annual_manifest=annual23,zstd_exe=zstd,archive=s5arc23,report=s5arcr23,level=6,remove_raw=True)
 ar23=_load_hashed(s5arcr23,"report_hash","PASS")
 if ar23.get("lossless_roundtrip_verified") is not True or not s5arc23.is_file():raise RuntimeError("2023 Stage5 archive not safely retained")
 _log("2023 Stage5 archived losslessly and raw boundary released")

 # Freeze exact current tooling before any 2024 materialization.
 freeze_path=work/"group8_v3_oos_2024_freeze.json"
 if not freeze_path.is_file():
  freeze_oos(artifacts_root=art,annual_manifest_path=annual23,stage6_plan_path=s6plan23,stage7_plan_path=s7plan23,stage5_archive_report_path=s5arcr23,zstd_exe=zstd,expected_commit=commit,output=freeze_path)
 fr=_load_hashed(freeze_path,"manifest_hash","FROZEN_FOR_2024_OOS_V3")
 zrec=fr.get("external_tooling",{}).get("zstd",{})
 if zrec.get("sha256")!=sha256_file(zstd) or int(zrec.get("size_bytes",-1))!=zstd.stat().st_size:raise RuntimeError("zstd identity drift after OOS freeze")
 _log("2024 OOS freeze PASS; first 2024 access now authorized")

 # 2023 staging is reproducible from frozen upstream registry and no longer needed.
 if staging23.exists():
  staging23.unlink();_log("released reconstructable 2023 staging database")

 # Materialize untouched 2024 inputs from immutable release registry.
 oos=work/"group8_v3_oos_2024";oos.mkdir(parents=True,exist_ok=True)
 staging24=oos/"staging.sqlite";mat24=oos/"materialization_report.json"
 if not (_sqlite_ok(staging24) and mat24.is_file() and json.loads(mat24.read_text()).get("status")=="PASS"):
  _run([py,str(art/"code"/"group8_materialize_inputs.py"),"--artifacts-root",str(art),"--year","2024","--output-db",str(staging24),"--work-dir",str(oos/"materialize_work"),"--report",str(mat24)],env)
 _log("2024 upstream materialization PASS")

 # Frozen Stage0-5 OOS.
 stage5_24=oos/"stage5.sqlite";stage5rep=oos/"stage5_report.json"
 run_oos_stage5(staging_db=staging24,output_db=stage5_24,artifacts_root=art,freeze_path=freeze_path,symbol="XAUUSD_",start=0,end=5)
 r5={"format_version":1,"status":"PASS","year":2024,"stage5_database_sha256":sha256_file(stage5_24),"freeze_manifest_hash":fr["manifest_hash"]};r5["report_hash"]=stable_hash(r5);stage5rep.write_text(json.dumps(r5,indent=2,sort_keys=True)+"\n")
 _log("2024 OOS Stage0-5 PASS")

 # Frozen-policy Stage6.
 s6plan24=oos/"stage6_plan.json"
 if not s6plan24.exists():build_s6_plan(stage5_db=stage5_24,artifacts_root=art,freeze_path=freeze_path,symbol="XAUUSD_",output=s6plan24)
 s6out24=oos/"stage6_output";s6prog24=oos/"stage6_progress.json";s6rel24=oos/"stage6_release.json"
 execute_s6(plan_path=s6plan24,staging_db=staging24,stage5_db=stage5_24,artifacts_root=art,freeze_path=freeze_path,output_root=s6out24,progress_path=s6prog24,release_path=s6rel24)
 _load_hashed(s6rel24,"release_hash","PASS");_log("2024 OOS Stage6 PASS")
 s6u24=oos/"stage6_union.json"
 if not s6u24.exists():validate_stage6_union(release_path=s6rel24,stage5_db=stage5_24,work_root=oos/"stage6_union_work",output_path=s6u24)
 _load_hashed(s6u24,"report_hash","PASS");_log("2024 OOS Stage6 union PASS")

 # Frozen-policy Stage7 plan from 2023 bucket counts.
 s7plan24=oos/"stage7_plan.json"
 if not s7plan24.exists():build_s7_plan(staging_db=staging24,stage5_db=stage5_24,artifacts_root=art,freeze_path=freeze_path,work_root=oos/"stage7_plan_work",symbol="XAUUSD_",output=s7plan24)
 p24=_load_hashed(s7plan24,"plan_hash","PASS")

 # Decide C or temporary D only after exact 2024 cardinality is known.
 s7r23=_load_hashed(s7rel23,"release_hash","PASS")
 i23=max(int(s7r23["table_row_counts"]["school_interpretation"]),1)
 bytes_per_i=float(s7r23["total_compressed_bytes"])/i23
 projected=int(bytes_per_i*int(p24["expected_cardinality"]["total_stage7_interpretations"])*1.5)
 cfinal=oos/"stage7_output"
 cfree=shutil.disk_usage(work).free
 if cfree-FLOOR >= projected+HARD+10*(1024**3):
  s7out24=cfinal;used_d=False
 else:
  if not d_temp_root.drive and os.name=="nt":raise RuntimeError("temporary D path invalid")
  droot=d_temp_root
  try:dfree=shutil.disk_usage(droot.anchor if droot.anchor else droot.parent).free
  except FileNotFoundError:
   droot.mkdir(parents=True,exist_ok=True);dfree=shutil.disk_usage(droot).free
  if dfree < projected+20*(1024**3):raise RuntimeError(f"insufficient C and temporary D space for reconstructable OOS Stage7; projected={projected}")
  s7out24=droot;used_d=True
  _log(f"C safety floor protected; using D only as temporary reconstructable Stage7 cache: {s7out24}")

 s7prog24=oos/"stage7_progress.json";s7rel24=oos/"stage7_release.json"
 execute_s7(plan_path=s7plan24,staging_db=staging24,stage5_db=stage5_24,artifacts_root=art,freeze_path=freeze_path,stage6_release_path=s6rel24,stage6_union_path=s6u24,output_root=s7out24,progress_path=s7prog24,release_path=s7rel24,zstd_exe=zstd,chunk=5000)
 rel24=_load_hashed(s7rel24,"release_hash","PASS");_log("2024 OOS Stage7 PASS")
 s7u24=oos/"stage7_union.json"
 if not s7u24.exists():
  uw24=oos/"stage7_union_work"
  try:
   if d_temp_root.anchor and shutil.disk_usage(d_temp_root.anchor).free>80*(1024**3):uw24=d_temp_root.parent/"group8_v3_stage7_2024_union_scratch"
  except Exception:pass
  if uw24.exists():shutil.rmtree(uw24)
  validate_stage7_union(release_path=s7rel24,plan_path=s7plan24,stage5_db=stage5_24,output_root=s7out24,work_root=uw24,zstd_exe=zstd,output_path=s7u24,fan_in=16)
  if uw24.exists():shutil.rmtree(uw24)
 _load_hashed(s7u24,"report_hash","PASS");_log("2024 OOS Stage7 streaming union PASS")

 # Annual 2024 OOS.
 annual24=oos/"annual_2024_oos_manifest.json"
 if not annual24.exists():finalize_2024(freeze_path=freeze_path,stage5_db=stage5_24,stage6_release_path=s6rel24,stage6_union_path=s6u24,stage7_plan_path=s7plan24,stage7_release_path=s7rel24,stage7_union_path=s7u24,output=annual24)
 _load_hashed(annual24,"manifest_hash","ANNUAL_2024_OOS_PASS");_log("Annual 2024 OOS PASS")

 # Archive 2024 Stage5 and release reconstructable staging before restoring any D cache to C.
 s5arc24=oos/"stage5_2024.sqlite.zst";s5arcr24=oos/"stage5_2024_archive_report.json"
 if stage5_24.exists():archive_stage5(stage5_db=stage5_24,annual_manifest=annual24,zstd_exe=zstd,archive=s5arc24,report=s5arcr24,level=6,remove_raw=True)
 _load_hashed(s5arcr24,"report_hash","PASS")
 if staging24.exists():staging24.unlink()
 _log("2024 Stage5 archived losslessly; 2024 staging released")

 if used_d:
  _copy_stage7_tree_verified(s7out24,cfinal,rel24)
  s7out24=cfinal

 # Cross-year and official Group8 closure.
 cross=oos/"cross_year_validation.json"
 if not cross.exists():cross_validate(annual23_path=annual23,annual24_path=annual24,freeze_path=freeze_path,output=cross)
 _load_hashed(cross,"report_hash","PASS");_log("Cross-year validation PASS")
 closure=oos/"group8_closure.json";handoff=oos/"group9_handoff.json"
 if not closure.exists():
  close_group8(annual23_path=annual23,annual24_path=annual24,freeze_path=freeze_path,cross_path=cross,stage6_2023_union_path=s6u23,stage7_2023_union_path=s7u23,stage6_2024_union_path=s6u24,stage7_2024_union_path=s7u24,output=closure,handoff=handoff)
 c=json.loads(closure.read_text())
 if c.get("officially_closed") is not True or c.get("group9_authorized") is not True:raise RuntimeError("Group8 closure did not authorize Group9")
 _log("GROUP 8 OFFICIALLY CLOSED; GROUP 9 AUTHORIZED")
 return c

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--work-root",type=Path,default=Path(r"C:\MoeBotWork"));p.add_argument("--repo",type=Path,default=Path(r"C:\MoeBotActive\group8-v3-validation"));p.add_argument("--zstd-exe",type=Path,default=Path(r"C:\MoeBotActive\tools\zstd\zstd-v1.5.7-win64\zstd.exe"));p.add_argument("--d-temp-root",type=Path,default=Path(r"D:\MoeBotData\group8_v3_oos_2024_stage7_temp"))
 a=p.parse_args();r=continue_all(work=a.work_root.resolve(),repo=a.repo.resolve(),zstd=a.zstd_exe.resolve(),d_temp_root=a.d_temp_root);print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
