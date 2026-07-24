#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from pathlib import Path

TARGETS = {
    "group2": {"filename": "moebot_group2_engine_v0_2_1.py", "sha256": "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926"},
    "group3": {"filename": "moebot_group3_structure_engine_v0_1_1.py", "sha256": "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512"},
    "group4": {"filename": "moebot_group4_zones_engine_v0_1_6.py", "sha256": "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad"},
    "group5": {"filename": "moebot_group5_liquidity_engine_v0_1_6.py", "sha256": "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc"},
    "group6": {"filename": "moebot_group6_engine.py", "sha256": "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877"},
}
EXPECTED_TO_GROUP = {v["sha256"]: k for k, v in TARGETS.items()}


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def git_text(*args: str) -> str:
    return git_bytes(*args).decode("utf-8", errors="surrogateescape")


def execute(materialize_dir: Path | None) -> dict[str, object]:
    objects = git_text("rev-list", "--all", "--objects").splitlines()
    paths_by_obj: dict[str, list[str]] = {}
    for line in objects:
        parts = line.split(" ", 1)
        obj = parts[0]
        path = parts[1] if len(parts) == 2 else ""
        paths_by_obj.setdefault(obj, [])
        if path:
            paths_by_obj[obj].append(path)

    matches: dict[str, list[dict[str, object]]] = {g: [] for g in TARGETS}
    scanned_blobs = 0
    skipped_by_size = 0
    seen: set[str] = set()
    for obj, paths in paths_by_obj.items():
        if obj in seen:
            continue
        seen.add(obj)
        try:
            if git_text("cat-file", "-t", obj).strip() != "blob":
                continue
            size = int(git_text("cat-file", "-s", obj).strip())
            # Frozen runtime engines are tens of KiB. Keep a broad but bounded window.
            if size < 15000 or size > 150000:
                skipped_by_size += 1
                continue
            data = git_bytes("cat-file", "blob", obj)
        except subprocess.CalledProcessError:
            continue
        scanned_blobs += 1
        digest = hashlib.sha256(data).hexdigest()
        group = EXPECTED_TO_GROUP.get(digest)
        if group:
            row = {
                "git_blob_sha": obj,
                "paths": sorted(set(paths)),
                "size_bytes": len(data),
                "sha256": digest,
            }
            matches[group].append(row)
            if materialize_dir:
                materialize_dir.mkdir(parents=True, exist_ok=True)
                dest = materialize_dir / TARGETS[group]["filename"]
                if not dest.exists():
                    dest.write_bytes(data)

    return {
        "format_version": 3,
        "targets": TARGETS,
        "scanned_blobs": scanned_blobs,
        "skipped_by_size": skipped_by_size,
        "matches": matches,
        "all_exact_matches_found": all(matches[g] for g in TARGETS),
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--materialize-dir", type=Path)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = execute(args.materialize_dir)
        rc = 0 if report["all_exact_matches_found"] else 1
    except Exception as exc:  # noqa: BLE001
        report = {
            "format_version": 3,
            "targets": TARGETS,
            "all_exact_matches_found": False,
            "fatal_error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        rc = 2
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
