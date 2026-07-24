#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

TARGETS = {
    "moebot_group2_engine_v0_2_1.py": "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926",
    "moebot_group3_structure_engine_v0_1_1.py": "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512",
    "moebot_group4_zones_engine_v0_1_6.py": "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad",
    "moebot_group5_liquidity_engine_v0_1_6.py": "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc",
    "moebot_group6_engine.py": "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877",
}


def git(*args: str, text: bool = False):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=text).stdout


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--materialize-dir", type=Path)
    args = p.parse_args()

    raw = git("rev-list", "--all", "--objects", text=True)
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
            kind = git("cat-file", "-t", obj, text=True).strip()
            if kind != "blob":
                continue
            data = git("cat-file", "blob", obj)
        except subprocess.CalledProcessError:
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
        rows.sort(key=lambda r: (not bool(r["match"]), str(r["path"]), str(r["git_blob_sha"])))
        matches[name] = next((r for r in rows if r["match"]), None)

    if args.materialize_dir:
        args.materialize_dir.mkdir(parents=True, exist_ok=True)
        for name, row in matches.items():
            if row:
                data = git("cat-file", "blob", str(row["git_blob_sha"]))
                (args.materialize_dir / name).write_bytes(data)

    report = {
        "format_version": 1,
        "targets": TARGETS,
        "candidates": candidates,
        "matches": matches,
        "all_exact_matches_found": all(matches.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"all_exact_matches_found": report["all_exact_matches_found"], "match_paths": {k: (v or {}).get("path") for k, v in matches.items()}}, indent=2))
    return 0 if report["all_exact_matches_found"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
