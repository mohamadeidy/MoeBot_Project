#!/usr/bin/env python3
"""Restore and verify the frozen MoeBot Groups 2-6 runtime bundle v2."""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_SHA256 = "d12deaadb90f7c7a30337246eb144e55399bdad1e4e2e065fb95723c3ae2d436"
EXPECTED_SIZE = 63561
BUNDLE_NAME = "MoeBot_Groups2-6_Frozen_Runtime_Sources_v2.tar.zst"
CHUNK_RE = re.compile(r"part_(\d{3})\.b64")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload(path: Path) -> bytes:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    if not lines:
        raise RuntimeError(f"No Base64 payload in {path}")
    return base64.b64decode("".join(lines), validate=True)


def restore(root: Path, output: Path) -> Path:
    chunks_dir = root / "chunks"
    chunks = sorted(
        path for path in chunks_dir.iterdir()
        if path.is_file() and CHUNK_RE.fullmatch(path.name)
    )
    if not chunks:
        raise RuntimeError(f"No chunks found under {chunks_dir}")

    expected = [f"part_{index:03d}.b64" for index in range(len(chunks))]
    actual = [path.name for path in chunks]
    if actual != expected:
        raise RuntimeError(f"Non-contiguous chunks: expected {expected}, got {actual}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        for chunk in chunks:
            stream.write(payload(chunk))

    size = output.stat().st_size
    digest = sha256_file(output)
    if size != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            "Runtime bundle identity mismatch:\n"
            f" expected size={EXPECTED_SIZE}, sha256={EXPECTED_SHA256}\n"
            f" actual   size={size}, sha256={digest}"
        )
    return output


def extract(bundle: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    tar = shutil.which("tar")
    if tar is None:
        raise RuntimeError("tar is required")
    result = subprocess.run(
        [tar, "--zstd", "-xf", str(bundle), "-C", str(destination)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Extraction failed:\n{result.stdout}\n{result.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    output = (args.output or root / BUNDLE_NAME).resolve()
    bundle = restore(root, output)
    print(f"PASS: restored {bundle}")
    print(f"size={bundle.stat().st_size}")
    print(f"sha256={EXPECTED_SHA256}")
    if args.extract_to:
        extract(bundle, args.extract_to.resolve())
        print(f"PASS: extracted to {args.extract_to.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
