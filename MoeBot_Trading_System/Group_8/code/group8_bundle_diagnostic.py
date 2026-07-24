#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()

    manifest_path = a.bundle_root / "BUNDLE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("chunks", [])
    expected_names = [str(row["name"]) for row in rows]
    actual_paths = sorted((a.bundle_root / "chunks").glob("part_*.b64"))
    actual_names = [path.name for path in actual_paths]

    result: dict[str, object] = {
        "bundle_generation": "v3",
        "manifest_format_version": manifest.get("format_version"),
        "manifest_status": manifest.get("status"),
        "expected_sha256": manifest.get("bundle_sha256"),
        "expected_size_bytes": manifest.get("bundle_size_bytes"),
        "chunk_count": len(actual_paths),
        "chunk_sequence_pass": actual_names == expected_names,
        "chunks": [],
    }

    parts: list[bytes] = []
    chunk_pass = actual_names == expected_names and len(rows) == len(actual_paths)
    if chunk_pass:
        for row in rows:
            path = a.bundle_root / "chunks" / row["name"]
            try:
                payload = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
            except Exception as exc:  # noqa: BLE001
                result["chunks"].append({"name": path.name, "decode": "fail", "error": repr(exc)})  # type: ignore[union-attr]
                chunk_pass = False
                continue
            actual_sha = digest(payload)
            ok = len(payload) == int(row["decoded_size_bytes"]) and actual_sha == row["decoded_sha256"]
            result["chunks"].append({  # type: ignore[union-attr]
                "name": path.name,
                "decoded_size_bytes": len(payload),
                "decoded_sha256": actual_sha,
                "pass": ok,
            })
            chunk_pass = chunk_pass and ok
            parts.append(payload)

    bundle = b"".join(parts) if chunk_pass else b""
    archive_pass = bool(
        chunk_pass
        and len(bundle) == int(manifest.get("bundle_size_bytes", -1))
        and digest(bundle) == manifest.get("bundle_sha256")
    )
    result["archive"] = {
        "size_bytes": len(bundle),
        "sha256": digest(bundle) if bundle else None,
        "pass": archive_pass,
    }

    tar_pass = False
    tar_first_lines: list[str] = []
    tar_stderr = ""
    if archive_pass:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "bundle.tar.zst"
            archive.write_bytes(bundle)
            proc = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True, check=False)
            tar_pass = proc.returncode == 0
            tar_first_lines = proc.stdout.splitlines()[:50]
            tar_stderr = proc.stderr[-2000:]
    result["tar"] = {"pass": tar_pass, "first_lines": tar_first_lines, "stderr": tar_stderr}

    result["status"] = "pass" if (
        manifest.get("format_version") == 3
        and manifest.get("status") == "frozen_verified_runtime"
        and chunk_pass
        and archive_pass
        and tar_pass
    ) else "fail"

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
