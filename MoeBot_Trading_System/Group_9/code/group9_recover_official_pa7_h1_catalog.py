#!/usr/bin/env python3
"""Read-only frozen Group8 PA7/H1 source catalog recovery for Group9.

Downloads verified 2023 H1 v2 PA7 bundles as separate immutable input evidence.
Uses C: as bounded active cache and D: as persistent verified data store.
Builds an *infrastructure* catalog only. Never runs derived interpretations,
Group9 annual shards, MT5, Group8 writers, or any next-group handoff.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request

TAG = "moebot-group8-pa7-annual-2023-v2-arm"
STEMS = ("H1-group8_range-000", "H1-upstream-000", "H1-upstream-001")
C_ROOT = Path(r"C:\MoeBotWork\group9_active\pa7_h1_2023_v2")
D_ROOT = Path(r"D:\MoeBotData\group9_scratch\upstream_pa7\official_h1_v2")
C_FLOOR = 120 * (1024**3)
G8_CODE = Path(r"C:\MoeBotActive\group9-preparation\MoeBot_Trading_System\Group_8\code")
G9_CODE = Path(__file__).resolve().parent
ZSTD = Path(r"C:\MoeBotActive\tools\zstd\zstd-v1.5.7-win64\zstd.exe")
CATALOG = C_ROOT / "H1_2023_v2_pa7_candidate_catalog.sqlite"


def stable(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for buf in iter(lambda: stream.read(8*1024*1024), b""):
            h.update(buf)
    return h.hexdigest()


def require_space(bytes_c):
    free_c = shutil.disk_usage(Path("C:/")).free
    free_d = shutil.disk_usage(Path("D:/")).free
    if free_c < C_FLOOR + bytes_c:
        raise RuntimeError(f"C_safety_floor_violation:free={free_c}:needed={C_FLOOR+bytes_c}")
    if free_d < 20*1024**3:
        raise RuntimeError("D_vault_reserve_below_20GiB")
    print(f"STORAGE_GATE=PASS C_free_GiB={free_c/1024**3:.1f} D_free_GiB={free_d/1024**3:.1f}",
          flush=True)


def atomic_copy(source, dest, expected_size, expected_sha):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size != expected_size or sha(dest) != expected_sha:
            raise RuntimeError("existing_vault_content_drift:" + str(dest))
        return
    tmp = dest.with_suffix(dest.suffix + ".incomplete")
    if tmp.exists():
        raise RuntimeError("incomplete_vault_copy_requires_review:" + str(tmp))
    with source.open("rb") as inp, tmp.open("xb") as out:
        shutil.copyfileobj(inp, out, 8*1024*1024)
        out.flush()
        os.fsync(out.fileno())
    if tmp.stat().st_size != expected_size or sha(tmp) != expected_sha:
        raise RuntimeError("vault_copy_sha_mismatch:" + str(dest))
    os.replace(tmp, dest)


def meta_for(stem):
    dest = D_ROOT / (stem + ".json")
    url = f"https://github.com/mohamadeidy/MoeBot_Project/releases/download/{TAG}/{stem}.json"
    if dest.exists():
        raw = dest.read_bytes()
    else:
        with urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "MoeBotG9OfficialH1Recovery"}
        ), timeout=40) as stream:
            raw = stream.read(1_000_000)
        tmp = C_ROOT / (stem + ".metadata.pending")
        if tmp.exists():
            raise RuntimeError("metadata_temp_exists")
        tmp.write_bytes(raw)
    data = json.loads(raw)
    self_hash = data.get("report_hash")
    check = dict(data)
    check.pop("report_hash", None)
    if self_hash != stable(check):
        raise RuntimeError("official_bundle_metadata_hash_mismatch:" + stem)
    if (data.get("status") != "PASS" or data.get("year") != 2023 or
        data.get("timeframe") != "H1" or len(data.get("shards", [])) != 12 or
        len(data.get("bundle_parts", [])) != 1):
        raise RuntimeError("wrong_official_bundle_scope:" + stem)
    part = data["bundle_parts"][0]
    if (part["filename"] != stem + ".tar.zst.part-000"
        or not part["url"].startswith(
            f"https://github.com/mohamadeidy/MoeBot_Project/releases/download/{TAG}/"
        )):
        raise RuntimeError("unexpected_bundle_origin:" + stem)
    if not dest.exists():
        pending = C_ROOT / (stem + ".metadata.pending")
        atomic_copy(pending, dest, len(raw), hashlib.sha256(raw).hexdigest())
        pending.unlink()
    return data


def recovery_module():
    p = G9_CODE / "group9_recover_official_pa7_staging.py"
    spec = importlib.util.spec_from_file_location("pa7_chunk_recovery", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def acquire_bundle(stem, meta, workers, chunker):
    part = meta["bundle_parts"][0]
    expected_n = int(part["size_bytes"])
    expected_sha = part["sha256"]
    saved = D_ROOT / part["filename"]
    if saved.exists():
        if saved.stat().st_size != expected_n or sha(saved) != expected_sha:
            raise RuntimeError("saved_official_archive_sha_drift:" + stem)
        print("OFFICIAL_ARCHIVE_ALREADY_VERIFIED=" + stem, flush=True)
        return saved
    current = C_ROOT / stem
    segments = current / "segments"
    segments.mkdir(parents=True, exist_ok=True)
    count = (expected_n + chunker.CHUNK_SIZE - 1) // chunker.CHUNK_SIZE
    chunker.DEST_ROOT = current
    print(f"DOWNLOADING={stem} chunks={count} size_bytes={expected_n}", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = [pool.submit(chunker.fetch, part["url"], i, expected_n) for i in range(count)]
        for task in as_completed(jobs):
            task.result()
            done += 1
            if done % 8 == 0 or done == count:
                print(f"DOWNLOAD_PROGRESS={stem} {done}/{count}", flush=True)
    src = current / part["filename"]
    if not src.exists():
        tmp = current / (part["filename"] + ".assembling")
        if tmp.exists():
            tmp.unlink()  # named scratch output only, never upstream evidence
        with tmp.open("xb") as out:
            for i in range(count):
                chunk = segments / f"{i:04d}.part"
                with chunk.open("rb") as f:
                    shutil.copyfileobj(f, out, 8*1024*1024)
        if tmp.stat().st_size != expected_n or sha(tmp) != expected_sha:
            raise RuntimeError("assembled_official_archive_sha_mismatch:" + stem)
        os.replace(tmp, src)
    atomic_copy(src, saved, expected_n, expected_sha)
    shutil.rmtree(current)  # only dedicated verified download cache
    print("OFFICIAL_ARCHIVE_VERIFIED_ON_D=" + stem, flush=True)
    return saved


def extract_verified(stem, meta, saved):
    stage = C_ROOT / (stem + ".extract")
    if stage.exists():
        raise RuntimeError("incomplete_extract_requires_review:" + stem)
    stage.mkdir(parents=True)
    tarpath = C_ROOT / (stem + ".tar")
    if tarpath.exists():
        raise RuntimeError("incomplete_decompress_requires_review:" + stem)
    subprocess.run([str(ZSTD), "-d", "-q", "-f", str(saved), "-o", str(tarpath)],
                   check=True, timeout=240)
    verified = []
    with tarfile.open(tarpath, "r:") as pack:
        for item in meta["shards"]:
            for name in (item["filename"], item["manifest_filename"]):
                member = pack.getmember("payload/" + name)
                if not member.isfile():
                    raise RuntimeError("non_file_in_official_bundle:" + name)
                dest = stage / name
                stream = pack.extractfile(member)
                if stream is None:
                    raise RuntimeError("tar_member_unreadable:" + name)
                with stream, dest.open("xb") as out:
                    shutil.copyfileobj(stream, out, 8*1024*1024)
            raw = stage / item["filename"]
            manifest = stage / item["manifest_filename"]
            if raw.stat().st_size != item["file_size_bytes"] or sha(raw) != item["sha256"]:
                raise RuntimeError("official_source_shard_identity_mismatch:" + raw.name)
            m = json.loads(manifest.read_text())
            actual = m.get("manifest_hash")
            check = dict(m)
            check.pop("manifest_hash", None)
            if actual != stable(check) or actual != item["manifest_hash"]:
                raise RuntimeError("source_shard_manifest_mismatch:" + raw.name)
            verified.append(raw)
    tarpath.unlink()
    return stage, verified


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args()
    if not 1 <= a.workers <= 12:
        raise ValueError("workers_not_in_1_to_12")
    C_ROOT.mkdir(parents=True, exist_ok=True)
    D_ROOT.mkdir(parents=True, exist_ok=True)
    metas = [(s, meta_for(s)) for s in STEMS]
    max_raw = max(int(m["raw_shard_bytes"]) for _, m in metas)
    # Keep bounded active raw tar + extracted SQLite + growing catalog (<5GiB).
    require_space(2*max_raw + 5*1024**3)
    if a.validate_only:
        print("PRECHECK_PASS=H1_2023_SOURCE_CATALOG_ONLY;NO_ANNUAL_PERMISSION", flush=True)
        return 0
    sys.path.insert(0, str(G8_CODE))
    import group8_pa7_catalog as builder
    chunker = recovery_module()
    if CATALOG.exists():
        with sqlite3.connect(CATALOG) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("partial_catalog_integrity_failed")
    else:
        builder.init_catalog(CATALOG)
    for stem, meta in metas:
        require_space(2*int(meta["raw_shard_bytes"]) + 5*1024**3)
        archive = acquire_bundle(stem, meta, a.workers, chunker)
        with sqlite3.connect(CATALOG) as db:
            done = {str(r[0]): (str(r[1]),int(r[2])) for r in db.execute(
                "SELECT filename,file_sha256,file_size_bytes FROM pa7_catalog_source_shard"
            )}
        if all(s["filename"] in done and done[s["filename"]] ==
               (s["sha256"],int(s["file_size_bytes"])) for s in meta["shards"]):
            print("CATALOG_BUNDLE_ALREADY_COMMITTED=" + stem, flush=True)
            continue
        stage, paths = extract_verified(stem, meta, archive)
        try:
            missing = []
            for p in paths:
                row = next(x for x in meta["shards"] if x["filename"]==p.name)
                if p.name in done:
                    if done[p.name] != (row["sha256"],int(row["file_size_bytes"])):
                        raise RuntimeError("previous_catalog_source_drift")
                else:
                    missing.append(p)
            if missing:
                builder.append_shards(CATALOG, missing)
            with sqlite3.connect(CATALOG) as db:
                for row in meta["shards"]:
                    got = db.execute(
                        "SELECT file_sha256,file_size_bytes FROM pa7_catalog_source_shard WHERE filename=?",
                        (row["filename"],)
                    ).fetchone()
                    if got != (row["sha256"],int(row["file_size_bytes"])):
                        raise RuntimeError("post_append_source_coverage_gap:" + stem)
            print(f"CATALOG_BUNDLE_COMMITTED={stem} shards={len(paths)}", flush=True)
        finally:
            shutil.rmtree(stage)
    report = builder.finalize_catalog(CATALOG)
    expected_rows = sum(int(x["candidate_rows"]) for _, x in metas)
    if (report["status"]!="PASS" or report["source_shard_count"]!=36 or
        report["candidate_rows"]!=expected_rows):
        raise RuntimeError("H1_catalog_annual_source_coverage_did_not_match_3_official_bundles")
    checksum = sha(CATALOG)
    archived = D_ROOT / "H1_2023_v2_pa7_candidate_catalog.sqlite"
    atomic_copy(CATALOG, archived, CATALOG.stat().st_size, checksum)
    record = {
        "format_version":1,"status":"PASS_FROZEN_H1_PA7_SOURCE_CATALOG_ONLY",
        "source_tag":TAG,"source_bundles":list(STEMS),
        "source_shards_verified":36,"candidate_rows":expected_rows,
        "source_report_hashes":{s:m["report_hash"] for s,m in metas},
        "catalog_sha256":checksum, "catalog_bytes":archived.stat().st_size,
        "catalog_path":str(archived),
        "frozen_group8_modified":False, "source_is_2023_only":True,
        "group9_wyckoff_derived_evidence_verified":False,
        "group9_annual_execution_authorized":False,
    }
    record["report_hash"]=stable(record)
    final=D_ROOT/"verified_H1_source_catalog_receipt.json"
    if final.exists():
        prior=json.loads(final.read_text())
        if prior != record:raise RuntimeError("existing_H1_receipt_drift")
    else:
        tmp=final.with_suffix(".json.incomplete")
        tmp.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n")
        os.replace(tmp, final)
    if sha(archived)!=checksum:
        raise RuntimeError("post_receipt_catalog_sha_mismatch")
    CATALOG.unlink()
    print(f"H1_SOURCE_CATALOG=PASS shards=36 rows={expected_rows}", flush=True)
    print("OFFICIAL_H1_CATALOG_D="+str(archived),flush=True)
    print("G9_ANNUAL_AUTHORIZED=False",flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
