#!/usr/bin/env python3
"""Exclusive stage-4 complete-coverage finalizer and checkpoint-3 publisher."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from group8_context_rejection_fastpath import IndexedContextRejectionEngine, STAGE4_PARTITION_COUNT
from group8_segmented_annual_core import run_segment
from group8_stage4_full_job import command, integrity, parent_restore, sha256_file, staging_restore
from moebot_group8_engine_v0_8_0 import stable_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    status = json.loads((args.artifacts_root / "STATUS.json").read_text())
    if status["annual_execution_2024_authorized"] is not False:
        raise RuntimeError("2024 lock failure")
    plan = IndexedContextRejectionEngine.stage4_partition_plan()
    if plan["partition_count"] != STAGE4_PARTITION_COUNT or STAGE4_PARTITION_COUNT != 24:
        raise RuntimeError("frozen stage-4 partition plan mismatch")

    staging, _ = staging_restore(args.artifacts_root, args.work_dir)
    parent_db, parent_manifest, parent_hash, _ = parent_restore(args.repo, args.tag, 23, args.work_dir)
    if parent_manifest["partition_index"] != 23 or parent_manifest["plan_hash"] != plan["plan_hash"]:
        raise RuntimeError("final parent manifest mismatch")
    core = args.work_dir / "core.sqlite"
    shutil.copy2(parent_db, core)
    result = run_segment(
        staging_db=staging,
        output_db=core,
        artifacts_root=args.artifacts_root,
        year=2023,
        symbol="XAUUSD_",
        start=4,
        end=4,
        stage4_finalize=True,
    )
    if result["checkpoint_3_published"] is not True:
        raise RuntimeError("stage-4 finalization did not publish logical checkpoint")
    aggregate = result["aggregate"]
    if len(aggregate["ordered_receipt_hashes"]) != 24:
        raise RuntimeError("incomplete stage-4 ordered receipt coverage")
    integrity(core)

    prefix = "checkpoint3"
    archive = args.work_dir / f"{prefix}.sqlite.zst"
    command("zstd", "-q", "-3", "-T0", "-f", str(core), "-o", str(archive))
    command("split", "-b", "1750000000", "-d", "-a", "3", str(archive), str(args.work_dir / f"{prefix}.sqlite.zst.part-"))
    parts = [{"filename": part.name, "size_bytes": part.stat().st_size, "sha256": sha256_file(part)} for part in sorted(args.work_dir.glob(f"{prefix}.sqlite.zst.part-*"))]
    manifest = {
        "status": "PASS", "year": 2023, "stage_end": 4,
        "source_checkpoint_report_hash": parent_hash,
        "raw_size_bytes": core.stat().st_size, "raw_sha256": sha256_file(core),
        "compressed_size_bytes": archive.stat().st_size, "compressed_sha256": sha256_file(archive),
        "parts": parts, "segment_report": result,
        "stage4_partition_chain_complete": True,
        "partition_count": 24, "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
        "free_only": True, "paid_runner_used": False, "paid_service_used": False, "oos_2024_accessed": False,
    }
    manifest["report_hash"] = stable_hash(manifest)
    manifest_path = args.work_dir / f"{prefix}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    command("gh", "release", "upload", args.tag, *[str(args.work_dir / item["filename"]) for item in parts], str(manifest_path), "--repo", args.repo, "--clobber")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
