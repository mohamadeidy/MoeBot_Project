#!/usr/bin/env python3
"""Bounded real-data reconstruction with the original frozen PA7 producer.
Only eight predetermined May 2023 H1 roots and their exact parent ranges.
The level projection retains every PA7 exact-breakout/retest match for those
ranges across the entire recovered H1 year. No producer semantics changed.
No hypotheses, annual invalidation completeness, or production authorization.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
G8 = ROOT / "Group_8"
G9 = ROOT / "Group_9"
sys.path.insert(0, str(G8 / "code"))
from group8_pa7_derived_executor import PA7DerivedEngine, DERIVED_INTERPRETATIONS
from moebot_group8_engine_v0_8_0 import normalize_direction
from group8_pa7_catalog import init_catalog, INSERT_SQL
from group9_real_setup_benchmark import (init_index, insert_subject,
    index_support_refs, init_sample_output, materialize_one)
from group9_real_root_inventory import load_hashed, atomic_json, stable

SCRATCH = Path(r"D:\MoeBotData\group9_scratch")
STAGING = Path(r"D:\MoeBotData\migration\full2023staging\MoeBot_Group8_FULL_2023_STAGING_v1.sqlite")
SOURCE = Path(r"D:\MoeBotData\group8_v3_full_surface_recovery\stage5_2023.sqlite")
CATALOG = SCRATCH / "upstream_pa7" / "official_h1_v2" / "H1_2023_v2_pa7_candidate_catalog.sqlite"
ACTIVE = Path(r"C:\MoeBotWork\group9_active\wyckoff_derived_pilot_20261124")
VAULT = Path(r"D:\MoeBotVault\Group_9\wyckoff_derived_pilot_20261124")
WORK = Path(r"C:\MoeBotWork")
COLS = "interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json"
WY = "G9_WYCKOFF_RANGE_RESOLUTION"

def ro(p):
    c = sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def copy_row(db, table, row):
    cols=list(row.keys())
    db.execute("INSERT INTO "+table+"("+",".join(cols)+") VALUES ("+
               ",".join("?" for _ in cols)+")",tuple(row))

def add_subject(idx, row):
    insert_subject(idx, year=2023, subject_type="school_interpretation",
                   row=tuple(row[k] for k in COLS.split(",")), is_sample_root=False)
    index_support_refs(idx,row["interpretation_id"],"school_interpretation",
                       row["definition_id"],row["upstream_refs_json"])

def check_db(db):
    if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
        raise RuntimeError("sqlite_integrity_failure")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("foreign_key_failure")

def build_output(idx, roots, path):
    stats=defaultdict(lambda:dict(roots=0,setup_rows=0,evidence_rows=0,
                                  transition_rows=0,logical_bytes=0))
    with closing(init_sample_output(path,G9/"02_SCHEMA.sql")) as out:
        out.execute("PRAGMA foreign_keys=ON")
        for root in roots:
            materialize_one(idx,out,root,"G9-SSI-1.0.0",stats,benchmark_mode=True)
        out.commit()
        check_db(out)
        states=dict(out.execute("SELECT current_state,COUNT(*) FROM setup_instance GROUP BY current_state"))
        if sum(states.values())!=len(roots):raise RuntimeError("root_count_mismatch")
        return {"states":states,"evidence_rows":out.execute("SELECT COUNT(*) FROM setup_component_evidence").fetchone()[0],
                "transitions":out.execute("SELECT COUNT(*) FROM setup_transition").fetchone()[0]}

def compress_verified(path):
    zstd=Path("C:/MoeBotActive/tools/zstd/zstd-v1.5.7-win64/zstd.exe")
    archive=path.with_suffix(path.suffix+".zst")
    if archive.exists():raise FileExistsError(archive)
    started=time.perf_counter()
    subprocess.run([str(zstd),"-q","-6","-T2",str(path),"-o",str(archive)],check=True,timeout=180)
    compression_seconds=time.perf_counter()-started
    digest=hashlib.sha256(); size=0
    with subprocess.Popen([str(zstd),"-q","-d","-c",str(archive)],stdout=subprocess.PIPE) as proc:
        for block in iter(lambda:proc.stdout.read(8*1024*1024),b""):
            digest.update(block);size+=len(block)
        if proc.wait()!=0:raise RuntimeError("zstd_roundtrip_failed")
    if size!=path.stat().st_size or digest.hexdigest()!=sha(path):
        raise RuntimeError("zstd_roundtrip_identity_mismatch")
    return {"raw_bytes":size,"archive_bytes":archive.stat().st_size,
            "raw_sha256":digest.hexdigest(),"archive_sha256":sha(archive),
            "compression_seconds":compression_seconds,"lossless_roundtrip_verified":True}

def main():
    global ACTIVE,VAULT
    started=time.perf_counter()
    p=argparse.ArgumentParser()
    p.add_argument("--roots",type=int,default=8)
    p.add_argument("--month",choices=[f"2023-{m:02d}" for m in range(1,13)])
    a=p.parse_args()
    month=a.month or "2023-05"
    if a.month:
        ACTIVE=ACTIVE.parent/("wyckoff_sizing_20261124_"+month)
        VAULT=VAULT.parent/"wyckoff_sizing_20261124"/month
    if not 1<=a.roots<=8:raise ValueError("bounded_scope_only")
    if ACTIVE.exists() or VAULT.exists():raise FileExistsError("pilot_output_exists")
    if shutil.disk_usage("C:/").free<124*1024**3:raise RuntimeError("C_storage_gate")
    staging_release=json.loads((G8/"reports"/"48_FULL_2023_STAGING_RELEASE.json").read_text())
    if STAGING.stat().st_size!=staging_release["raw_size_bytes"] or sha(STAGING)!=staging_release["raw_sha256"]:
        raise RuntimeError("full_staging_sha_mismatch")
    rec=load_hashed(CATALOG.parent/"verified_H1_source_catalog_receipt.json")
    if rec["status"]!="PASS_FROZEN_H1_PA7_SOURCE_CATALOG_ONLY" or sha(CATALOG)!=rec["catalog_sha256"]:
        raise RuntimeError("H1_catalog_receipt_mismatch")
    print("FROZEN_INPUT_HASHES=PASS",flush=True)
    stage5_report=load_hashed(WORK/"group8_v3_stage5_2023_archive_report.json")
    if SOURCE.stat().st_size!=stage5_report["raw_size_bytes"]:
        raise RuntimeError("stage5_size_mismatch")
    ACTIVE.mkdir(parents=True)
    with closing(ro(SCRATCH/"group9_root_inventory.sqlite")) as inv, closing(ro(SOURCE)) as src, closing(ro(SCRATCH/"group9_support_index.sqlite")) as supp, closing(ro(CATALOG)) as cat:
        roots=inv.execute("""SELECT * FROM root_candidate WHERE dataset_year=2023
            AND symbol='XAUUSD_' AND timeframe='H1' AND root_month=?
            AND setup_family=? ORDER BY root_key LIMIT ?""",(month,WY,a.roots)).fetchall()
        if len(roots)!=a.roots:raise RuntimeError("root_inventory_short")
        source_roots=[];contexts={};patterns={};range_for={}
        for r in roots:
            row=src.execute("SELECT * FROM school_interpretation WHERE interpretation_id=?",(r["source_id"],)).fetchone()
            if row is None or row["interpretation_hash"]!=r["source_row_hash"]:
                raise RuntimeError("root_lineage_mismatch")
            source_roots.append(row)
            ref=next(x for x in json.loads(row["upstream_refs_json"]) if x["source_type"]=="school_interpretation")
            ctx=src.execute("SELECT * FROM school_interpretation WHERE interpretation_id=?",(ref["source_id"],)).fetchone()
            if ctx is None or ctx["definition_id"]!="wyckoff_range_context":raise RuntimeError("range_parent_missing")
            stored=supp.execute("SELECT row_hash FROM subject WHERE subject_id=?",(ctx["interpretation_id"],)).fetchone()
            if stored is None or stored[0]!=ctx["interpretation_hash"]:raise RuntimeError("range_hash_mismatch")
            contexts[ctx["interpretation_id"]]=ctx
            rr=next(x for x in json.loads(ctx["upstream_refs_json"]) if x["source_type"]=="price_action_pattern_candidate")
            rg=src.execute("SELECT * FROM price_action_pattern_candidate WHERE candidate_id=?",(rr["source_id"],)).fetchone()
            if rg is None or rg["definition_id"]!="pa_bounded_range_context":raise RuntimeError("range_pattern_missing")
            patterns[rg["candidate_id"]]=rg
            range_for[ctx["interpretation_id"]]=rg
        # Full search domain for the selected levels, not a date-truncated sample.
        levels=sorted({float(rg[k]) for rg in patterns.values() for k in ("lower","upper")})
        projected=ACTIVE/"complete_selected_level_catalog.sqlite"
        init_catalog(projected)
        level_rows={}; all_candidates={}
        cols="candidate_id,definition_id,symbol,timeframe,direction,source_bar_id,related_source_bar_id,event_time,confirmation_time,availability_time,lower,upper,features_json,candidate_hash"
        for level in levels:
            for definition in ("pa_breakout_exact","pa_retest"):
                rows=cat.execute("SELECT "+cols+""" FROM pa7_candidate_catalog
                  WHERE definition_id=? AND symbol='XAUUSD_' AND timeframe='H1'
                  AND lower>=? AND lower<=? AND ABS(lower-?)<1e-12
                  ORDER BY availability_time,candidate_id""",
                  (definition,level-1e-9,level+1e-9,level)).fetchall()
                level_rows[(level,definition)]=rows
                all_candidates.update((r["candidate_id"],r) for r in rows)
        with closing(sqlite3.connect(projected)) as db:
            db.executemany(INSERT_SQL,[tuple(r) for r in all_candidates.values()])
            db.commit()
            check_db(db)
        print("COMPLETE_LEVEL_PROJECTION roots=%d ranges=%d levels=%d candidates=%d"%
              (len(roots),len(contexts),len(levels),len(all_candidates)),flush=True)
        derived=ACTIVE/"bounded_frozen_producer.sqlite"
        producer_started=time.perf_counter()
        engine=PA7DerivedEngine(staging_db=STAGING,output_db=derived,
                    artifacts_root=G8,year=2023,symbol="XAUUSD_",pa7_catalog=projected)
        try:
            for row in patterns.values():copy_row(engine.out,"price_action_pattern_candidate",row)
            for row in contexts.values():copy_row(engine.out,"school_interpretation",row)
            engine.out.commit()
            # Original producer, unchanged. Deliberately omit spring/hypothesis
            # generation from this bounded range-level reconstruction.
            engine.process_wyckoff_pa7_dependent()
            legs=[dict(r) for r in engine._validated_legs() if r["timeframe"]=="H1"]
            check_db(engine.out)
        finally:engine.close()
        producer_seconds=time.perf_counter()-producer_started
        # Independent expected graph from full-year level-domain and leg rows.
        expected_signs=set();expected_lasts=set()
        def first(rows,t,strict=False):
            keys=[int(x["availability_time"]) for x in rows]
            n=(bisect_right if strict else bisect_left)(keys,t)
            return rows[n] if n<len(rows) else None
        for ctx_id,ctx in contexts.items():
            rg=range_for[ctx_id]
            for direction,level in (("bullish",float(rg["upper"])),("bearish",float(rg["lower"]))):
                breaks=[x for x in level_rows[(level,"pa_breakout_exact")] if x["direction"]==direction]
                rets=level_rows[(level,"pa_retest")]
                for leg in legs:
                    if normalize_direction(leg["direction"])!=direction:continue
                    br=first(breaks,int(leg["validation_availability"]))
                    if br is None:continue
                    avail=max(ctx["availability_time"],leg["validation_availability"],br["availability_time"])
                    key=(ctx_id,direction,str(leg["leg_id"]),br["candidate_id"],avail)
                    expected_signs.add(key)
                    ret=first(rets,int(br["availability_time"]),True)
                    if ret is not None:
                        expected_lasts.add((key,ret["candidate_id"],max(avail,ret["availability_time"])))
        with closing(ro(derived)) as produced:
            rows=produced.execute("SELECT * FROM school_interpretation WHERE definition_id IN (?,?,?,?) ORDER BY interpretation_id",tuple(sorted(DERIVED_INTERPRETATIONS))).fetchall()
        sign_keys={};actual_lasts=set()
        for row in rows:
            refs=json.loads(row["upstream_refs_json"])
            if row["definition_id"] in ("wyckoff_sign_of_strength","wyckoff_sign_of_weakness"):
                sign_keys[row["interpretation_id"]]=(refs[0]["source_id"],row["direction"],refs[1]["source_id"],refs[2]["source_id"],row["availability_time"])
            if row["event_time"]>row["confirmation_time"] or row["confirmation_time"]>row["availability_time"]:
                raise RuntimeError("producer_temporal_order")
            if any(x["availability_time"]>row["availability_time"] for x in refs):
                raise RuntimeError("future_evidence_link")
        for row in rows:
            if row["definition_id"] in ("wyckoff_last_point_of_support","wyckoff_last_point_of_supply"):
                rr=json.loads(row["upstream_refs_json"])
                actual_lasts.add((sign_keys[rr[0]["source_id"]],rr[1]["source_id"],row["availability_time"]))
        if set(sign_keys.values())!=expected_signs or actual_lasts!=expected_lasts:
            raise RuntimeError("frozen_producer_independent_graph_parity_failed")
        counts=Counter(row["definition_id"] for row in rows)
        print("FROZEN_PRODUCER_GRAPH_PARITY=PASS "+str(dict(counts)),flush=True)
        idxpath=ACTIVE/"bounded_support_index.sqlite"
        with closing(init_index(idxpath)) as idx:
            idx.row_factory=sqlite3.Row
            censor=supp.execute("SELECT censor_time FROM annual_boundary WHERE dataset_year=2023").fetchone()[0]
            idx.execute("INSERT INTO annual_boundary VALUES(2023,?)",(censor,))
            def attach(row):
                add_subject(idx,row)
                for r in supp.execute("SELECT * FROM invalidation WHERE subject_type='school_interpretation' AND subject_id=?",(row["interpretation_id"],)):
                    idx.execute("INSERT OR IGNORE INTO invalidation VALUES(?,?,?,?,?,?,?,?,?)",tuple(r))
            for row in source_roots+list(contexts.values()):attach(row)
            idx.commit()
            baseline=build_output(idx,roots,ACTIVE/"baseline.sqlite")
            for row in rows:attach(row)
            idx.commit()
            materializer_started=time.perf_counter()
            augmented=build_output(idx,roots,ACTIVE/"augmented.sqlite")
            materializer_seconds=time.perf_counter()-materializer_started
            check_db(idx)
        compression=compress_verified(ACTIVE/"augmented.sqlite") if a.month else None
    result={"status":"PASS_BOUNDED_WYCKOFF_DERIVED_GRAPH_PARITY",
            "scope":"2023_XAUUSD_H1_PREDETERMINED_ROOTS_ONLY",
            "sample_month":month,
            "sample_selection":"first_root_keys_within_month",
            "producer_seconds":producer_seconds,
            "materializer_seconds":materializer_seconds,
            "compression":compression,
            "pre_vault_total_seconds":time.perf_counter()-started,
            "roots":len(roots),"root_ids":[r["source_id"] for r in roots],
            "range_count":len(contexts),"validated_h1_leg_rows":len(legs),
            "full_level_projection_candidates":len(all_candidates),
            "derived_definition_counts":dict(counts),"sign_graph_keys":len(expected_signs),
            "last_point_graph_keys":len(expected_lasts),
            "baseline":baseline,"with_derived":augmented,
            "full_h1_year_catalog_sha256":rec["catalog_sha256"],
            "full_staging_sha256":staging_release["raw_sha256"],
            "stage5_source_size_checked_prior_restore_not_rehashed":True,
            "producer_sha256":sha(G8/"code"/"group8_pa7_derived_executor.py"),
            "frozen_group8_modified":False,
            "derived_invalidation_completeness_verified":False,
            "full_annual_coverage_verified":False,
            "group9_annual_execution_authorized":False}
    result["report_hash"]=stable(result)
    atomic_json(ACTIVE/"pilot_report.json",result)
    VAULT.mkdir(parents=True)
    files=[]
    for src in sorted(ACTIVE.iterdir()):
        if not src.is_file():raise RuntimeError("unexpected_pilot_output")
        dst=VAULT/src.name
        digest=sha(src)
        shutil.copyfile(src,dst)
        if dst.stat().st_size!=src.stat().st_size or sha(dst)!=digest:
            raise RuntimeError("vault_copy_identity_failure")
        files.append({"name":src.name,"size_bytes":dst.stat().st_size,"sha256":digest})
    transfer={"status":"PASS","pilot_report_hash":result["report_hash"],"files":files}
    transfer["report_hash"]=stable(transfer)
    atomic_json(VAULT/"transfer_receipt.json",transfer)
    for f in files:
        if sha(VAULT/f["name"])!=f["sha256"]:raise RuntimeError("vault_drift")
    for f in files:(ACTIVE/f["name"]).unlink()
    ACTIVE.rmdir()
    print("PILOT_RESULT="+json.dumps(result,sort_keys=True),flush=True)
    print("VERIFIED_VAULT="+str(VAULT),flush=True)
    return 0

if __name__=="__main__":raise SystemExit(main())
