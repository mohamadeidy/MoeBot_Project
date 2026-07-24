#!/usr/bin/env python3
"""Restore Group 2-6 frozen runtime bundle v3 and verify every engine identity."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

CANONICAL_ENGINES = {
    "runtime/groups2_5/code/moebot_group2_engine_v0_2_1.py": (35853, "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926"),
    "runtime/groups2_5/code/moebot_group3_structure_engine_v0_1_1.py": (23933, "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512"),
    "runtime/groups2_5/code/moebot_group4_zones_engine_v0_1_6.py": (57168, "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad"),
    "runtime/groups2_5/code/moebot_group5_liquidity_engine_v0_1_6.py": (59657, "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc"),
    "runtime/group6/code/moebot_group6_engine.py": (64524, "1a60e9943e91af656df462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad"),
}
# Correct canonical Group 6 identity (kept explicit to avoid accepting manifest drift).
CANONICAL_ENGINES["runtime/group6/code/moebot_group6_engine.py"] = (64524, "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path)
    ap.add_argument("--extract-to", type=Path)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 3 or manifest.get("status") != "frozen_verified_runtime":
        raise RuntimeError("invalid v3 manifest status/version")

    chunks_dir = root / "chunks"
    rows = manifest["chunks"]
    expected_names = [row["name"] for row in rows]
    actual_names = sorted(p.name for p in chunks_dir.glob("part_*.b64"))
    if actual_names != expected_names:
        raise RuntimeError(f"chunk sequence mismatch: expected={expected_names} actual={actual_names}")

    parts: list[bytes] = []
    for row in rows:
        path = chunks_dir / row["name"]
        payload = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
        if len(payload) != int(row["decoded_size_bytes"]):
            raise RuntimeError(f"decoded chunk size mismatch: {path.name}")
        if sha256_bytes(payload) != row["decoded_sha256"]:
            raise RuntimeError(f"decoded chunk SHA mismatch: {path.name}")
        parts.append(payload)

    bundle = b"".join(parts)
    if len(bundle) != int(manifest["bundle_size_bytes"]):
        raise RuntimeError("bundle size mismatch")
    if sha256_bytes(bundle) != manifest["bundle_sha256"]:
        raise RuntimeError("bundle SHA mismatch")

    output = (args.output or root / manifest["bundle_filename"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bundle)
    print(f"PASS archive size={len(bundle)} sha256={manifest['bundle_sha256']}")

    if args.extract_to:
        destination = args.extract_to.resolve()
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        tar = shutil.which("tar")
        if not tar:
            raise RuntimeError("tar executable is required")
        proc = subprocess.run([tar, "--zstd", "-xf", str(output), "-C", str(destination)], text=True, capture_output=True)
        if proc.returncode:
            raise RuntimeError(f"extraction failed: {proc.stderr}")
        for rel, (expected_size, expected_sha) in CANONICAL_ENGINES.items():
            path = destination / rel
            if not path.is_file():
                raise RuntimeError(f"missing canonical engine: {rel}")
            actual_size = path.stat().st_size
            actual_sha = sha256_file(path)
            if actual_size != expected_size or actual_sha != expected_sha:
                raise RuntimeError(f"engine identity mismatch: {rel} size={actual_size} sha256={actual_sha}")
            print(f"PASS {rel} size={actual_size} sha256={actual_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
