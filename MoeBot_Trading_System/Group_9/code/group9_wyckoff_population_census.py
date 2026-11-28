#!/usr/bin/env python3
"""Resumable full Wyckoff parent census, NOT production setup materialization.

Scans the immutable 2023 Stage5 school surface in availability partitions.
Exact root counts and independent order-insensitive ID/hash fingerprints must
match the frozen root inventory by event month. Retains all root multiplicities
and context-to-range identities for subsequent rule-correct sizing.
Active SQLite files on C:, verified copies/receipts on D:. No Group8 writes.
"""
from collections import Counter,defaultdict
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,os,shutil,sqlite3,time
from pathlib import Path

WORK=Path("C:/MoeBotWork")
ACTIVE=WORK/"group9_active"/"wyckoff_population_census_20261128"
VAULT=Path("D:/MoeBotVault/Group_9/wyckoff_population_census_20261128")
SOURCE=Path("D:/MoeBotData/group8_v3_full_surface_recovery/stage5_2023.sqlite")
INV=Path("D:/MoeBotData/group9_scratch/group9_root_inventory.sqlite")
SOURCE_REPORT=WORK/"group8_v3_stage5_2023_archive_report.json"
INV_REPORT=WORK/"group9_root_inventory.json"
SEMANTIC_AUDIT=WORK/"group9_wyckoff_semantic_audit_20261128.json"
FAMILY="G9_WYCKOFF_RANGE_RESOLUTION"
ROOTS=("wyckoff_spring_candidate","wyckoff_upthrust_candidate")
CTX="wyckoff_range_context"
MASK=(1<<256)-1
GIB=1<<30
MONTHS=[f"2023-{m:02d}" for m in range(1,13)]
SCHEMA="""
CREATE TABLE root_multiplicity(context_id TEXT NOT NULL,direction TEXT NOT NULL,event_month TEXT NOT NULL,root_count INTEGER NOT NULL,PRIMARY KEY(context_id,direction,event_month)) WITHOUT ROWID;
CREATE TABLE range_context(context_id TEXT PRIMARY KEY,range_candidate_id TEXT NOT NULL,availability_time INTEGER NOT NULL,context_hash TEXT NOT NULL) WITHOUT ROWID;
"""
def stable(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def hashed(p):
    d=json.loads(p.read_text(encoding="utf-8"));x=dict(d);h=x.pop("report_hash")
    if h!=stable(x):raise RuntimeError("report_hash_mismatch:"+str(p))
    return d
def atomic(p,d):
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",encoding="utf-8") as f:
        json.dump(d,f,sort_keys=True,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
    os.replace(t,p)
def receipt(p,d):
    body=dict(d);body["report_hash"]=stable(body);atomic(p,body);return body
def status(stage,**extra):
    atomic(VAULT/"runtime_status.json",{"stage":stage,"updated_utc":datetime.now(timezone.utc).isoformat(),
        "annual_execution_authorized":False,"group9_closed":False,"next_group_authorized":False,**extra})
def sha(p,log=False):
    h=hashlib.sha256();n=0;last=0
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b);n+=len(b)
            if log and n-last>=8*GIB:
                print("HASH_PROGRESS",p.name,n,p.stat().st_size,flush=True);last=n
    return h.hexdigest()
def ro(p):
    c=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    c.execute("PRAGMA query_only=ON");return c
def space(extra=0):
    if shutil.disk_usage("C:/").free<120*GIB+extra:raise RuntimeError("C_SAFETY_FLOOR")
    if shutil.disk_usage("D:/").free<20*GIB+extra:raise RuntimeError("D_SAFETY_FLOOR")
def verify_input(p,n,digest,label):
    rp=VAULT/(label+"_identity.json");st=p.stat()
    expected={"path":str(p),"bytes":n,"mtime_ns":st.st_mtime_ns,"sha256":digest}
    if st.st_size!=n:raise RuntimeError(label+"_size_mismatch")
    if rp.exists():
        prior=hashed(rp)
        if any(prior.get(k)!=v for k,v in expected.items()):raise RuntimeError(label+"_identity_drift")
        return expected
    status("VERIFY_"+label.upper(),bytes=n)
    print("VERIFY_INPUT="+label,flush=True)
    if sha(p,True)!=digest or p.stat().st_mtime_ns!=st.st_mtime_ns:
        raise RuntimeError(label+"_sha_mismatch")
    receipt(rp,{"status":"PASS",**expected});return expected
def check_unchanged(p,identity):
    s=p.stat()
    if s.st_size!=identity["bytes"] or s.st_mtime_ns!=identity["mtime_ns"]:raise RuntimeError("input_changed:"+str(p))
def fold(acc,month,sid,row_hash):
    n=int.from_bytes(hashlib.sha256((sid+":"+row_hash).encode()).digest(),"big")
    a=acc[month];a[0]+=1;a[1]=(a[1]+n)&MASK;a[2]^=n
def encoded(acc):return {m:{"count":v[0],"sum":f"{v[1]:064x}","xor":f"{v[2]:064x}"} for m,v in sorted(acc.items())}
def decoded(x):return {m:(v["count"],int(v["sum"],16),int(v["xor"],16)) for m,v in x.items()}
def combine(acc,x):
    for m,(n,s,z) in decoded(x).items():
        a=acc[m];a[0]+=n;a[1]=(a[1]+s)&MASK;a[2]^=z
def months_at(t):return datetime.fromtimestamp(t,timezone.utc).strftime("%Y-%m")
def bounds(i):
    lo=-(1<<63) if i==0 else int(datetime(2023,i+1,1,tzinfo=timezone.utc).timestamp())
    hi=(1<<63)-1 if i==11 else int(datetime(2023,i+2,1,tzinfo=timezone.utc).timestamp())
    return lo,hi
def integrity(p):
    with closing(ro(p)) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0]!="ok":raise RuntimeError("sqlite_integrity:"+str(p))
