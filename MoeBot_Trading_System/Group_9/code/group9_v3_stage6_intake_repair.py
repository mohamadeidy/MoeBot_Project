#!/usr/bin/env python3
"""Verified additive V3 Stage6 intake. Preserve prior inventory and support DB.
Produces a new candidate union inventory and separate complete Stage6 support
index; does NOT certify production, alter frozen definitions or reconstruct G8.
"""
from collections import Counter
from contextlib import closing
from pathlib import Path
import json, shutil, sqlite3, os
from group9_real_root_inventory import (
    load_hashed, sha256_file, stable, atomic_json, insert_rows, logical_fingerprint)
from group9_real_setup_benchmark import init_index, insert_subject, index_support_refs

W=Path("C:/MoeBotWork")
S=Path("D:/MoeBotData/group9_scratch")
A=W/"group9_active"/"v3_stage6_intake_20261128"
V=Path("D:/MoeBotVault/Group_9/v3_stage6_intake_20261128")
DEFS={"wyckoff_range_context","wyckoff_spring_candidate","wyckoff_upthrust_candidate"}
ROOTS=DEFS-{"wyckoff_range_context"}
COLS="interpretation_id,definition_id,symbol,timeframe,direction,event_time,availability_time,interpretation_hash,upstream_refs_json"
def require(ok,reason):
    if not ok:raise RuntimeError(reason)
def ro(p):
    c=sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    c.execute("PRAGMA query_only=ON");return c
def copy_verified(src,dst,digest):
    require(not dst.exists(),"destination_exists:"+str(dst))
    with src.open("rb") as f,dst.open("xb") as g:
        shutil.copyfileobj(f,g,8*1024*1024);g.flush();os.fsync(g.fileno())
    require(dst.stat().st_size==src.stat().st_size and sha256_file(dst)==digest,"copy_hash_mismatch")
