#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

EXPECTED = "174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    chunks = sorted((a.bundle_root / "chunks").glob("part_*.b64"))
    result: dict[str, object] = {
        "expected_sha256": EXPECTED,
        "chunks": [{"name": x.name, "size_bytes": x.stat().st_size, "sha256": hashlib.sha256(x.read_bytes()).hexdigest()} for x in chunks],
    }
    payloads = [x.read_bytes().strip() for x in chunks]
    variants: dict[str, object] = {}
    decoded_candidates: list[tuple[str, bytes]] = []
    try:
        data = base64.b64decode(b"".join(payloads), validate=True)
        variants["joined"] = {"decode": "pass", "size_bytes": len(data), "sha256": digest(data)}
        decoded_candidates.append(("joined", data))
    except Exception as exc:
        variants["joined"] = {"decode": "fail", "error": repr(exc)}
    try:
        data = b"".join(base64.b64decode(x, validate=True) for x in payloads)
        variants["independent"] = {"decode": "pass", "size_bytes": len(data), "sha256": digest(data)}
        decoded_candidates.append(("independent", data))
    except Exception as exc:
        variants["independent"] = {"decode": "fail", "error": repr(exc)}
    for name, data in decoded_candidates:
        if digest(data) == EXPECTED:
            with tempfile.TemporaryDirectory() as td:
                archive = Path(td) / "bundle.tar.zst"
                archive.write_bytes(data)
                proc = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
                variants[name]["tar_list_returncode"] = proc.returncode  # type: ignore[index]
                variants[name]["tar_list_first_lines"] = proc.stdout.splitlines()[:30]  # type: ignore[index]
                variants[name]["tar_list_stderr"] = proc.stderr[-2000:]  # type: ignore[index]
    result["variants"] = variants
    result["matching_variants"] = [name for name, data in decoded_candidates if digest(data) == EXPECTED]
    result["status"] = "pass" if result["matching_variants"] else "fail"
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