def copy_verified(src,dst,expected):
    if dst.exists():
        if dst.stat().st_size!=src.stat().st_size or sha(dst)!=expected:raise RuntimeError("vault_drift:"+str(dst))
        return
    tmp=dst.with_suffix(dst.suffix+".copying")
    if tmp.exists():tmp.unlink()  # only incomplete private destination, never published
    with src.open("rb") as a,tmp.open("xb") as b:
        shutil.copyfileobj(a,b,8*1024*1024);b.flush();os.fsync(b.fileno())
    if tmp.stat().st_size!=src.stat().st_size or sha(tmp)!=expected:raise RuntimeError("copy_hash_mismatch")
    os.replace(tmp,dst)
def verify_artifact(name):
    r=hashed(VAULT/(name+".json"));db=VAULT/(name+".sqlite")
    if r["status"]!="PASS" or not db.is_file() or db.stat().st_size!=r["bytes"] or sha(db)!=r["sha256"]:raise RuntimeError("artifact_drift:"+name)
    return r
def promote(name,meta):
    src=ACTIVE/(name+".sqlite");local=ACTIVE/(name+".json")
    if not local.exists():
        integrity(src)
        receipt(local,{"status":"PASS","bytes":src.stat().st_size,"sha256":sha(src),**meta})
    r=hashed(local)
    if src.stat().st_size!=r["bytes"] or sha(src)!=r["sha256"]:raise RuntimeError("active_artifact_drift")
    copy_verified(src,VAULT/src.name,r["sha256"])
    atomic(VAULT/local.name,r)
    verified=verify_artifact(name)
    src.unlink();local.unlink()
    return verified
def open_new(name):
    p=ACTIVE/(name+".sqlite")
    # A completed C receipt is promoted on resume instead of rebuilt. Other
    # private, incomplete C output can be discarded without touching frozen data.
    for suffix in ("","-journal","-wal","-shm"):
        q=Path(str(p)+suffix)
        if q.exists():q.unlink()
    c=sqlite3.connect(p,uri=True)
    c.execute("PRAGMA journal_mode=DELETE")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-65536")
    c.executescript(SCHEMA)
    return c
def parent_ref(text,kind):
    refs=[r for r in json.loads(text) if r.get("source_type")==kind and r.get("source_group")=="group8"]
    if not refs:raise RuntimeError("missing_parent_ref:"+kind)
    return str(refs[0]["source_id"])
