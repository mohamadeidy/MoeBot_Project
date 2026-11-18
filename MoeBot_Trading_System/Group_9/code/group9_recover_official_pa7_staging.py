#!/usr/bin/env python3
"""Verified, resumable *download only* of frozen Group8 PA7 staging release.

This utility never starts MT5, Group8 execution, Group9 annual execution or
changes Git-tracked source. Each HTTP 206 chunk validates Content-Range, bytes,
and a per-part SHA-256. The assembled archive is exposed only if its total
SHA-256 equals the official Group8 release value.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ASSET = "MoeBot_Group8_PA7_2023_COMPACT_STAGING_v1.sqlite.zst"
RELEASE = Path(r"C:\MoeBotActive\group9-preparation\MoeBot_Trading_System\Group_8\reports\47_PA7_2023_COMPACT_STAGING_RELEASE.json")
DEST_ROOT = Path(r"D:\MoeBotData\group9_scratch\upstream_pa7")
CHUNK_SIZE = 2 * 1024 * 1024


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def expected():
    j = json.loads(RELEASE.read_text(encoding="utf-8"))
    if j.get("status") != "PASS" or j.get("filename") != ASSET or j.get("year") != 2023:
        raise RuntimeError("official_group8_release_mismatch")
    return j["release_url"], int(j["compressed_size_bytes"]), str(j["compressed_sha256"])


def fetch(url: str, i: int, total: int) -> int:
    start = i * CHUNK_SIZE
    end = min(total - 1, start + CHUNK_SIZE - 1)
    n = end - start + 1
    segments = DEST_ROOT / "segments"
    part = segments / (f"{i:04d}.part")
    receipt = segments / (f"{i:04d}.sha256")
    if part.exists() and receipt.exists() and part.stat().st_size == n:
        if receipt.read_text().strip() == sha(part):
            return n
    temp = segments / (f"{i:04d}.download")
    headers = segments / (f"{i:04d}.headers")
    for attempt in range(3):
        try:
            if temp.exists():
                temp.unlink()
            cmd = [
                "curl.exe", "-sS", "-f", "-L", "--connect-timeout", "15",
                "--max-time", "150", "--retry", "0", "-r", f"{start}-{end}",
                "-D", str(headers), "-o", str(temp), url,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=160)
            if r.returncode:
                raise RuntimeError(f"curl={r.returncode}:{r.stderr[-160:]}")
            h = headers.read_text(errors="replace")
            response_lines = [
                x.strip() for x in h.splitlines() if x.strip().startswith("HTTP/")
            ]
            if not response_lines or not re.search(r"\s206\s", response_lines[-1]):
                raise RuntimeError("http_not_206")
            range_headers = re.findall(r"(?im)^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", h)
            if not range_headers or tuple(map(int, range_headers[-1])) != (start, end, total):
                raise RuntimeError("content_range_mismatch")
            if temp.stat().st_size != n:
                raise RuntimeError("range_size_mismatch")
            checksum = sha(temp)
            os.replace(temp, part)
            receipt.write_text(checksum + "\n", encoding="ascii")
            return n
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError("range_failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-chunks", type=int, default=0,
                        help="0 means entire official asset; positive means bounded probe only")
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        raise ValueError("workers_must_be_1_to_12")
    url, total, expected_hash = expected()
    dest = DEST_ROOT / ASSET
    segments = DEST_ROOT / "segments"
    segments.mkdir(parents=True, exist_ok=True)
    chunk_count = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    if dest.exists():
        if dest.stat().st_size == total and sha(dest) == expected_hash:
            print("PA7_OFFICIAL_ASSET=ALREADY_VERIFIED", flush=True)
            return 0
        raise RuntimeError("untrusted_final_asset_path_exists")
    limit = min(chunk_count, args.max_chunks) if args.max_chunks > 0 else chunk_count
    started = time.perf_counter()
    print(f"PA7_DOWNLOAD_START total_bytes={total} chunks={chunk_count} scheduled={limit} workers={args.workers}", flush=True)
    complete = 0
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch, url, i, total): i for i in range(limit)}
        for job in concurrent.futures.as_completed(jobs):
            idx = jobs[job]
            try:
                job.result()
                complete += 1
            except Exception as exc:
                errors.append((idx, str(exc)))
            if complete % 8 == 0 or errors:
                print(f"PA7_PROGRESS completed={complete}/{limit} errors={len(errors)} elapsed={time.perf_counter()-started:.1f}s", flush=True)
    if errors:
        print("PA7_CHUNK_ERRORS=" + repr(errors[:10]), flush=True)
        return 2
    if limit < chunk_count:
        print(f"PA7_BOUNDED_PROBE_PASS={complete} chunks", flush=True)
        return 0
    assembling = DEST_ROOT / (ASSET + ".assembling")
    if assembling.exists():
        raise RuntimeError("unverified_assembly_exists")
    h = hashlib.sha256()
    total_written = 0
    with assembling.open("wb") as out:
        for i in range(chunk_count):
            part = segments / f"{i:04d}.part"
            with part.open("rb") as stream:
                while block := stream.read(8 * 1024 * 1024):
                    out.write(block)
                    h.update(block)
                    total_written += len(block)
    if total_written != total or h.hexdigest() != expected_hash:
        raise RuntimeError("OFFICIAL_ARCHIVE_SHA256_OR_SIZE_MISMATCH")
    os.replace(assembling, dest)
    print(f"PA7_OFFICIAL_ASSET=VERIFIED_COMPLETE bytes={total_written} sha256={h.hexdigest()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
