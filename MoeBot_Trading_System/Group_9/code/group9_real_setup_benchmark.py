#!/usr/bin/env python3
"""Representative real-data setup-state benchmark for MoeBot Group 9.

This benchmark is outcome-blind. It builds a compact reverse-link index from frozen
Group 8 evidence, selects a deterministic sample proportional to the exact root
inventory, materializes representative Group 9 setup lifecycles, and projects the
full candidate runtime/output cardinality. It does not authorize annual execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from group9_real_root_inventory import (
    atomic_json,
    fast_readonly_schema_check,
    load_hashed,
    restore_marker_path,
    stable,
    stream_decompress_verified,
    write_verified_restore_marker,
)

GIB=1024**3

STAGE5_SCHOOL_SUPPORT=(
    "wyckoff_range_context",
    "wyckoff_sign_of_strength","wyckoff_sign_of_weakness",
    "wyckoff_last_point_of_support","wyckoff_last_point_of_supply",
    "dow_advancing_structure","dow_declining_structure","dow_protected_pullback",
)
STAGE5_HYP_SUPPORT=("pa_continuation_after_pullback",)
STAGE7_SUPPORT=(
    "ict_mss_fvg_delivery","ict_return_to_imbalance","ict_block_delivery_context",
    "ict_premium_discount_context","ict_draw_on_liquidity_context",
)
ICT_ROOT="ict_liquidity_sweep_displacement"
WY_ROOTS={"wyckoff_spring_candidate","wyckoff_upthrust_candidate"}
STRUCT_ROOT="pa_structural_pullback"


def sha256_file(path:Path,chunk:int=8*1024*1024)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()


def init_index(path:Path)->sqlite3.Connection:
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): path.unlink()
    con=sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.executescript("""
    CREATE TABLE subject(
      subject_id TEXT PRIMARY KEY,
      subject_type TEXT NOT NULL,
      dataset_year INTEGER NOT NULL,
      definition_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      timeframe TEXT NOT NULL,
      direction TEXT NOT NULL,
      event_time INTEGER NOT NULL,
      availability_time INTEGER NOT NULL,
      row_hash TEXT NOT NULL,
      upstream_refs_json TEXT NOT NULL,
      is_sample_root INTEGER NOT NULL CHECK(is_sample_root IN(0,1))
    );
    CREATE INDEX ix_subject_def ON subject(dataset_year,definition_id,symbol,timeframe,availability_time);
    CREATE TABLE support_ref(
      subject_id TEXT NOT NULL,
      subject_type TEXT NOT NULL,
      definition_id TEXT NOT NULL,
      source_group TEXT NOT NULL,
      source_type TEXT NOT NULL,
      source_id TEXT NOT NULL,
      source_event_time INTEGER,
      source_availability_time INTEGER NOT NULL,
      source_timeframe TEXT,
      relation_type TEXT NOT NULL,
      ordinal INTEGER NOT NULL,
      PRIMARY KEY(subject_id,ordinal)
    );
    CREATE INDEX ix_support_ref_source ON support_ref(source_group,source_type,source_id);
    CREATE INDEX ix_support_ref_subject ON support_ref(subject_id);
    CREATE TABLE invalidation(
      invalidation_id TEXT PRIMARY KEY,
      subject_type TEXT NOT NULL,
      subject_id TEXT NOT NULL,
      rule_id TEXT NOT NULL,
      source_type TEXT NOT NULL,
      source_id TEXT NOT NULL,
      event_time INTEGER NOT NULL,
      availability_time INTEGER NOT NULL,
      invalidation_hash TEXT NOT NULL
    );
    CREATE INDEX ix_invalidation_subject ON invalidation(subject_type,subject_id,availability_time);
    CREATE TABLE annual_boundary(
      dataset_year INTEGER PRIMARY KEY,
      censor_time INTEGER NOT NULL
    );
    CREATE TABLE benchmark_sample(
      root_key TEXT PRIMARY KEY,
      dataset_year INTEGER NOT NULL,
      setup_family TEXT NOT NULL,
      source_type TEXT NOT NULL,
      source_id TEXT NOT NULL,
      definition_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      timeframe TEXT NOT NULL,
      direction TEXT NOT NULL,
      event_time INTEGER NOT NULL,
      availability_time INTEGER NOT NULL,
      source_row_hash TEXT NOT NULL
    );
    """)
    return con


def refs(v:str)->list[dict[str,Any]]:
    try:
        x=json.loads(v or "[]")
    except Exception:
        return []
    return x if isinstance(x,list) else []


def insert_subject(con:sqlite3.Connection,*,year:int,subject_type:str,row:sqlite3.Row|tuple,is_sample_root:bool)->None:
    if subject_type=="school_interpretation":
        sid,definition,symbol,tf,direction,event,avail,row_hash,upstream=row
    else:
        sid,definition,symbol,tf,direction,event,avail,row_hash,upstream=row
    con.execute("""INSERT INTO subject(subject_id,subject_type,dataset_year,definition_id,symbol,timeframe,direction,event_time,availability_time,row_hash,upstream_refs_json,is_sample_root)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subject_id) DO UPDATE SET is_sample_root=MAX(subject.is_sample_root,excluded.is_sample_root)""",
                (str(sid),subject_type,int(year),str(definition),str(symbol),str(tf),str(direction),int(event),int(avail),str(row_hash),str(upstream),1 if is_sample_root else 0))


def index_support_refs(con:sqlite3.Connection,subject_id:str,subject_type:str,definition_id:str,upstream_json:str)->None:
    for ordinal,r in enumerate(refs(upstream_json)):
        con.execute("""INSERT OR REPLACE INTO support_ref(subject_id,subject_type,definition_id,source_group,source_type,source_id,
                     source_event_time,source_availability_time,source_timeframe,relation_type,ordinal)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (subject_id,subject_type,definition_id,str(r.get("source_group","group8")),str(r.get("source_type","unknown")),
                     str(r.get("source_id","")),None if r.get("event_time") is None else int(r["event_time"]),
                     int(r.get("availability_time",0)),None if r.get("timeframe") is None else str(r["timeframe"]),
                     str(r.get("relation_type","mandatory_evidence")),ordinal))


