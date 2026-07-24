#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from pathlib import Path

TARGETS = {
    "moebot_group2_engine_v0_2_1.py": "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926",
    "moebot_group3_structure_engine_v0_1_1.py": "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512",
    "moebot_group4_zones_engine_v0_1_6.py": "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad",
    "moebot_group5_liquidity_engine_v0_1_6.py": "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc",
    "moebot_group6_engine.py": "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877",
}


def git_text(*args: str) -> str:
    proc = subprocess.run(["git", *args], check=True, capture_output=True)
    return proc.stdout.decode("utf-8", errors="surrogateescape")


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def execute(materialize_dir: Path | None) -> dict[str, object]:
    raw = git_text("rev-list", "--all", "--objects")
    candidates: dict[str, list[dict[str, object]]] = {name: [] for name in TARGETS}
    seen: set[tuple[str, str]] = set()
    for line in raw.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        obj, path = parts
        name = Path(path).name
        if name not in TARGETS or (name, obj) in seen:
            continue
        seen.add((name, obj))
        try:
            if git_text("cat-file", "-t", obj).strip() != "blob":
                continue
            data = git_bytes("cat-file", "blob", obj)
        except subprocess.CalledProcessError as exc:
            candidates[name].append({"git_object": obj, "path": path, "read_error": repr(exc), "match": False})
            continue
        sha = hashlib.sha256(data).hexdigest()
        candidates[name].append({
            "git_blob_sha": obj,
            "path": path,
            "size_bytes": len(data),
            "sha256": sha,
            "expected_sha256": TARGETS[name],
            "match": sha == TARGETS[name],
        })

    matches: dict[str, dict[str, object] | None] = {}
    for name, rows in candidates.items():
        rows.sort(key=lambda r: (not bool(r.get("match")), str(r.get("path", "")), str(r.get("git_blob_sha", ""))))
        matches[name] = next((r for r in rows if r.get("match")), None)

    if materialize_dir:
        materialize_dir.mkdir(parents=True, exist_ok=True)
        for name, row in matches.items():
            if row and row.get("git_blob_sha"):
                data = git_bytes("cat-file", "blob", str(row["git_blob_sha"]))
                (materialize_dir / name).write_bytes(data)

    return {
        "format_version": 2,
        "targets": TARGETS,
        "candidates": candidates,
        "matches": matches,
        "all_exact_matches_found": all(matches.values()),
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
            "format_version": 2,
            "targets": TARGETS,
            "all_exact_matches_found": False,
            "fatal_error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        rc = 2
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
