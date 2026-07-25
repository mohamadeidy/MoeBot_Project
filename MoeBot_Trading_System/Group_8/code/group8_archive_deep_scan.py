#!/usr/bin/env python3
"""Deep, bounded scan for exact frozen Group 4/5 runtime sources.

The scanner is diagnostic only. It never extracts into the repository and never
claims identity from filenames alone: a hit requires the exact SHA-256.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TARGETS = {
    "group4": {
        "filename": "moebot_group4_zones_engine_v0_1_6.py",
        "sha256": "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad",
    },
    "group5": {
        "filename": "moebot_group5_liquidity_engine_v0_1_6.py",
        "sha256": "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc",
    },
}

_BASE64_RE = re.compile(rb"^[A-Za-z0-9+/=\r\n\t ]+$")


@dataclass(frozen=True)
class Candidate:
    provenance: str
    name: str
    payload: bytes
    depth: int


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def bounded_read(path: Path, max_bytes: int) -> bytes:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file exceeds max bytes: {size} > {max_bytes}")
    return path.read_bytes()


def maybe_base64(payload: bytes) -> bytes | None:
    compact = re.sub(rb"\s+", b"", payload)
    if len(compact) < 16 or len(compact) % 4 or not _BASE64_RE.fullmatch(payload):
        return None
    try:
        decoded = base64.b64decode(compact, validate=True)
    except Exception:
        return None
    return decoded if decoded and decoded != payload else None


def expand(candidate: Candidate, max_bytes: int, max_depth: int) -> Iterable[Candidate]:
    if candidate.depth >= max_depth:
        return []
    payload = candidate.payload
    next_depth = candidate.depth + 1
    out: list[Candidate] = []

    if payload[:2] == b"\x1f\x8b":
        try:
            decoded = gzip.decompress(payload)
            if len(decoded) <= max_bytes:
                out.append(
                    Candidate(
                        candidate.provenance + "::gzip",
                        candidate.name.removesuffix(".gz"),
                        decoded,
                        next_depth,
                    )
                )
        except Exception:
            pass

    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile() or member.size > max_bytes:
                    continue
                handle = tf.extractfile(member)
                if handle is None:
                    continue
                data = handle.read(max_bytes + 1)
                if len(data) <= max_bytes:
                    out.append(
                        Candidate(
                            candidate.provenance + "::tar:" + member.name,
                            Path(member.name).name,
                            data,
                            next_depth,
                        )
                    )
    except Exception:
        pass

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size > max_bytes:
                    continue
                data = zf.read(info)
                if len(data) <= max_bytes:
                    out.append(
                        Candidate(
                            candidate.provenance + "::zip:" + info.filename,
                            Path(info.filename).name,
                            data,
                            next_depth,
                        )
                    )
    except Exception:
        pass

    decoded = maybe_base64(payload)
    if decoded is not None and len(decoded) <= max_bytes:
        out.append(
            Candidate(
                candidate.provenance + "::base64",
                candidate.name.removesuffix(".b64"),
                decoded,
                next_depth,
            )
        )

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        required=True,
        help="File or directory to scan; repeatable",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-depth", type=int, default=4)
    args = parser.parse_args()

    queue: list[Candidate] = []
    skipped: list[dict[str, str]] = []
    for root in args.root:
        root = root.resolve()
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in paths:
            try:
                queue.append(Candidate(str(path), path.name, bounded_read(path, args.max_bytes), 0))
            except Exception as exc:
                skipped.append({"path": str(path), "reason": str(exc)})

    seen: set[tuple[str, str]] = set()
    hits: dict[str, list[dict[str, object]]] = {key: [] for key in TARGETS}
    inspected = 0
    while queue:
        item = queue.pop(0)
        digest = sha256_bytes(item.payload)
        key = (digest, item.provenance)
        if key in seen:
            continue
        seen.add(key)
        inspected += 1
        for group, target in TARGETS.items():
            if item.name == target["filename"] or digest == target["sha256"]:
                hits[group].append(
                    {
                        "provenance": item.provenance,
                        "name": item.name,
                        "size_bytes": len(item.payload),
                        "sha256": digest,
                        "filename_match": item.name == target["filename"],
                        "sha256_match": digest == target["sha256"],
                        "depth": item.depth,
                    }
                )
        queue.extend(expand(item, args.max_bytes, args.max_depth))

    verified = {
        group: any(bool(row["sha256_match"]) for row in rows)
        for group, rows in hits.items()
    }
    report = {
        "format_version": 1,
        "status": "PASS" if all(verified.values()) else "NOT_FOUND",
        "targets": TARGETS,
        "verified": verified,
        "hits": hits,
        "inspected_payloads": inspected,
        "skipped": skipped,
        "policy": "Exact source recovery requires SHA-256 match; filename-only matches are diagnostic and never accepted.",
    }
    report["report_hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "verified": verified,
                "report_hash": report["report_hash"],
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