def select_sample(inv:sqlite3.Connection,idx:sqlite3.Connection,total_sample:int)->dict[str,Any]:
    total=int(inv.execute("SELECT COUNT(*) FROM root_candidate").fetchone()[0])
    if total<=0: raise RuntimeError("empty inventory")
    strata=[tuple(r) for r in inv.execute("""SELECT dataset_year,setup_family,COUNT(*) FROM root_candidate
                                            GROUP BY dataset_year,setup_family ORDER BY dataset_year,setup_family""")]
    minimum=min(100,max(1,total_sample//max(1,len(strata))))
    base=[min(int(n),minimum) for _,_,n in strata]
    remaining=max(0,total_sample-sum(base))
    residual_total=sum(max(0,int(n)-b) for (_,_,n),b in zip(strata,base))
    allocations=[]
    used=0
    for i,((year,family,n),b) in enumerate(zip(strata,base)):
        residual=max(0,int(n)-b)
        extra=0 if residual_total==0 else int(math.floor(remaining*residual/residual_total))
        take=min(int(n),b+extra)
        allocations.append((int(year),str(family),int(n),take));used+=take
    leftover=max(0,total_sample-used)
    for i in sorted(range(len(allocations)),key=lambda j:allocations[j][2]-allocations[j][3],reverse=True):
        y,f,n,t=allocations[i]
        add=min(n-t,leftover);allocations[i]=(y,f,n,t+add);leftover-=add
        if leftover<=0:break
    actual=0
    for year,family,n,take in allocations:
        rows=inv.execute("""SELECT root_key,dataset_year,setup_family,source_type,source_id,definition_id,symbol,timeframe,direction,event_time,availability_time,source_row_hash
                            FROM root_candidate WHERE dataset_year=? AND setup_family=? ORDER BY root_key LIMIT ?""",
                         (year,family,take))
        for r in rows:
            idx.execute("INSERT INTO benchmark_sample VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",tuple(r))
            actual+=1
    idx.commit()
    return {"population":total,"requested":total_sample,"actual":actual,
            "allocations":[{"year":y,"family":f,"population":n,"sample":t} for y,f,n,t in allocations]}


def restore_stage5(zstd:Path,archive:Path,report:dict[str,Any],scratch:Path)->tuple[Path,float]:
    year=int(report["year"]);raw=scratch/f"g9_bench_stage5_{year}.sqlite"
    raw_bytes,secs=stream_decompress_verified(zstd,archive,raw,str(report["raw_sha256"]))
    if raw_bytes!=int(report["raw_size_bytes"]):
        raw.unlink(missing_ok=True);raise RuntimeError(f"stage5 restore size mismatch:{year}")
    fast_readonly_schema_check(raw,("school_interpretation","narrative_hypothesis","invalidation_record","processing_checkpoint"))
    write_verified_restore_marker(raw,report,provenance="group9_setup_benchmark_stream_verified")
    return raw,secs


def build_stage5_index(*,idx:sqlite3.Connection,raw:Path,year:int,sample_ids:set[str])->dict[str,Any]:
    src=sqlite3.connect(f"file:{raw.resolve()}?mode=ro&immutable=1",uri=True);src.row_factory=sqlite3.Row
    t0=time.perf_counter();supports=0;roots=0;refs_n=0;invalid_n=0
    try:
        censor=max(int(r[0] or 0) for r in src.execute("SELECT MAX(last_time) FROM processing_checkpoint"))
        idx.execute("INSERT OR REPLACE INTO annual_boundary VALUES(?,?)",(year,censor))
        q=",".join("?" for _ in STAGE5_SCHOOL_SUPPORT)
        for r in src.execute(f"""SELECT interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json
                                 FROM school_interpretation WHERE definition_id IN ({q})""",STAGE5_SCHOOL_SUPPORT):
            row=(r["interpretation_id"],r["definition_id"],r["symbol"],r["timeframe"],r["direction"],r["event_time"],r["availability_time"],r["interpretation_hash"],r["upstream_refs_json"])
            insert_subject(idx,year=year,subject_type="school_interpretation",row=row,is_sample_root=False)
            index_support_refs(idx,str(r["interpretation_id"]),"school_interpretation",str(r["definition_id"]),str(r["upstream_refs_json"]));supports+=1;refs_n+=len(refs(str(r["upstream_refs_json"])))
        qh=",".join("?" for _ in STAGE5_HYP_SUPPORT)
        for r in src.execute(f"""SELECT hypothesis_id,definition_id,symbol,timeframe,direction,event_time,availability_time,hypothesis_hash,upstream_refs_json
                                  FROM narrative_hypothesis WHERE definition_id IN ({qh})""",STAGE5_HYP_SUPPORT):
            row=(r["hypothesis_id"],r["definition_id"],r["symbol"],r["timeframe"],r["direction"],r["event_time"],r["availability_time"],r["hypothesis_hash"],r["upstream_refs_json"])
            insert_subject(idx,year=year,subject_type="narrative_hypothesis",row=row,is_sample_root=False)
            index_support_refs(idx,str(r["hypothesis_id"]),"narrative_hypothesis",str(r["definition_id"]),str(r["upstream_refs_json"]));supports+=1;refs_n+=len(refs(str(r["upstream_refs_json"])))
        stage5_samples=[tuple(r) for r in idx.execute("SELECT source_type,source_id FROM benchmark_sample WHERE dataset_year=?",(year,))]
        # Fetch sampled Stage5 roots directly by immutable primary ID.
        for st,sid in stage5_samples:
            if st=="school_interpretation":
                r=src.execute("""SELECT interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json
                                 FROM school_interpretation WHERE interpretation_id=?""",(sid,)).fetchone()
                if r:
                    row=(r["interpretation_id"],r["definition_id"],r["symbol"],r["timeframe"],r["direction"],r["event_time"],r["availability_time"],r["interpretation_hash"],r["upstream_refs_json"])
                    insert_subject(idx,year=year,subject_type=st,row=row,is_sample_root=True);roots+=1
            elif st=="narrative_hypothesis":
                r=src.execute("""SELECT hypothesis_id,definition_id,symbol,timeframe,direction,event_time,availability_time,hypothesis_hash,upstream_refs_json
                                 FROM narrative_hypothesis WHERE hypothesis_id=?""",(sid,)).fetchone()
                if r:
                    row=(r["hypothesis_id"],r["definition_id"],r["symbol"],r["timeframe"],r["direction"],r["event_time"],r["availability_time"],r["hypothesis_hash"],r["upstream_refs_json"])
                    insert_subject(idx,year=year,subject_type=st,row=row,is_sample_root=True);roots+=1
        for r in src.execute("""SELECT invalidation_id,subject_type,subject_id,rule_id,source_type,source_id,event_time,availability_time,invalidation_hash
                                FROM invalidation_record"""):
            idx.execute("INSERT OR IGNORE INTO invalidation VALUES(?,?,?,?,?,?,?,?,?)",tuple(r));invalid_n+=1
        idx.commit()
    finally:
        src.close()
    return {"year":year,"support_subjects":supports,"support_refs":refs_n,"sample_roots_found":roots,"invalidations":invalid_n,
            "seconds":time.perf_counter()-t0}


def iter_stage7_rows(db:Path,defs:tuple[str,...])->Iterable[tuple]:
    con=sqlite3.connect(f"file:{db.resolve()}?mode=ro&immutable=1",uri=True)
    try:
        q=",".join("?" for _ in defs)
        yield from con.execute(f"""SELECT interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json
                                   FROM school_interpretation WHERE definition_id IN ({q})""",defs)
    finally:
        con.close()


def build_stage7_index(*,idx:sqlite3.Connection,release:dict[str,Any],output_root:Path,zstd:Path,scratch:Path,sample_ids:set[str])->dict[str,Any]:
    year=int(release["year"]);t0=time.perf_counter();supports=roots=refs_n=shards=0;dec_s=0.0;raw_bytes=0
    wanted=set(STAGE7_SUPPORT)|{ICT_ROOT}
    for x in sorted(release["shards"],key=lambda z:int(z["ordinal"])):
        if (x.get("spec") or {}).get("family")!="school_core":continue
        mf=output_root/str(x["manifest_path"]);m=load_hashed(mf)
        cov=m.get("definition_coverage") or {}
        if not any(int(cov.get(d,0)) for d in wanted):continue
        arc=output_root/str(x["archive_path"])
        raw=scratch/f"g9_bench_stage7_{year}_{int(x['ordinal']):05d}.sqlite"
        n,ds=stream_decompress_verified(zstd,arc,raw,str(x["raw_sha256"]));raw_bytes+=n;dec_s+=ds;shards+=1
        fast_readonly_schema_check(raw,("school_interpretation",))
        for r in iter_stage7_rows(raw,tuple(sorted(wanted))):
            sid,definition,symbol,tf,direction,event,avail,row_hash,upstream=r
            if definition==ICT_ROOT:
                if str(sid) in sample_ids:
                    insert_subject(idx,year=year,subject_type="school_interpretation",row=r,is_sample_root=True);roots+=1
            else:
                insert_subject(idx,year=year,subject_type="school_interpretation",row=r,is_sample_root=False)
                index_support_refs(idx,str(sid),"school_interpretation",str(definition),str(upstream));supports+=1;refs_n+=len(refs(str(upstream)))
        raw.unlink(missing_ok=True);idx.commit()
    return {"year":year,"support_subjects":supports,"support_refs":refs_n,"sample_roots_found":roots,"shards_scanned":shards,
            "decompressed_raw_bytes":raw_bytes,"decompression_seconds":dec_s,"seconds":time.perf_counter()-t0}


def init_sample_output(path:Path,schema:Path)->sqlite3.Connection:
    if path.exists():path.unlink()
    con=sqlite3.connect(path)
    con.executescript(schema.read_text())
    con.execute("PRAGMA journal_mode=OFF");con.execute("PRAGMA synchronous=OFF")
    return con


def subject_row(idx:sqlite3.Connection,sid:str)->sqlite3.Row|None:
    return idx.execute("SELECT * FROM subject WHERE subject_id=?",(sid,)).fetchone()


def linked_subjects(idx:sqlite3.Connection,source_group:str,source_type:str,source_id:str,defs:set[str])->list[sqlite3.Row]:
    if not defs:return []
    q=",".join("?" for _ in defs)
    return list(idx.execute(f"""SELECT DISTINCT s.* FROM support_ref r JOIN subject s ON s.subject_id=r.subject_id
                               WHERE r.source_group=? AND r.source_type=? AND r.source_id=? AND s.definition_id IN ({q})
                               ORDER BY s.availability_time,s.subject_id""",(source_group,source_type,source_id,*sorted(defs))))


def root_refs(root:sqlite3.Row)->list[dict[str,Any]]:
    return refs(str(root["upstream_refs_json"]))


def linked_by_any_root_ref(idx:sqlite3.Connection,root:sqlite3.Row,defs:set[str])->list[sqlite3.Row]:
    got={}
    for r in root_refs(root):
        for s in linked_subjects(idx,str(r.get("source_group","group8")),str(r.get("source_type","unknown")),str(r.get("source_id","")),defs):
            if s["symbol"]!=root["symbol"] or s["timeframe"]!=root["timeframe"]:continue
            got[str(s["subject_id"])]=s
    for s in linked_subjects(idx,"group8",str(root["subject_type"]),str(root["subject_id"]),defs):
        if s["symbol"]==root["symbol"] and s["timeframe"]==root["timeframe"]:got[str(s["subject_id"])]=s
    return sorted(got.values(),key=lambda x:(int(x["availability_time"]),str(x["subject_id"])))


def invalidation(idx:sqlite3.Connection,ids:list[tuple[str,str]])->sqlite3.Row|None:
    best=None
    for st,sid in ids:
        r=idx.execute("""SELECT * FROM invalidation WHERE subject_type=? AND subject_id=?
                         ORDER BY availability_time,invalidation_id LIMIT 1""",(st,sid)).fetchone()
        if r is not None and (best is None or (int(r["availability_time"]),str(r["invalidation_id"]))<(int(best["availability_time"]),str(best["invalidation_id"]))):
            best=r
    return best


def canonical_row_bytes(vals:Iterable[Any])->int:
    return len(json.dumps(list(vals),separators=(",",":"),ensure_ascii=False).encode())+1


def insert_evidence(out:sqlite3.Connection,*,sid:str,component:str,src:sqlite3.Row,link_method:str,mandatory:int,family_stats:dict[str,int])->str:
    payload={"setup_id":sid,"component":component,"source_group":8,"source_type":str(src["subject_type"]),"source_id":str(src["subject_id"])}
    eid="g9e_"+stable(payload)
    details="{}"
    row=(eid,"",sid,component,int(mandatory),8,str(src["subject_type"]),str(src["subject_id"]),str(src["definition_id"]),
         str(src["direction"]),int(src["event_time"]),int(src["availability_time"]),int(src["event_time"]),int(src["availability_time"]),link_method,details)
    h=stable({"evidence_id":eid,"setup_id":sid,"component_name":component,"mandatory":bool(mandatory),"source_group":8,
              "source_type":str(src["subject_type"]),"source_id":str(src["subject_id"]),"source_definition_id":str(src["definition_id"]),
              "source_direction":str(src["direction"]),"source_event_time":int(src["event_time"]),"source_availability_time":int(src["availability_time"]),
              "observed_event_time":int(src["event_time"]),"observed_availability_time":int(src["availability_time"]),"link_method":link_method,"details":{}})
    row=(eid,h,*row[2:])
    cur=out.execute("""INSERT OR IGNORE INTO setup_component_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",row)
    if cur.rowcount:
        family_stats["evidence_rows"]+=1;family_stats["logical_bytes"]+=canonical_row_bytes(row)
    return eid


def insert_transition(out:sqlite3.Connection,*,sid:str,ordinal:int,from_state:str|None,to_state:str,event:int,avail:int,reason:str,trigger:str|None,family_stats:dict[str,int])->None:
    body={"setup_id":sid,"ordinal":ordinal,"from":from_state,"to":to_state,"event_time":event,"availability_time":avail,"reason":reason,"trigger":trigger}
    tid="g9t_"+stable(body);th=stable(body);details="{}"
    row=(tid,th,sid,ordinal,from_state,to_state,trigger,int(event),int(avail),reason,details)
    out.execute("INSERT INTO setup_transition VALUES(?,?,?,?,?,?,?,?,?,?,?)",row)
    family_stats["transition_rows"]+=1;family_stats["logical_bytes"]+=canonical_row_bytes(row)


def materialize_one(idx:sqlite3.Connection,out:sqlite3.Connection,sample:sqlite3.Row,version:str,stats:dict[str,dict[str,int]])->None:
    root=subject_row(idx,str(sample["source_id"]))
    if root is None:raise RuntimeError(f"sample root missing from source index:{sample['source_id']}")
    family=str(sample["setup_family"]);fs=stats[family];fs["roots"]+=1
    sid="g9s_"+stable({"family":family,"symbol":root["symbol"],"timeframe":root["timeframe"],"direction":root["direction"],
                       "root_subject_type":root["subject_type"],"root_subject_id":root["subject_id"],"definition_version":version})
    features=json.dumps({"benchmark":True,"root_source_hash":str(root["row_hash"])},sort_keys=True,separators=(",",":"))
    initial_base={"setup_id":sid,"setup_family":family,"root_subject_type":str(root["subject_type"]),"root_subject_id":str(root["subject_id"]),
          "root_definition_id":str(root["definition_id"]),"symbol":str(root["symbol"]),"timeframe":str(root["timeframe"]),"direction":str(root["direction"]),
          "origin_event_time":int(root["event_time"]),"origin_availability_time":int(root["availability_time"]),"current_state":"FORMING",
          "state_event_time":int(root["event_time"]),"state_availability_time":int(root["availability_time"]),"definition_version":version,
          "parent_lineage_hash":str(root["row_hash"]),"features_json":features}
    initial_hash=stable(initial_base)
    out.execute("INSERT INTO setup_instance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid,initial_hash,family,str(root["subject_type"]),str(root["subject_id"]),str(root["definition_id"]),str(root["symbol"]),
                 str(root["timeframe"]),str(root["direction"]),int(root["event_time"]),int(root["availability_time"]),"FORMING",
                 int(root["event_time"]),int(root["availability_time"]),version,str(root["row_hash"]),features))
    ev_ids=[];mandatory_ids=[(str(root["subject_type"]),str(root["subject_id"]))]
    root_components=[]
    if family=="G9_ICT_LIQUIDITY_DELIVERY":root_components=["liquidity","displacement"]
    elif family=="G9_WYCKOFF_RANGE_RESOLUTION":root_components=["liquidity"]
    else:root_components=["retracement","structure"]
    for comp in root_components:ev_ids.append(insert_evidence(out,sid=sid,component=comp,src=root,link_method="ROOT",mandatory=1,family_stats=fs))
    ready_time=None;ready_event=None;ready_trigger=None;supports=[]

    if family=="G9_WYCKOFF_RANGE_RESOLUTION":
        rr=root_refs(root);ctx_id=next((str(r.get("source_id")) for r in rr if str(r.get("source_type"))=="school_interpretation"),None)
        ctx=subject_row(idx,ctx_id) if ctx_id else None
        if ctx is not None and ctx["definition_id"]=="wyckoff_range_context":
            supports.append((ctx,["context"],"DIRECT_REF",1));mandatory_ids.append(("school_interpretation",str(ctx["subject_id"])))
            sign_def="wyckoff_sign_of_strength" if root["definition_id"]=="wyckoff_spring_candidate" else "wyckoff_sign_of_weakness"
            last_def="wyckoff_last_point_of_support" if root["definition_id"]=="wyckoff_spring_candidate" else "wyckoff_last_point_of_supply"
            signs=linked_subjects(idx,"group8","school_interpretation",str(ctx["subject_id"]),{sign_def})
            signs=[s for s in signs if s["direction"]==root["direction"] and s["symbol"]==root["symbol"] and s["timeframe"]==root["timeframe"]]
            lasts=[]
            sign_by_id={str(s["subject_id"]):s for s in signs}
            for s in signs:
                supports.append((s,["displacement","structure"],"DIRECT_REF",1));mandatory_ids.append(("school_interpretation",str(s["subject_id"])))
                for lp in linked_subjects(idx,"group8","school_interpretation",str(s["subject_id"]),{last_def}):
                    if lp["direction"]==root["direction"] and lp["symbol"]==root["symbol"] and lp["timeframe"]==root["timeframe"]:
                        lasts.append((s,lp));supports.append((lp,["retracement","confirmation"],"DIRECT_REF",1));mandatory_ids.append(("school_interpretation",str(lp["subject_id"])))
            if lasts:
                s,lp=min(lasts,key=lambda z:(max(int(root["availability_time"]),int(ctx["availability_time"]),int(z[0]["availability_time"]),int(z[1]["availability_time"])),str(z[1]["subject_id"])))
                ready_time=max(int(root["availability_time"]),int(ctx["availability_time"]),int(s["availability_time"]),int(lp["availability_time"]))
                ready_event=max(int(root["event_time"]),int(ctx["event_time"]),int(s["event_time"]),int(lp["event_time"]))
                ready_trigger=str(lp["subject_id"])

    elif family=="G9_STRUCTURAL_PULLBACK_CONTINUATION":
        structures={}
        for r in root_refs(root):
            if str(r.get("source_group"))=="group3" and str(r.get("source_type"))=="structure_states":
                for s in linked_subjects(idx,"group3","structure_states",str(r.get("source_id")),{"dow_advancing_structure","dow_declining_structure"}):
                    if s["direction"]==root["direction"] and s["symbol"]==root["symbol"] and s["timeframe"]==root["timeframe"]:structures[str(s["subject_id"])]=s
        for s in linked_subjects(idx,"group8","narrative_hypothesis",str(root["subject_id"]),{"dow_protected_pullback"}):
            if s["direction"]==root["direction"]:structures[str(s["subject_id"])]=s
        confirmations=linked_subjects(idx,"group8","narrative_hypothesis",str(root["subject_id"]),{"pa_continuation_after_pullback"})
        confirmations=[s for s in confirmations if s["direction"]==root["direction"] and s["symbol"]==root["symbol"] and s["timeframe"]==root["timeframe"]]
        for s in structures.values():supports.append((s,["structure"],"SHARED_UPSTREAM",1));mandatory_ids.append(("school_interpretation",str(s["subject_id"])))
        for c in confirmations:supports.append((c,["confirmation"],"DIRECT_REF",1));mandatory_ids.append(("narrative_hypothesis",str(c["subject_id"])))
        if structures and confirmations:
            s=min(structures.values(),key=lambda x:(int(x["availability_time"]),str(x["subject_id"])))
            c=min(confirmations,key=lambda x:(int(x["availability_time"]),str(x["subject_id"])))
            ready_time=max(int(root["availability_time"]),int(s["availability_time"]),int(c["availability_time"]))
            ready_event=max(int(root["event_time"]),int(s["event_time"]),int(c["event_time"]));ready_trigger=str(c["subject_id"])

    else:
        mss=linked_by_any_root_ref(idx,root,{"ict_mss_fvg_delivery"})
        mss=[s for s in mss if s["direction"]==root["direction"]]
        poi=linked_by_any_root_ref(idx,root,{"ict_return_to_imbalance","ict_block_delivery_context"})
        poi=[s for s in poi if s["direction"] in (root["direction"],"neutral")]
        optional=linked_by_any_root_ref(idx,root,{"ict_premium_discount_context","ict_draw_on_liquidity_context"})
        for s in mss:supports.append((s,["structure","confirmation"],"SHARED_UPSTREAM",1));mandatory_ids.append(("school_interpretation",str(s["subject_id"])))
        for s in poi:
            comp="retracement" if s["definition_id"]=="ict_return_to_imbalance" else "poi"
            supports.append((s,[comp],"SHARED_UPSTREAM",1));mandatory_ids.append(("school_interpretation",str(s["subject_id"])))
        for s in optional:
            comp="location" if s["definition_id"]=="ict_premium_discount_context" else "liquidity"
            supports.append((s,[comp],"SHARED_UPSTREAM",0))
        if mss and poi:
            a=min(mss,key=lambda x:(int(x["availability_time"]),str(x["subject_id"])))
            b=min(poi,key=lambda x:(int(x["availability_time"]),str(x["subject_id"])))
            ready_time=max(int(root["availability_time"]),int(a["availability_time"]),int(b["availability_time"]))
            ready_event=max(int(root["event_time"]),int(a["event_time"]),int(b["event_time"]));ready_trigger=str(b["subject_id"])

    support_eids={}
    for s,components,method,mandatory in supports:
        for comp in components:
            support_eids[(str(s["subject_id"]),comp)]=insert_evidence(out,sid=sid,component=comp,src=s,link_method=method,mandatory=mandatory,family_stats=fs)

    inv=invalidation(idx,mandatory_ids)
    inv_time=None if inv is None else int(inv["availability_time"])
    forming_event=int(root["event_time"]);forming_time=int(root["availability_time"])
    insert_transition(out,sid=sid,ordinal=0,from_state=None,to_state="FORMING",event=forming_event,avail=forming_time,reason="ROOT_AVAILABLE",trigger=ev_ids[0] if ev_ids else None,family_stats=fs)
    ordinal=1
    final_state="FORMING";state_event=forming_event;state_avail=forming_time

    if ready_time is None:
        if inv is not None:
            final_state="FAILED";state_event=int(inv["event_time"]);state_avail=inv_time
            insert_transition(out,sid=sid,ordinal=ordinal,from_state="FORMING",to_state="FAILED",event=state_event,avail=state_avail,reason="AUTHORITATIVE_INVALIDATION_BEFORE_READY",trigger=None,family_stats=fs)
        else:
            censor=int(idx.execute("SELECT censor_time FROM annual_boundary WHERE dataset_year=?",(int(sample["dataset_year"]),)).fetchone()[0])
            censor=max(censor,int(root["availability_time"]))
            final_state="MISSING";state_event=censor;state_avail=censor
            insert_transition(out,sid=sid,ordinal=ordinal,from_state="FORMING",to_state="MISSING",event=censor,avail=censor,reason="RIGHT_CENSORED_MISSING_COMPONENT",trigger=None,family_stats=fs)
    elif inv_time is not None and inv_time<=ready_time:
        final_state="FAILED";state_event=int(inv["event_time"]);state_avail=inv_time
        insert_transition(out,sid=sid,ordinal=ordinal,from_state="FORMING",to_state="FAILED",event=state_event,avail=state_avail,reason="AUTHORITATIVE_INVALIDATION_BEFORE_READY",trigger=None,family_stats=fs)
    else:
        trig=None
        for (source_id,comp),eid in support_eids.items():
            if source_id==ready_trigger:trig=eid;break
        final_state="READY";state_event=int(ready_event);state_avail=int(ready_time)
        insert_transition(out,sid=sid,ordinal=ordinal,from_state="FORMING",to_state="READY",event=state_event,avail=state_avail,reason="MANDATORY_COMPONENTS_CAUSALLY_COMPLETE",trigger=trig,family_stats=fs);ordinal+=1
        if inv is not None and inv_time>ready_time:
            final_state="INVALIDATED";state_event=int(inv["event_time"]);state_avail=inv_time
            insert_transition(out,sid=sid,ordinal=ordinal,from_state="READY",to_state="INVALIDATED",event=state_event,avail=state_avail,reason="AUTHORITATIVE_INVALIDATION_AFTER_READY",trigger=None,family_stats=fs)

    base={"setup_id":sid,"setup_family":family,"root_subject_type":str(root["subject_type"]),"root_subject_id":str(root["subject_id"]),
          "root_definition_id":str(root["definition_id"]),"symbol":str(root["symbol"]),"timeframe":str(root["timeframe"]),"direction":str(root["direction"]),
          "origin_event_time":int(root["event_time"]),"origin_availability_time":int(root["availability_time"]),"current_state":final_state,
          "state_event_time":state_event,"state_availability_time":state_avail,"definition_version":version,"parent_lineage_hash":str(root["row_hash"]),"features_json":features}
    sh=stable(base)
    row=(sid,sh,family,str(root["subject_type"]),str(root["subject_id"]),str(root["definition_id"]),str(root["symbol"]),str(root["timeframe"]),str(root["direction"]),
         int(root["event_time"]),int(root["availability_time"]),final_state,int(state_event),int(state_avail),version,str(root["row_hash"]),features)
    out.execute("""UPDATE setup_instance SET setup_hash=?,current_state=?,state_event_time=?,state_availability_time=? WHERE setup_id=?""",
                (sh,final_state,int(state_event),int(state_avail),sid))
    fs["setup_rows"]+=1;fs["logical_bytes"]+=canonical_row_bytes(row);fs["states_"+final_state]=fs.get("states_"+final_state,0)+1


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--inventory-db",type=Path,required=True)
    p.add_argument("--inventory-report",type=Path,required=True)
    p.add_argument("--dependency-intake",type=Path,required=True)
    p.add_argument("--g9-definitions",type=Path,required=True)
    p.add_argument("--g9-schema",type=Path,required=True)
    p.add_argument("--stage5-archive-report",type=Path,action="append",required=True)
    p.add_argument("--stage5-archive",type=Path,action="append",required=True)
    p.add_argument("--stage7-release",type=Path,action="append",required=True)
    p.add_argument("--stage7-output-root",type=Path,action="append",required=True)
    p.add_argument("--zstd-exe",type=Path,required=True)
    p.add_argument("--scratch-root",type=Path,required=True)
    p.add_argument("--sample-count",type=int,default=12000)
    p.add_argument("--support-index",type=Path,required=True)
    p.add_argument("--sample-output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()

    dep=load_hashed(a.dependency_intake);invrep=load_hashed(a.inventory_report);defs=load_hashed(a.g9_definitions)
    if dep.get("status")!="PASS" or invrep.get("status")!="PASS" or defs.get("status")!="FROZEN":raise RuntimeError("upstream benchmark gate not PASS")
    if dep.get("semantic_registry_hash")!=defs.get("registry_hash") or invrep.get("semantic_registry_hash")!=defs.get("registry_hash"):raise RuntimeError("semantic identity drift")
    if len(a.stage5_archive_report)!=len(a.stage5_archive) or len(a.stage7_release)!=len(a.stage7_output_root):raise RuntimeError("source argument count mismatch")
    a.scratch_root.mkdir(parents=True,exist_ok=True)

    inv=sqlite3.connect(f"file:{a.inventory_db.resolve()}?mode=ro&immutable=1",uri=True);inv.row_factory=sqlite3.Row
    idx=init_index(a.support_index);idx.row_factory=sqlite3.Row
    sample=select_sample(inv,idx,a.sample_count)
    sample_ids_by_year=defaultdict(set)
    for r in idx.execute("SELECT dataset_year,source_id FROM benchmark_sample"):sample_ids_by_year[int(r[0])].add(str(r[1]))

    build_started=time.perf_counter();source_reports=[];largest_restore=0
    for rp,ap in zip(a.stage5_archive_report,a.stage5_archive):
        rep=load_hashed(rp);year=int(rep["year"]);largest_restore=max(largest_restore,int(rep["raw_size_bytes"]))
        raw,dec=restore_stage5(a.zstd_exe,ap,rep,a.scratch_root)
        rr=build_stage5_index(idx=idx,raw=raw,year=year,sample_ids=sample_ids_by_year[year]);rr["decompression_seconds"]=dec;source_reports.append({"stage5":rr})
        raw.unlink(missing_ok=True);restore_marker_path(raw).unlink(missing_ok=True)
    for rp,root in zip(a.stage7_release,a.stage7_output_root):
        rel=load_hashed(rp);source_reports.append({"stage7":build_stage7_index(idx=idx,release=rel,output_root=root,zstd=a.zstd_exe,scratch=a.scratch_root,sample_ids=sample_ids_by_year[int(rel["year"])])})
    idx.commit();build_seconds=time.perf_counter()-build_started
    support_index_bytes=a.support_index.stat().st_size

    missing_samples=int(idx.execute("""SELECT COUNT(*) FROM benchmark_sample b LEFT JOIN subject s ON s.subject_id=b.source_id WHERE s.subject_id IS NULL""").fetchone()[0])
    if missing_samples:raise RuntimeError(f"sample roots missing from source index:{missing_samples}")

    out=init_sample_output(a.sample_output,a.g9_schema);out.execute("PRAGMA foreign_keys=ON")
    stats=defaultdict(lambda:{"roots":0,"setup_rows":0,"evidence_rows":0,"transition_rows":0,"logical_bytes":0})
    mat_started=time.perf_counter()
    for s in idx.execute("SELECT * FROM benchmark_sample ORDER BY dataset_year,setup_family,root_key"):
        t=time.perf_counter();before=stats[str(s["setup_family"])]["roots"]
        materialize_one(idx,out,s,str(defs["definition_version"]),stats)
        stats[str(s["setup_family"])]["runtime_ns"]=stats[str(s["setup_family"])].get("runtime_ns",0)+int((time.perf_counter()-t)*1e9)
    out.commit();mat_seconds=time.perf_counter()-mat_started
    qc=out.execute("PRAGMA quick_check").fetchone()[0]
    if qc!="ok":raise RuntimeError("sample output quick_check failed")
    fk=out.execute("PRAGMA foreign_key_check").fetchall()
    if fk:raise RuntimeError(f"sample output foreign key failures:{len(fk)}")
    sample_output_bytes=a.sample_output.stat().st_size
    sample_count=int(sample["actual"]);population=int(sample["population"])
    if sample_count<=0:raise RuntimeError("empty benchmark sample")

    family_pop={str(k):int(v) for k,v in inv.execute("SELECT setup_family,COUNT(*) FROM root_candidate GROUP BY setup_family")}
    family_stats={}
    projected_materialization=0.0
    projected_logical_bytes=0.0
    sample_logical_bytes=0
    for fam,v in stats.items():
        roots=max(int(v["roots"]),1);runtime=float(v.get("runtime_ns",0))/1e9
        pop=family_pop.get(fam,0)
        projected_family_seconds=runtime/roots*pop
        projected_family_logical=(float(v["logical_bytes"])/roots)*pop
        projected_materialization+=projected_family_seconds
        projected_logical_bytes+=projected_family_logical
        sample_logical_bytes+=int(v["logical_bytes"])
        family_stats[fam]={**{k:int(x) for k,x in v.items() if k!="runtime_ns"},"sample_runtime_seconds":runtime,
                           "seconds_per_root":runtime/roots,"population":pop,
                           "projected_family_seconds":projected_family_seconds,
                           "projected_family_logical_bytes":projected_family_logical}
    projected_total=build_seconds+projected_materialization
    sqlite_overhead_factor=sample_output_bytes/max(sample_logical_bytes,1)
    projected_output=int(math.ceil(projected_logical_bytes*sqlite_overhead_factor))
    projected_hours=projected_total/3600.0
    recommended_shards=max(1,math.ceil(projected_output/1_500_000_000))
    projected_per_shard=int(math.ceil(projected_output/recommended_shards))
    hard_runtime_pass=projected_hours<=48.0
    runtime_target_met=projected_hours<=24.0
    hard_shard_pass=projected_per_shard<=2_500_000_000

    report={
      "format_version":1,"group":9,"scope":"REAL_SETUP_STATE_REPRESENTATIVE_BENCHMARK",
      "status":"PASS" if hard_runtime_pass and hard_shard_pass else "BLOCKED",
      "semantic_registry_hash":defs["registry_hash"],"definition_version":defs["definition_version"],
      "dependency_intake_report_hash":dep["report_hash"],"inventory_report_hash":invrep["report_hash"],
      "candidate_population":population,"sample":sample,"source_reports":source_reports,
      "support_index_build_seconds":build_seconds,"support_index_bytes":support_index_bytes,
      "sample_materialization_seconds":mat_seconds,"sample_output_bytes":sample_output_bytes,
      "projected_materialization_seconds":projected_materialization,"projected_total_seconds":projected_total,
      "projected_total_hours":projected_hours,"target_hours":24.0,"hard_hours":48.0,
      "runtime_target_met":runtime_target_met,"hard_runtime_pass":hard_runtime_pass,
      "sample_logical_bytes":sample_logical_bytes,"sqlite_overhead_factor":sqlite_overhead_factor,
      "projected_logical_bytes":projected_logical_bytes,"projected_output_bytes":projected_output,"recommended_shard_count":recommended_shards,
      "projected_bytes_per_shard":projected_per_shard,"hard_shard_pass":hard_shard_pass,
      "largest_stage5_restore_bytes":largest_restore,"family_stats":family_stats,
      "sample_output_quick_check":"ok","sample_output_foreign_key_failures":0,
      "outcome_data_accessed":False,"trade_policy_accessed":False,
      "real_annual_materialization_authorized":False,
      "next_gate":"sizing + resource gate; benchmark PASS alone never authorizes annual execution"
    }
    report["report_hash"]=stable(report);atomic_json(a.report,report)
    print(json.dumps(report,indent=2,sort_keys=True))
    out.close();idx.close();inv.close()
    return 0 if report["status"]=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
