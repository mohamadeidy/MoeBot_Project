#!/usr/bin/env python3
"""Read-only audit of recovered Wyckoff pilot rows versus explicit frozen rules.
Diagnostics only: never rewrites Group8, grants production, or changes a rule.
"""
import hashlib,json,sqlite3
from pathlib import Path
from collections import Counter,defaultdict
from contextlib import closing
from bisect import bisect_right

ROOT=Path("D:/MoeBotVault/Group_9/wyckoff_sizing_20261124")
CAT=Path("D:/MoeBotData/group9_scratch/upstream_pa7/official_h1_v2/H1_2023_v2_pa7_candidate_catalog.sqlite")
WORK=Path("C:/MoeBotWork")
OUT=WORK/"group9_wyckoff_semantic_audit_20261128.json"

def stable(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()
def hashed(p):
    d=json.loads(p.read_text(encoding="utf-8"))
    x=dict(d);h=x.pop("report_hash")
    if h!=stable(x):raise RuntimeError("report_hash_mismatch:"+str(p))
    return d
def ro(p):
    c=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    c.row_factory=sqlite3.Row
    return c
def write_report(p,d):
    d["report_hash"]=stable(d)
    t=p.with_suffix(".json.tmp")
    with t.open("x",encoding="utf-8") as f:
        json.dump(d,f,sort_keys=True,indent=2);f.flush()
        import os
        os.fsync(f.fileno())
    t.replace(p)

def main():
    if OUT.exists():
        print("AUDIT_ALREADY_EXISTS="+hashed(OUT)["status"],flush=True);return
    receipt=hashed(CAT.parent/"verified_H1_source_catalog_receipt.json")
    if sha(CAT)!=receipt["catalog_sha256"]:raise RuntimeError("PA7_catalog_identity")
    summary=hashed(ROOT/"monthly_sizing_summary.json")
    total=Counter();months=[];examples=defaultdict(list)
    with closing(ro(CAT)) as cat:
        failed=defaultdict(list)
        for row in cat.execute("SELECT candidate_id,availability_time,features_json FROM pa7_candidate_catalog WHERE definition_id='pa_failed_breakout' AND symbol='XAUUSD_' AND timeframe='H1' ORDER BY availability_time,candidate_id"):
            f=json.loads(row["features_json"]);bid=f.get("breakout_candidate_id")
            if bid:failed[bid].append((int(row["availability_time"]),row["candidate_id"]))
        print("FAILED_BREAKOUT_PARENT_KEYS="+str(len(failed)),flush=True)
        for row in summary["months"]:
            month=row["month"];folder=ROOT/month
            report=hashed(folder/"pilot_report.json");transfer=hashed(folder/"transfer_receipt.json")
            if report["report_hash"]!=row["report_hash"] or transfer["pilot_report_hash"]!=report["report_hash"]:
                raise RuntimeError("pilot_lineage_drift:"+month)
            dbpath=folder/"bounded_frozen_producer.sqlite"
            file=next(x for x in transfer["files"] if x["name"]==dbpath.name)
            if dbpath.stat().st_size!=file["size_bytes"] or sha(dbpath)!=file["sha256"]:
                raise RuntimeError("pilot_database_drift:"+month)
            counts=Counter()
            with closing(ro(dbpath)) as db:
                signs={}
                for s in db.execute("SELECT * FROM school_interpretation WHERE definition_id IN ('wyckoff_sign_of_strength','wyckoff_sign_of_weakness')"):
                    refs=json.loads(s["upstream_refs_json"])
                    ctx=db.execute("SELECT * FROM school_interpretation WHERE interpretation_id=?",(refs[0]["source_id"],)).fetchone()
                    br=cat.execute("SELECT * FROM pa7_candidate_catalog WHERE candidate_id=?",(refs[2]["source_id"],)).fetchone()
                    if ctx is None or br is None:raise RuntimeError("missing_sign_parent")
                    counts["sign_rows"]+=1
                    if int(br["availability_time"])<int(ctx["availability_time"]):
                        counts["breakout_precedes_context_availability"]+=1
                    signs[s["interpretation_id"]]=(s,br)
                for lp in db.execute("SELECT * FROM school_interpretation WHERE definition_id IN ('wyckoff_last_point_of_support','wyckoff_last_point_of_supply')"):
                    refs=json.loads(lp["upstream_refs_json"])
                    sign,br=signs[refs[0]["source_id"]]
                    ret=cat.execute("SELECT * FROM pa7_candidate_catalog WHERE candidate_id=?",(refs[1]["source_id"],)).fetchone()
                    if ret is None:raise RuntimeError("missing_retest_parent")
                    counts["last_point_rows"]+=1
                    feat=json.loads(ret["features_json"])
                    wanted="above" if lp["direction"]=="bullish" else "below"
                    side=feat.get("close_side")
                    issues=[]
                    if side is None:
                        counts["retest_close_side_unknown"]+=1;issues.append("retest_close_side_unknown")
                    elif side!=wanted:
                        counts["retest_close_side_mismatch"]+=1;issues.append("retest_close_side_mismatch")
                    if feat.get("breakout_candidate_id")!=br["candidate_id"]:
                        counts["retest_parent_breakout_id_differs"]+=1
                    # Strictly linked failure of this exact breakout, after breakout
                    # availability but at/before last point availability.
                    prior=[(t,i) for t,i in failed.get(br["candidate_id"],[]) if int(br["availability_time"])<t<=int(lp["availability_time"])]
                    if prior:
                        counts["linked_failure_available_by_last_point"]+=1;issues.append("linked_failure_available_by_last_point")
                    if issues:
                        counts["last_points_with_explicit_issue"]+=1
                        for issue in issues:
                            if len(examples[issue])<3:
                                examples[issue].append({"month":month,"last_point_id":lp["interpretation_id"],"sign_id":sign["interpretation_id"],"breakout_id":br["candidate_id"],"retest_id":ret["candidate_id"],"required_close_side":wanted,"observed_close_side":side,"prior_failure":prior[:1]})
            total.update(counts);months.append({"month":month,**counts})
            print("SEMANTIC_AUDIT_MONTH="+month+" "+json.dumps(counts,sort_keys=True),flush=True)
    report={"status":"BLOCKED_EXPLICIT_RETEST_RULE_VIOLATIONS" if total["last_points_with_explicit_issue"] else "INDETERMINATE_REQUIRES_FULL_SEMANTIC_AUDIT",
            "scope":"96_PREDETERMINED_2023_H1_ROOTS_DERIVED_ROWS_ONLY","monthly_sizing_report_hash":summary["report_hash"],
            "counts":dict(total),"months":months,"examples":dict(examples),
            "pre_context_breakouts_and_parent_id_differences_are_diagnostics_not_automatically_rule_violations":True,
            "active_context_and_annual_invalidation_completeness_verified":False,
            "annual_execution_authorized":False,"frozen_group8_modified":False}
    write_report(OUT,report)
    print("SEMANTIC_AUDIT_RESULT="+json.dumps({"status":report["status"],"counts":report["counts"]},sort_keys=True),flush=True)
if __name__=="__main__":main()
