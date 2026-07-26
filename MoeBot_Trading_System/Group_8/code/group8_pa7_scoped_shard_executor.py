#!/usr/bin/env python3
"""Free-only PA7 shard execution split by physical boundary scope.

`upstream` shards consume only Groups4-7 boundaries and therefore skip the
expensive Group8 bounded-range construction. `group8_range` shards build bounded
ranges and consume only those Group8 boundaries. The union is required to equal
the frozen PA7 logical output. This is physical execution only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from group8_pa7_shard_executor import (
    PA7ShardEngine,
    ShardSpec,
    export_chain_shard,
    stable_hash,
)

SCOPES = {"upstream", "group8_range", "all"}


class ScopedPA7ShardEngine(PA7ShardEngine):
    def __init__(self, *, boundary_scope: str, **kwargs: Any) -> None:
        if boundary_scope not in SCOPES:
            raise ValueError(f"unsupported boundary_scope: {boundary_scope}")
        self.boundary_scope = boundary_scope
        super().__init__(**kwargs)

    def _pa7_boundary_catalog(self, symbol: str, tf: str) -> list[dict[str, Any]]:
        rows = super()._pa7_boundary_catalog(symbol, tf)
        if self.boundary_scope == "upstream":
            return [row for row in rows if row["group"] != "group8"]
        if self.boundary_scope == "group8_range":
            return [row for row in rows if row["group"] == "group8"]
        return rows


def _scope_manifest(manifest: dict[str, Any], boundary_scope: str) -> dict[str, Any]:
    out = dict(manifest)
    out["boundary_scope"] = boundary_scope
    shard_payload = {
        "family": out["family"],
        "year": out["year"],
        "symbol": out["symbol"],
        "timeframe": out["timeframe"],
        "causal_root_window": out["causal_root_window"],
        "partition_root_rule": out["partition_root_rule"],
        "bucket_index": out["bucket_index"],
        "bucket_count": out["bucket_count"],
        "boundary_scope": boundary_scope,
    }
    out["shard_id"] = "g8shard_" + stable_hash(shard_payload)
    out.pop("manifest_hash", None)
    out["manifest_hash"] = stable_hash(out)
    return out


def run_scoped_shard(
    *,
    staging_db: Path,
    work_db: Path,
    output_db: Path,
    artifacts_root: Path,
    spec: ShardSpec,
    boundary_scope: str,
    manifest_path: Path,
) -> dict[str, Any]:
    if boundary_scope not in SCOPES:
        raise ValueError(f"unsupported boundary_scope: {boundary_scope}")
    if spec.year == 2024:
        status = json.loads((artifacts_root / "STATUS.json").read_text())
        if status.get("annual_execution_2024_authorized") is not True:
            raise RuntimeError("2024 OOS is forbidden")
    work_db.unlink(missing_ok=True)
    engine = ScopedPA7ShardEngine(
        staging_db=staging_db,
        output_db=work_db,
        artifacts_root=artifacts_root,
        year=spec.year,
        symbol=spec.symbol,
        spec=spec,
        boundary_scope=boundary_scope,
    )
    try:
        engine.load_bars()
        engine.retain_target_timeframe()
        if boundary_scope in {"group8_range", "all"}:
            engine.process_bounded_ranges()
        engine.process_breakouts()
        engine.process_failed_breakouts_and_retests_fast()
    finally:
        engine.close()
    manifest = export_chain_shard(work_db, output_db, artifacts_root, spec)
    manifest = _scope_manifest(manifest, boundary_scope)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging-db", type=Path, required=True)
    p.add_argument("--work-db", type=Path, required=True)
    p.add_argument("--output-db", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--root-month")
    p.add_argument("--bucket-count", type=int, required=True)
    p.add_argument("--bucket-index", type=int, required=True)
    p.add_argument("--boundary-scope", choices=sorted(SCOPES), required=True)
    p.add_argument("--manifest", type=Path, required=True)
    a = p.parse_args()
    spec = ShardSpec(a.year, a.symbol, a.timeframe, a.root_month, a.bucket_count, a.bucket_index)
    report = run_scoped_shard(
        staging_db=a.staging_db.resolve(),
        work_db=a.work_db.resolve(),
        output_db=a.output_db.resolve(),
        artifacts_root=a.artifacts_root.resolve(),
        spec=spec,
        boundary_scope=a.boundary_scope,
        manifest_path=a.manifest.resolve(),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
