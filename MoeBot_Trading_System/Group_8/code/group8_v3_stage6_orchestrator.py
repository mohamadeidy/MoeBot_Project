#!/usr/bin/env python3
"""Group 8 V3 Stage 6 annual orchestrator.

Consumes only a PASS preflight plan, executes deterministic range_chain shards,
resumes completed shards by verified manifest/file identity, and fail-closes on
storage-budget or commit-identity drift. Stage 7 is intentionally not callable
from this module.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import RangeShardSpec, run_shard, stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git_head(artifacts_root: Path) -> str:
    repo = artifacts_root.resolve().parent.parent
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _verify_self_hash(record: dict[str, Any], field: str) -> None:
    if field not in record:
        raise RuntimeError(f"missing {field}")
    payload = dict(record)
    saved = str(payload.pop(field))
    if stable_hash(payload) != saved:
        raise RuntimeError(f"{field} mismatch")


def _safe_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))


def _paths(output_root: Path, spec: dict[str, Any]) -> tuple[Path, Path, Path]:
    tf = _safe_token(spec["timeframe"])
    month = _safe_token(spec["root_month"])
    b = int(spec["bucket_index"])
    n = int(spec["bucket_count"])
    stem = f"g8_stage6_{spec.get('year', 2023)}_{tf}_{month}_b{b:04d}of{n:04d}"
    return (
        output_root / "shards" / f"{stem}.sqlite",
        output_root / "checkpoints" / f"{stem}.checkpoint.json",
        output_root / "manifests" / f"{stem}.manifest.json",
    )


def _verified_existing(manifest_path: Path, database: Path, spec: dict[str, Any], stage5_sha: str) -> dict[str, Any] | None:
    if not manifest_path.exists() or not database.exists():
        return None
    m = json.loads(manifest_path.read_text())
    _verify_self_hash(m, "manifest_hash")
    checks = {
        "status": "PASS",
        "stage": 6,
        "stage_name": "wyckoff_core",
        "family": "range_chain",
        "timeframe": spec["timeframe"],
        "causal_root_window": spec["root_month"],
        "bucket_count": int(spec["bucket_count"]),
        "bucket_index": int(spec["bucket_index"]),
        "stage5_database_sha256": stage5_sha,
    }
    for key, expected in checks.items():
        if m.get(key) != expected:
            raise RuntimeError(f"existing Stage 6 manifest mismatch {key}: {m.get(key)!r} != {expected!r}")
    if database.stat().st_size != int(m.get("file_size_bytes", -1)):
        raise RuntimeError(f"existing shard size mismatch: {database}")
    if sha256_file(database) != m.get("sha256"):
        raise RuntimeError(f"existing shard SHA-256 mismatch: {database}")
    return m


def run_plan(
    *,
    plan_path: Path,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    output_root: Path,
    progress_path: Path,
    release_path: Path,
    expected_commit: str,
) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text())
    _verify_self_hash(plan, "plan_hash")
    if plan.get("status") != "PASS":
        raise RuntimeError("Stage 6 preflight plan is BLOCKED")
    if int(plan.get("stage", 0)) != 6 or int(plan.get("year", 0)) != 2023:
        raise RuntimeError("unexpected Stage 6 plan identity")
    if plan.get("validated_commit") != expected_commit:
        raise RuntimeError("plan validated_commit mismatch")
    actual_head = _git_head(artifacts_root)
    if actual_head != expected_commit:
        raise RuntimeError(f"server Git HEAD mismatch: {actual_head} != {expected_commit}")

    output_root.mkdir(parents=True, exist_ok=True)
    for sub in ("shards", "checkpoints", "manifests"):
        (output_root / sub).mkdir(parents=True, exist_ok=True)

    stage5_sha = sha256_file(stage5_db)
    specs = list(plan.get("specs", []))
    total = len(specs)
    completed = 0
    total_bytes = 0
    manifests: list[dict[str, Any]] = []
    started = time.monotonic()
    floor_bytes = int(float(plan["safety_floor_gb"]) * (1024 ** 3))
    hard_guard = int(plan["hard_guard_shard_bytes"])
    chunk_pairs = int(plan["chunk_pairs"])

    for i, raw in enumerate(specs):
        spec_dict = dict(raw)
        spec_dict["year"] = int(plan["year"])
        db, checkpoint, manifest_path = _paths(output_root, spec_dict)

        existing = _verified_existing(manifest_path, db, spec_dict, stage5_sha)
        if existing is not None:
            manifest = existing
        else:
            disk = shutil.disk_usage(output_root)
            projected = int(spec_dict.get("projected_bytes", hard_guard))
            reserve = int(projected * 1.05)
            if int(disk.free) - floor_bytes < reserve:
                raise RuntimeError(
                    f"Stage 6 storage gate blocked shard {i+1}/{total}: "
                    f"free={disk.free} floor={floor_bytes} reserve={reserve}"
                )
            spec = RangeShardSpec(
                int(plan["year"]),
                str(plan["symbol"]),
                str(spec_dict["timeframe"]),
                str(spec_dict["root_month"]),
                int(spec_dict["bucket_count"]),
                int(spec_dict["bucket_index"]),
            )
            manifest = run_shard(
                staging_db=staging_db,
                stage5_db=stage5_db,
                output_db=db,
                checkpoint_path=checkpoint,
                manifest_path=manifest_path,
                artifacts_root=artifacts_root,
                spec=spec,
                chunk_pairs=chunk_pairs,
                hard_guard_bytes=hard_guard,
                stage5_sha256=stage5_sha,
            )
            if manifest.get("status") != "PASS":
                raise RuntimeError(f"Stage 6 shard did not complete: {db}")

        manifests.append(
            {
                "shard_id": manifest["shard_id"],
                "database": str(db),
                "manifest": str(manifest_path),
                "sha256": manifest["sha256"],
                "manifest_hash": manifest["manifest_hash"],
                "file_size_bytes": int(manifest["file_size_bytes"]),
                "timeframe": manifest["timeframe"],
                "root_month": manifest["causal_root_window"],
                "bucket_index": int(manifest["bucket_index"]),
                "bucket_count": int(manifest["bucket_count"]),
                "table_row_counts": manifest["table_row_counts"],
                "table_logical_sha256": manifest["table_logical_sha256"],
            }
        )
        completed += 1
        total_bytes += int(manifest["file_size_bytes"])
        elapsed = max(time.monotonic() - started, 1e-9)
        rate = completed / elapsed
        remaining = total - completed
        eta = remaining / rate if rate > 0 else None
        progress = {
            "schema": "moebot-group8-v3-stage6-annual-progress-v1",
            "status": "RUNNING" if completed < total else "PASS",
            "stage": 6,
            "validated_commit": expected_commit,
            "stage5_database_sha256": stage5_sha,
            "completed_shards": completed,
            "total_shards": total,
            "progress_percent": 100.0 if total == 0 else round(100.0 * completed / total, 6),
            "elapsed_seconds": round(elapsed, 3),
            "eta_seconds": None if eta is None else round(eta, 3),
            "completed_output_bytes": total_bytes,
            "safety_floor_gb": float(plan["safety_floor_gb"]),
            "stage7_auto_launch": False,
            "updated_unix": int(time.time()),
        }
        progress["progress_hash"] = stable_hash(progress)
        _atomic_json(progress_path, progress)

    release = {
        "format_version": 1,
        "status": "PASS",
        "stage": 6,
        "stage_name": "wyckoff_core",
        "year": int(plan["year"]),
        "symbol": plan["symbol"],
        "validated_commit": expected_commit,
        "stage5_database_sha256": stage5_sha,
        "preflight_report_hash": plan["preflight_report_hash"],
        "preflight_plan_hash": plan["plan_hash"],
        "storage_contract_preserved": True,
        "design_semantics_preserved": True,
        "groups_1_7_read_only": True,
        "stage5_read_only": True,
        "shard_count": len(manifests),
        "total_output_bytes": total_bytes,
        "shards": manifests,
        "stage7_auto_launch": False,
        "stage7_authorized": False,
    }
    release["release_hash"] = stable_hash(release)
    _atomic_json(release_path, release)
    return release


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--stage5-db", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--progress", type=Path, required=True)
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--expected-commit", required=True)
    a = p.parse_args()
    r = run_plan(
        plan_path=a.plan.resolve(),
        staging_db=a.staging_db.resolve(),
        stage5_db=a.stage5_db.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        output_root=a.output_root.resolve(),
        progress_path=a.progress.resolve(),
        release_path=a.release.resolve(),
        expected_commit=a.expected_commit,
    )
    print(json.dumps(r, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