def scan_partition(i,source_identity):
    month=MONTHS[i];name="availability_"+month;lo,hi=bounds(i)
    if (VAULT/(name+".json")).exists():
        r=verify_artifact(name)
        if r["source_sha256"]!=source_identity["sha256"] or r["availability_bounds"]!=[lo,hi]:
            raise RuntimeError("partition_input_drift")
        return r
    if (ACTIVE/(name+".json")).exists():return promote(name,{})
    space(3*GIB);check_unchanged(SOURCE,source_identity)
    status("SCAN_STAGE5",availability_partition=month,completed_partitions=i)
    print("START_POPULATION_PARTITION="+month,flush=True)
    t=time.perf_counter();acc=defaultdict(lambda:[0,0,0]);roots=ctxs=seen=0;pending=Counter();contexts=[]
    with closing(ro(SOURCE)) as src, closing(open_new(name)) as out:
        q="""SELECT interpretation_id,definition_id,direction,event_time,availability_time,interpretation_hash,upstream_refs_json
             FROM school_interpretation INDEXED BY ix_school_interpretation_tf_avail
             WHERE symbol='XAUUSD_' AND timeframe='H1' AND availability_time>=? AND availability_time<?
             AND school_id='school_wyckoff_v1' AND definition_id IN (?,?,?) ORDER BY availability_time"""
        def flush():
            if pending:
                out.executemany("INSERT INTO root_multiplicity VALUES(?,?,?,?) ON CONFLICT(context_id,direction,event_month) DO UPDATE SET root_count=root_count+excluded.root_count",
                    ((*key,n) for key,n in pending.items()));pending.clear()
            if contexts:out.executemany("INSERT INTO range_context VALUES(?,?,?,?)",contexts);contexts.clear()
            out.commit()
        for sid,definition,direction,event,avail,row_hash,refs in src.execute(q,(lo,hi,*ROOTS,CTX)):
            seen+=1
            if definition==CTX:
                contexts.append((sid,parent_ref(refs,"price_action_pattern_candidate"),avail,row_hash));ctxs+=1
            else:
                if (definition==ROOTS[0] and direction!="bullish") or (definition==ROOTS[1] and direction!="bearish"):
                    raise RuntimeError("root_direction_mismatch:"+sid)
                m=months_at(event);pending[(parent_ref(refs,"school_interpretation"),direction,m)]+=1
                fold(acc,m,sid,row_hash);roots+=1
            if seen%20000==0:flush()
            if seen%100000==0:
                space();print("POPULATION_PROGRESS",month,"roots",roots,"contexts",ctxs,flush=True)
        flush()
        if out.execute("SELECT COALESCE(SUM(root_count),0) FROM root_multiplicity").fetchone()[0]!=roots or out.execute("SELECT COUNT(*) FROM range_context").fetchone()[0]!=ctxs:
            raise RuntimeError("partition_count_mismatch")
    check_unchanged(SOURCE,source_identity)
    r=promote(name,{"source_sha256":source_identity["sha256"],"availability_partition":month,
        "availability_bounds":[lo,hi],"root_count":roots,"context_count":ctxs,
        "root_fingerprints_by_event_month":encoded(acc),"seconds":time.perf_counter()-t})
    print("POPULATION_PARTITION_PASS",month,"roots",roots,"contexts",ctxs,flush=True);return r
def inventory_fingerprint(identity,expected_count):
    p=VAULT/"inventory_fingerprint.json"
    if p.exists():
        r=hashed(p)
        if r["inventory_sha256"]!=identity["sha256"]:raise RuntimeError("inventory_fingerprint_drift")
        return r
    status("VERIFY_ROOT_SET_AGAINST_INVENTORY")
    acc=defaultdict(lambda:[0,0,0]);n=0
    with closing(ro(INV)) as db:
        for sid,h,m in db.execute("SELECT source_id,source_row_hash,root_month FROM root_candidate NOT INDEXED WHERE dataset_year=2023 AND symbol='XAUUSD_' AND timeframe='H1' AND setup_family=?",(FAMILY,)):
            fold(acc,m,sid,h);n+=1
            if n%1000000==0:print("INVENTORY_FINGERPRINT_PROGRESS",n,flush=True)
    check_unchanged(INV,identity)
    if n!=expected_count:raise RuntimeError("inventory_count_mismatch")
    return receipt(p,{"status":"PASS","inventory_sha256":identity["sha256"],"root_count":n,"root_fingerprints_by_event_month":encoded(acc)})