def main():
    require(not A.exists() and not V.exists(),"preserve_prior_attempt")
    require(shutil.disk_usage("C:/").free>=132*1024**3,"C_storage_floor")
    require(shutil.disk_usage("D:/").free>=40*1024**3,"D_storage_floor")
    cp=load_hashed(W/"group8_checkpoint3.json")
    require(cp["status"]=="PASS" and cp["officially_closed"] and cp["real_group9_dependency_intake_authorized"],"checkpoint3_gate")
    old=load_hashed(W/"group9_root_inventory.json")
    src=S/"group9_root_inventory.sqlite"
    require(str(src.resolve()).lower()==str(Path(old["inventory_db_path"]).resolve()).lower(),"inventory_path_drift")
    A.mkdir(parents=True)
    invpath=A/"root_inventory_union_candidate.sqlite"
    copy_verified(src,invpath,old["inventory_db_sha256"])
    print("PRIOR_INVENTORY_COPY_HASH=PASS",flush=True)
    totals=Counter();years={};release_ids={}
    idxpath=A/"stage6_support_overlay.sqlite"
    with closing(sqlite3.connect(invpath)) as inv,closing(init_index(idxpath)) as idx,closing(ro(S/"group9_support_index.sqlite")) as prior:
        inv.execute("PRAGMA synchronous=FULL")
        idx.execute("PRAGMA journal_mode=DELETE");idx.execute("PRAGMA synchronous=FULL")
        require(inv.execute("SELECT value FROM inventory_metadata WHERE key='logical_sha256'").fetchone()[0]==old["root_logical_sha256"],"prior_logical_metadata_drift")
        seen=set()
        for year,annual,release,union in (
            (2023,"group8_v3_annual_2023_manifest.json","group8_v3_stage6_release.json","group8_v3_stage6_union_report.json"),
            (2024,"group8_v3_oos_2024/annual_2024_oos_manifest.json","group8_v3_oos_2024/stage6_release.json","group8_v3_oos_2024/stage6_union.json")):
            am=load_hashed(W/annual);rel=load_hashed(W/release);un=load_hashed(W/union)
            key="annual_2023_manifest_hash" if year==2023 else "annual_2024_oos_manifest_hash"
            require(am["manifest_hash"]==cp[key],"annual_checkpoint_mismatch")
            require(un["report_hash"]==cp["union_report_hashes"][f"stage6_{year}"],"union_checkpoint_mismatch")
            require(rel["status"]==un["status"]=="PASS" and rel["release_hash"]==un["stage6_release_hash"]==am["stage6"]["release_hash"],"release_lineage_mismatch")
            require(rel["year"]==year and rel["shard_count"]==len(rel["shards"]),"release_scope_mismatch")
            release_ids[str(year)]=rel["release_hash"]
            stats=Counter();defs=Counter()
            for sh in rel["shards"]:
                p=Path(sh["database"]);m=load_hashed(Path(sh["manifest"]))
                require(m["manifest_hash"]==sh["manifest_hash"] and m["sha256"]==sh["sha256"] and m["year"]==year,"shard_manifest_drift")
                require(p.stat().st_size==sh["file_size_bytes"] and sha256_file(p)==sh["sha256"],"shard_file_drift")
                with closing(ro(p)) as db:
                    actual=Counter()
                    for row in db.execute("SELECT "+COLS+" FROM school_interpretation ORDER BY interpretation_id"):
                        sid,definition,symbol,tf,direction,event,avail,h,refs=row
                        require(definition in DEFS and symbol==rel["symbol"] and tf==sh["timeframe"] and event<=avail,"stage6_scope_or_time_violation")
                        require(sid not in seen,"duplicate_stage6_subject:"+sid);seen.add(sid)
                        actual[definition]+=1
                        oldsub=prior.execute("SELECT dataset_year,definition_id,symbol,timeframe,direction,event_time,availability_time,row_hash,upstream_refs_json FROM subject WHERE subject_id=?",(sid,)).fetchone()
                        if oldsub:
                            require(tuple(oldsub)==(year,definition,symbol,tf,direction,event,avail,h,refs),"prior_subject_identity_conflict:"+sid)
                            stats["support_exact_duplicates"]+=1
                        insert_subject(idx,year=year,subject_type="school_interpretation",row=row,is_sample_root=False)
                        index_support_refs(idx,sid,"school_interpretation",definition,refs)
                        if definition in ROOTS:
                            key="school_interpretation:"+sid
                            prev=inv.execute("SELECT dataset_year,source_id,definition_id,symbol,timeframe,direction,event_time,availability_time,source_row_hash FROM root_candidate WHERE root_key=?",(key,)).fetchone()
                            expected=(year,sid,definition,symbol,tf,direction,event,avail,h)
                            if prev:
                                require(tuple(prev)==expected,"root_identity_conflict:"+sid)
                                stats["root_exact_duplicates"]+=1
                            else:
                                insert_rows(inv,[expected],expected_source_type="school_interpretation")
                                stats["new_roots"]+=1
                    require(dict(actual)=={k:v for k,v in m["definition_coverage"].items() if v},"definition_coverage_mismatch")
                    require(sum(actual.values())==sh["table_row_counts"]["school_interpretation"],"school_count_mismatch")
                    for row in db.execute("SELECT invalidation_id,subject_type,subject_id,rule_id,source_type,source_id,event_time,availability_time,invalidation_hash FROM invalidation_record"):
                        idx.execute("INSERT INTO invalidation VALUES(?,?,?,?,?,?,?,?,?)",row)
                        stats["invalidation_rows"]+=1
                    defs.update(actual)
                inv.commit();idx.commit();stats["verified_shards"]+=1
                print("SHARD_VERIFIED",year,stats["verified_shards"],"/",rel["shard_count"],"new_roots",stats["new_roots"],flush=True)
            require(sum(defs.values())==un["table_row_counts"]["school_interpretation"],"union_count_mismatch")
            require(stats["new_roots"]+stats["root_exact_duplicates"]==sum(defs[d] for d in ROOTS),"root_union_count_mismatch")
            years[str(year)]={"definitions":dict(defs),**dict(stats)}
            totals.update(stats)
        logical=logical_fingerprint(inv)
        inv.execute("UPDATE inventory_metadata SET value=? WHERE key='logical_sha256'",(logical,))
        inv.execute("INSERT INTO inventory_metadata VALUES('stage6_intake_status','CANDIDATE_UNION_NOT_PRODUCTION')")
        inv.commit()
        count=inv.execute("SELECT count(*) FROM root_candidate").fetchone()[0]
        require(count==old["candidate_count"]+totals["new_roots"],"new_inventory_count_mismatch")
        by_year=dict(inv.execute("SELECT dataset_year,count(*) FROM root_candidate GROUP BY dataset_year"))
        for db in (inv,idx):require(db.execute("PRAGMA quick_check").fetchone()[0]=="ok","output_integrity_failed")
        require(idx.execute("SELECT count(*) FROM subject").fetchone()[0]==len(seen),"overlay_subject_count_mismatch")
    report={"status":"PASS_STAGE6_CANDIDATE_UNION_ONLY","years":years,"totals":dict(totals),
            "prior_inventory_hash":old["report_hash"],"prior_root_count":old["candidate_count"],
            "candidate_union_root_count":count,"candidate_union_counts_by_year":by_year,
            "candidate_union_logical_sha256":logical,"stage6_release_hashes":release_ids,
            "checkpoint3_hash":cp["report_hash"],"group8_unchanged":True,
            "production_support_adapter_integrated":False,"mandatory_derived_evidence_resolved":False,
            "annual_execution_authorized":False}
    report["report_hash"]=stable(report);atomic_json(A/"intake_report.json",report)
    V.mkdir(parents=True)
    files=[]
    for p in sorted(A.iterdir()):
        require(p.is_file(),"unexpected_scratch_entry")
        h=sha256_file(p);copy_verified(p,V/p.name,h)
        files.append({"name":p.name,"sha256":h,"bytes":p.stat().st_size})
    receipt={"status":"PASS","report_hash_ref":report["report_hash"],"files":files}
    receipt["report_hash"]=stable(receipt);atomic_json(V/"transfer_receipt.json",receipt)
    for f in files:require(sha256_file(V/f["name"])==f["sha256"],"vault_drift")
    for f in files:(A/f["name"]).unlink()
    A.rmdir()
    print("STAGE6_INTAKE_COMPLETE="+json.dumps(report,sort_keys=True),flush=True)
    print("VERIFIED_VAULT="+str(V),flush=True)
if __name__=="__main__":main()
