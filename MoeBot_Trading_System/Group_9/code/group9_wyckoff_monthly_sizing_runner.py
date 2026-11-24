#!/usr/bin/env python3
"""Bounded real-data month-by-month sizing; never an annual execution grant."""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

P=pathlib.Path
ROOT=P("D:/MoeBotVault/Group_9/wyckoff_sizing_20261124")
WORK=P("C:/MoeBotWork")
PILOT=P(__file__).with_name("group9_real_wyckoff_derived_pilot.py")
MONTHS=[f"2023-{m:02d}" for m in range(1,13)]

def stable(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(8*1024*1024),b""):h.update(block)
    return h.hexdigest()

def hashed(p):
    obj=json.loads(p.read_text(encoding="utf-8"))
    body=dict(obj);expected=body.pop("report_hash")
    if expected!=stable(body):raise RuntimeError("hash_mismatch:"+str(p))
    return obj

def verified_month(month):
    d=ROOT/month
    r=hashed(d/"pilot_report.json")
    t=hashed(d/"transfer_receipt.json")
    if (r["status"]!="PASS_BOUNDED_WYCKOFF_DERIVED_GRAPH_PARITY" or
        r["roots"]!=8 or r["sample_month"]!=month or
        t["status"]!="PASS" or t["pilot_report_hash"]!=r["report_hash"] or
        r["compression"]["lossless_roundtrip_verified"] is not True):
        raise RuntimeError("invalid_month_receipt:"+month)
    for f in t["files"]:
        p=d/f["name"]
        if p.stat().st_size!=f["size_bytes"] or sha(p)!=f["sha256"]:
            raise RuntimeError("vault_file_drift:"+str(p))
    a=d/"augmented.sqlite.zst";raw=d/"augmented.sqlite"
    if (sha(a)!=r["compression"]["archive_sha256"] or
        sha(raw)!=r["compression"]["raw_sha256"]):
        raise RuntimeError("compressed_payload_drift:"+month)
    return r

def write_new(p,r):
    body=dict(r);body["report_hash"]=stable(body)
    with p.open("x",encoding="utf-8") as f:
        json.dump(body,f,indent=2,sort_keys=True);f.write("\n")

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    plan=hashed(WORK/"group9_exact_shard_plan_20261118.json")
    counts={m:sum(s["candidate_count_exact"] for s in plan["shards"]
         if s["year"]==2023 and s["timeframe"]=="H1" and s["root_month"]==m) for m in MONTHS}
    final=ROOT/"monthly_sizing_summary.json"
    if final.exists():
        report=hashed(final)
        for m in MONTHS:verified_month(m)
        print("VERIFIED_SIZING_ALREADY_COMPLETE",flush=True);return 0
    all_rows=[]
    for month in MONTHS:
        if (ROOT/month).exists():
            r=verified_month(month)
        else:
            print("START_MONTH="+month,flush=True)
            subprocess.run([sys.executable,"-u",str(PILOT),"--roots","8","--month",month],
                           check=True,timeout=900)
            r=verified_month(month)
        c=r["compression"];n=r["roots"]
        row={"month":month,"sample_roots":n,"population_h1_all_families":counts[month],
             "raw_bytes":c["raw_bytes"],"compressed_bytes":c["archive_bytes"],
             "evidence_rows":r["with_derived"]["evidence_rows"],
             "producer_seconds":r["producer_seconds"],"materializer_seconds":r["materializer_seconds"],
             "report_hash":r["report_hash"],
             "illustrative_population_raw_bytes":round(counts[month]*c["raw_bytes"]/n),
             "illustrative_population_compressed_bytes":round(counts[month]*c["archive_bytes"]/n)}
        all_rows.append(row)
        print("VERIFIED_MONTH="+json.dumps(row,sort_keys=True),flush=True)
    report={"status":"PASS_BOUNDED_12_MONTH_SIZING_ONLY","months":all_rows,
        "sample_roots":sum(x["sample_roots"] for x in all_rows),
        "population_h1_all_families":sum(counts.values()),
        "illustrative_total_raw_bytes":sum(x["illustrative_population_raw_bytes"] for x in all_rows),
        "illustrative_total_compressed_bytes":sum(x["illustrative_population_compressed_bytes"] for x in all_rows),
        "projection_limits":"Eight first deterministic root keys per month, Wyckoff only; population includes small other-family share. Tiny-shard overhead, compression, sampling, and incomplete invalidation coverage mean no annual guarantee.",
        "full_annual_coverage_verified":False,"derived_invalidation_completeness_verified":False,
        "annual_execution_authorized":False,"previous_plan_hash":plan["report_hash"]}
    write_new(final,report)
    print("MONTHLY_SIZING_COMPLETE="+str(final),flush=True)
    print("ILLUSTRATIVE_RAW_BYTES="+str(report["illustrative_total_raw_bytes"]),flush=True)
    print("ILLUSTRATIVE_COMPRESSED_BYTES="+str(report["illustrative_total_compressed_bytes"]),flush=True)
    return 0

if __name__=="__main__":raise SystemExit(main())
