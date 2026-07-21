#!/usr/bin/env python3
"""Restore and verify the frozen MoeBot Groups 2-6 runtime bundle.

The archive is stored as ordered Base64 chunks so it can live in ordinary Git
without changing the exact frozen source bytes. This script joins the chunks,
decodes the Zstandard-compressed tar archive, verifies SHA-256, and optionally
extracts it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_BUNDLE_SHA256 = "174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf"
BUNDLE_NAME = "MoeBot_Groups2-6_Frozen_Runtime_Sources.tar.zst"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def restore(root: Path, output: Path) -> Path:
    chunks_dir = root / "chunks"
    chunks = sorted(chunks_dir.glob("part_*.b64"))
    if not chunks:
        raise FileNotFoundError(f"No chunks found under {chunks_dir}")

    encoded = b"".join(chunk.read_bytes().strip() for chunk in chunks)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid Base64 chunks: {exc}") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(decoded)

    actual = sha256_file(output)
    if actual != EXPECTED_BUNDLE_SHA256:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            "Bundle SHA-256 mismatch:\n"
            f"  expected: {EXPECTED_BUNDLE_SHA256}\n"
            f"  actual:   {actual}"
        )
    return output


def extract(bundle: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    tar = shutil.which("tar")
    if tar is None:
        raise RuntimeError("The 'tar' executable is required for extraction.")

    command = [tar, "--zstd", "-xf", str(bundle), "-C", str(destination)]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Extraction failed. Install tar with Zstandard support or extract "
            f"the verified archive manually.\n{result.stderr}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / BUNDLE_NAME,
        help="Path for the reconstructed tar.zst archive.",
    )
    parser.add_argument(
        "--extract-to",
        type=Path,
        help="Optional directory in which to extract the verified archive.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    bundle = restore(root, args.output.resolve())
    print(f"PASS: restored {bundle}")
    print(f"SHA-256: {EXPECTED_BUNDLE_SHA256}")

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