def union(parts,source_identity,inventory):
    name="exact_parent_census"
    if (VAULT/(name+".json")).exists():return verify_artifact(name)
    if (ACTIVE/(name+".json")).exists():return promote(name,{})
    space(5*GIB);status("BUILD_EXACT_PARENT_UNION",completed_partitions=12)
    with closing(open_new(name)) as out:
        for i,p in enumerate(parts):
            db=VAULT/("availability_"+p["availability_partition"]+".sqlite")
            out.execute("ATTACH DATABASE ? AS shard",(db.resolve().as_uri()+"?mode=ro&immutable=1",))
            out.execute("INSERT INTO range_context SELECT * FROM shard.range_context")
            out.execute("INSERT INTO root_multiplicity SELECT * FROM shard.root_multiplicity WHERE 1 ON CONFLICT(context_id,direction,event_month) DO UPDATE SET root_count=root_count+excluded.root_count")
            out.commit();out.execute("DETACH DATABASE shard");space()
            print("UNION_PARTITION="+p["availability_partition"],flush=True)
        roots=out.execute("SELECT SUM(root_count) FROM root_multiplicity").fetchone()[0]
        contexts=out.execute("SELECT COUNT(*) FROM range_context").fetchone()[0]
        missing=out.execute("SELECT COUNT(*) FROM root_multiplicity m LEFT JOIN range_context c USING(context_id) WHERE c.context_id IS NULL").fetchone()[0]
        if roots!=inventory["root_count"] or contexts!=sum(p["context_count"] for p in parts) or missing:
            raise RuntimeError("union_parent_coverage_mismatch")
        counts=dict(out.execute("SELECT event_month,SUM(root_count) FROM root_multiplicity GROUP BY event_month"))
        if counts!={m:v["count"] for m,v in inventory["root_fingerprints_by_event_month"].items()}:raise RuntimeError("union_month_count_mismatch")
        distinct=out.execute("SELECT COUNT(DISTINCT context_id) FROM root_multiplicity").fetchone()[0]
        out.commit()
    return promote(name,{"scope":"2023_XAUUSD_H1_WYCKOFF_PARENT_CENSUS",
        "root_count":roots,"context_count":contexts,"distinct_referenced_contexts":distinct,
        "unresolved_parent_groups":missing,"root_counts_by_event_month":counts,
        "source_sha256":source_identity["sha256"],"inventory_fingerprint_hash":inventory["report_hash"],
        "partition_report_hashes":[p["report_hash"] for p in parts],"annual_execution_authorized":False})
def main():
    ACTIVE.mkdir(parents=True,exist_ok=True);VAULT.mkdir(parents=True,exist_ok=True)
    space()
    audit=hashed(SEMANTIC_AUDIT)
    sr=hashed(SOURCE_REPORT);ir=hashed(INV_REPORT)
    si=verify_input(SOURCE,sr["raw_size_bytes"],sr["raw_sha256"],"stage5")
    ii=verify_input(INV,ir["inventory_db_bytes"],ir["inventory_db_sha256"],"inventory")
    parts=[scan_partition(i,si) for i in range(12)]
    expected=int(ir["counts_by_family"][FAMILY])
    inv=inventory_fingerprint(ii,expected)
    acc=defaultdict(lambda:[0,0,0])
    for p in parts:combine(acc,p["root_fingerprints_by_event_month"])
    if encoded(acc)!=inv["root_fingerprints_by_event_month"]:raise RuntimeError("full_root_fingerprint_mismatch")
    result=union(parts,si,inv)
    status("CENSUS_COMPLETE_BLOCKED_SEMANTIC_REMEDIATION",completed_partitions=12,
        root_count=result["root_count"],context_count=result["context_count"],
        census_report_hash=result["report_hash"],semantic_audit_hash=audit["report_hash"],
        next_gate="Rule-conformant derived evidence, invalidation completeness, exact sizing and production preflight")
    print("EXACT_PARENT_CENSUS_PASS="+json.dumps(result,sort_keys=True),flush=True)
if __name__=="__main__":
    try:main()
    except Exception as exc:
        status("BLOCKED_CENSUS_ERROR",error=type(exc).__name__+":"+str(exc))
        raise
