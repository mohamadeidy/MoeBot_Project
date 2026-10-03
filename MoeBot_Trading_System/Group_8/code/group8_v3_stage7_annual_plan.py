#!/usr/bin/env python3
"""Freeze the Group 8 V3 Stage 7 annual 2023 shard plan.

Consumes only already-PASS Stage 7 evidence (preflight, premium benchmark,
lossless zstd storage gate, school-core benchmark) plus read-only staging/Stage5.
It computes exact school-core cardinality by timeframe/root-month using the
frozen current-engine semantics, freezes deterministic bucket counts, verifies
storage/runtime budgets and Git identity, and NEVER launches Stage 7.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from group8_v3_stage6_range_shard_executor import stable_hash
from moebot_group8_engine_v0_8_0 import sha256_file

SOFT_TARGET = 1_500_000_000
HARD_GUARD = 2_500_000_000


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _verify_hash(record: dict[str, Any], field: str) -> None:
    payload = dict(record)
    saved = str(payload.pop(field))
    if stable_hash(payload) != saved:
        raise RuntimeError(f"{field} mismatch")


def _git_head(artifacts_root: Path) -> str:
    repo = artifacts_root.resolve().parent.parent
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _pow2_for_bytes(n: float) -> int:
    if n <= SOFT_TARGET:
        return 1
    return 1 << math.ceil(math.log2(n / SOFT_TARGET))


def _month_expr(column: str) -> str:
    return f"strftime('%Y-%m',{column},'unixepoch')"


def _school_window_counts(con: sqlite3.Connection, allowed: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {
        "ict_liquidity_sweep_displacement": 0,
        "ict_mss_fvg_delivery": 0,
        "ict_return_to_imbalance": 0,
        "ict_block_delivery_context": 0,
        "ict_draw_on_liquidity_context": 0,
    })

    # ICT1 current frozen semantics.
    sql = f"""
      SELECT l.timeframe,{_month_expr('l.end_time')} AS root_month,COUNT(*)
      FROM group6__group6_evidence e
      JOIN group5__liquidity_events q ON q.event_id=e.source_id
      JOIN group6__displacement_legs l ON l.leg_id=e.subject_id
      JOIN group6__displacement_validation_events v ON v.leg_id=l.leg_id
      WHERE lower(e.source_group) IN ('group5','5')
        AND (
          lower(COALESCE(v.result,'')) IN ('pass','validated','true','1','accepted','valid')
          OR lower(COALESCE(v.validation_type,'')) LIKE '%valid%'
        )
      GROUP BY l.timeframe,root_month
    """
    # _validated_legs is logically one row per leg. Avoid duplicate validation rows.
    sql = f"""
      WITH valid_leg AS (
        SELECT l.leg_id,l.timeframe,l.end_time
        FROM group6__displacement_legs l
        WHERE EXISTS (
          SELECT 1 FROM group6__displacement_validation_events v
          WHERE v.leg_id=l.leg_id AND (
            lower(COALESCE(v.result,'')) IN ('pass','validated','true','1','accepted','valid')
            OR lower(COALESCE(v.validation_type,'')) LIKE '%valid%'
          )
        )
      )
      SELECT vl.timeframe,{_month_expr('vl.end_time')} AS root_month,COUNT(*)
      FROM group6__group6_evidence e
      JOIN group5__liquidity_events q ON q.event_id=e.source_id
      JOIN valid_leg vl ON vl.leg_id=e.subject_id
      WHERE lower(e.source_group) IN ('group5','5')
      GROUP BY vl.timeframe,root_month
    """
    for tf, month, n in con.execute(sql):
        out[f"{tf}:{month}"]["ict_liquidity_sweep_displacement"] = int(n)

    q_allowed = ",".join("?" for _ in allowed)
    sql = f"""
      SELECT f.timeframe,{_month_expr('f.creation_time')} AS root_month,COUNT(*)
      FROM group6__fvg_events f
      JOIN group3__break_events e ON e.event_id=f.associated_group3_event_id
      WHERE f.associated_group3_event_id IS NOT NULL
        AND e.resolved_time IS NOT NULL
        AND e.event_type IN ({q_allowed})
      GROUP BY f.timeframe,root_month
    """
    for tf, month, n in con.execute(sql, tuple(allowed)):
        out[f"{tf}:{month}"]["ict_mss_fvg_delivery"] = int(n)

    sql = f"""
      SELECT f.timeframe,{_month_expr('f.creation_time')} AS root_month,COUNT(*)
      FROM group6__fvg_state_transitions t
      JOIN group6__fvg_events f ON f.fvg_id=t.fvg_id
      WHERE t.transition_time>f.availability_time
        AND (
          lower(t.event_type) LIKE '%touch%' OR lower(t.event_type) LIKE '%visit%'
          OR lower(t.event_type) LIKE '%fill%' OR lower(t.event_type) LIKE '%ce%'
          OR lower(t.event_type) LIKE '%traverse%'
        )
      GROUP BY f.timeframe,root_month
    """
    for tf, month, n in con.execute(sql):
        out[f"{tf}:{month}"]["ict_return_to_imbalance"] = int(n)

    sql = f"""
      SELECT z.timeframe,{_month_expr('z.event_time')} AS root_month,COUNT(*)
      FROM group7__institutional_zones z
      JOIN group7__zone_evidence e ON e.zone_id=z.zone_id
      WHERE lower(e.source_group) IN ('group6','6')
      GROUP BY z.timeframe,root_month
    """
    for tf, month, n in con.execute(sql):
        out[f"{tf}:{month}"]["ict_block_delivery_context"] = int(n)

    sql = f"""
      SELECT d.timeframe,{_month_expr('d.close_time')} AS root_month,COUNT(*)
      FROM group5__draw_states d
      JOIN group5__liquidity_pools p ON p.pool_id=d.selected_pool_id
      WHERE d.selected_pool_id IS NOT NULL
        AND EXISTS (
          SELECT 1 FROM group3__structure_states s
          WHERE s.timeframe=d.timeframe AND s.close_time<=d.close_time
        )
      GROUP BY d.timeframe,root_month
    """
    for tf, month, n in con.execute(sql):
        out[f"{tf}:{month}"]["ict_draw_on_liquidity_context"] = int(n)

    return dict(sorted(out.items()))


def run_plan(
    *,
    staging_db: Path,
    stage5_db: Path,
    artifacts_root: Path,
    preflight_path: Path,
    premium_benchmark_path: Path,
    compression_gate_path: Path,
    school_benchmark_path: Path,
    output_root: Path,
    expected_commit: str,
    safety_floor_gb: float,
    max_runtime_hours: float,
    storage_safety_factor: float,
    runtime_safety_factor: float,
    report_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    if _git_head(artifacts_root) != expected_commit:
        raise RuntimeError("Git HEAD mismatch for Stage 7 plan")

    pf = json.loads(preflight_path.read_text()); _verify_hash(pf, "report_hash")
    pb = json.loads(premium_benchmark_path.read_text()); _verify_hash(pb, "report_hash")
    cg = json.loads(compression_gate_path.read_text()); _verify_hash(cg, "report_hash")
    sb = json.loads(school_benchmark_path.read_text()); _verify_hash(sb, "report_hash")
    for name, rec in (("preflight",pf),("premium_benchmark",pb),("compression_gate",cg),("school_benchmark",sb)):
        if rec.get("status") != "PASS":
            raise RuntimeError(f"{name} is not PASS")
    if cg.get("storage_gate_pass") is not True or cg.get("lossless_roundtrip_verified") is not True:
        raise RuntimeError("compression storage gate is not lossless PASS")
    stage5_sha = sha256_file(stage5_db)
    if stage5_sha != pf["stage5_database_sha256"] or stage5_sha != sb["stage5_database_sha256"]:
        raise RuntimeError("Stage5 SHA drift")
    if pb["stage7_preflight_report_hash"] != pf["report_hash"] or sb["stage7_preflight_report_hash"] != pf["report_hash"]:
        raise RuntimeError("Stage 7 evidence lineage mismatch")
    if cg["stage7_benchmark_report_hash"] != pb["report_hash"]:
        raise RuntimeError("compression gate/premium benchmark lineage mismatch")

    bindings = json.loads((artifacts_root/"UPSTREAM_VALUE_BINDINGS.json").read_text())
    allowed = list(bindings["bindings"]["group3"]["mss_or_bos_event_types"])
    con = sqlite3.connect(f"file:{staging_db.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        school_counts = _school_window_counts(con, allowed)
    finally:
        con.close()

    expected_school_total = sum(
        int(pf["definition_cardinality_current_engine"][k])
        for k in (
            "ict_liquidity_sweep_displacement","ict_mss_fvg_delivery",
            "ict_return_to_imbalance_fvg_ce_current_engine",
            "ict_block_delivery_context","ict_draw_on_liquidity_context",
        )
    )
    exact_school_total = sum(sum(v.values()) for v in school_counts.values())
    if exact_school_total != expected_school_total:
        raise RuntimeError(f"school_core exact cardinality mismatch:{exact_school_total}!={expected_school_total}")

    premium_bpi = float(pb["sample"]["bytes_per_interpretation_with_two_evidence_rows"])
    premium_windows = pf["premium_discount"]["by_root_window"]
    range_shards = []
    for window, interpretations in sorted(premium_windows.items()):
        tf, month = window.split(":",1)
        projected = int(int(interpretations) * premium_bpi * storage_safety_factor)
        buckets = _pow2_for_bytes(projected)
        for b in range(buckets):
            range_shards.append({
                "family":"range_chain","year":2023,"symbol":pf["symbol"],"timeframe":tf,
                "root_month":month,"bucket_count":buckets,"bucket_index":b,
                "window_interpretations":int(interpretations),
                "window_projected_raw_bytes_with_safety":projected,
            })

    school_bpl = float(sb["sample"]["bytes_per_logical_row"])
    school_shards = []
    school_window_projection = {}
    weights = {
        "ict_liquidity_sweep_displacement": 4,
        "ict_mss_fvg_delivery": 3,
        "ict_return_to_imbalance": 3,
        "ict_block_delivery_context": 3,
        "ict_draw_on_liquidity_context": 4,
    }
    for window, defs in sorted(school_counts.items()):
        tf, month = window.split(":",1)
        logical = sum(int(defs[k])*weights[k] for k in weights)
        projected = int(logical * school_bpl * storage_safety_factor)
        buckets = _pow2_for_bytes(projected)
        school_window_projection[window] = {
            "definition_counts": defs,
            "interpretations": sum(defs.values()),
            "logical_rows": logical,
            "projected_raw_bytes_with_safety": projected,
            "bucket_count": buckets,
        }
        for b in range(buckets):
            school_shards.append({
                "family":"school_core","year":2023,"symbol":pf["symbol"],"timeframe":tf,
                "root_month":month,"bucket_count":buckets,"bucket_index":b,
                "window_interpretations":sum(defs.values()),
                "window_logical_rows":logical,
                "window_projected_raw_bytes_with_safety":projected,
            })

    all_shards = range_shards + school_shards
    max_projected = max(
        [math.ceil(int(s.get("window_projected_raw_bytes_with_safety",0))/int(s["bucket_count"])) for s in all_shards],
        default=0,
    )
    if max_projected > HARD_GUARD:
        raise RuntimeError(f"projected shard exceeds hard guard:{max_projected}")

    premium_runtime = float(pb["sample"]["seconds_per_interpretation"]) * int(pb["projection"]["full_premium_discount_interpretations"]) * runtime_safety_factor
    school_runtime = float(sb["sample"]["seconds_per_interpretation"]) * exact_school_total * runtime_safety_factor
    runtime_seconds = premium_runtime + school_runtime

    # Conservative compressed annual size: use measured premium gate + measured school projection,
    # each already based on actual frozen writers; then apply the plan-level storage factor once.
    premium_compressed = int(pb["projection"]["premium_projected_bytes_from_measured_sample"] / float(cg["measured_compression_ratio"]))
    school_compressed = int(sb["projection"]["projected_compressed_bytes"])
    compressed_projection = int((premium_compressed + school_compressed) * storage_safety_factor)
    disk = shutil.disk_usage(output_root)
    floor = int(safety_floor_gb*(1024**3))
    usable = max(int(disk.free)-floor,0)
    peak = compressed_projection + max_projected

    blockers=[]
    if runtime_seconds > max_runtime_hours*3600:
        blockers.append(f"runtime projection {runtime_seconds/3600:.2f}h exceeds {max_runtime_hours:.2f}h")
    if peak > usable:
        blockers.append(f"compressed+one-raw-shard peak {peak} exceeds usable {usable}")
    if int(cg["measured_compression_ratio"]*1000) < int(float(cg["required_compression_ratio_for_peak_gate"])*1000):
        blockers.append("measured compression ratio below required gate")
    status="PASS" if not blockers else "BLOCKED"

    plan = {
        "format_version":1,
        "scope":"GROUP8_V3_STAGE7_2023_ANNUAL_PLAN",
        "status":status,
        "year":2023,
        "symbol":pf["symbol"],
        "validated_commit":expected_commit,
        "stage5_database_sha256":stage5_sha,
        "stage6_release_hash":pf["stage6_release_hash"],
        "stage6_union_report_hash":pf["stage6_union_report_hash"],
        "stage7_preflight_report_hash":pf["report_hash"],
        "premium_benchmark_report_hash":pb["report_hash"],
        "compression_gate_report_hash":cg["report_hash"],
        "school_core_benchmark_report_hash":sb["report_hash"],
        "storage_contract_hash":json.loads((artifacts_root/"SHARDED_STORAGE_CONTRACT.json").read_text())["storage_contract_hash"],
        "design_freeze_hash":json.loads((artifacts_root/"DESIGN_FREEZE_MANIFEST.json").read_text())["design_freeze_hash"],
        "shard_count":len(all_shards),
        "range_chain_shard_count":len(range_shards),
        "school_core_shard_count":len(school_shards),
        "shards":all_shards,
        "school_core_exact_by_window":school_window_projection,
        "expected_cardinality":{
            "premium_discount_interpretations":int(pb["projection"]["full_premium_discount_interpretations"]),
            "school_core_interpretations":exact_school_total,
            "total_stage7_interpretations":int(pb["projection"]["full_premium_discount_interpretations"])+exact_school_total,
        },
        "projection":{
            "premium_runtime_seconds_with_plan_safety":premium_runtime,
            "school_runtime_seconds_with_plan_safety":school_runtime,
            "total_runtime_seconds_with_plan_safety":runtime_seconds,
            "max_runtime_hours":max_runtime_hours,
            "premium_compressed_bytes_measured_ratio":premium_compressed,
            "school_core_compressed_bytes_measured":school_compressed,
            "compressed_annual_bytes_with_plan_safety":compressed_projection,
            "projected_max_raw_shard_bytes_with_safety":max_projected,
            "projected_peak_compressed_plus_one_raw_shard":peak,
            "drive_free_bytes":int(disk.free),
            "safety_floor_bytes":floor,
            "usable_new_output_bytes":usable,
            "storage_safety_factor":storage_safety_factor,
            "runtime_safety_factor":runtime_safety_factor,
        },
        "execution_policy":{
            "one_raw_shard_at_a_time":True,
            "validate_before_compress":True,
            "zstd_level":6,
            "zstd_test_required":True,
            "streamed_roundtrip_sha256_required":True,
            "delete_raw_only_after_roundtrip_sha_match":True,
            "resume_from_verified_manifest_or_checkpoint":True,
            "stage5_read_only":True,
            "groups_1_7_read_only":True,
            "oos_2024_forbidden":True,
            "stage7_auto_launch":False,
        },
        "blockers":blockers,
    }
    plan["plan_hash"]=stable_hash(plan)
    _atomic_json(plan_path,plan)

    report={
        "format_version":1,"scope":"GROUP8_V3_STAGE7_2023_PLAN_GATE","status":status,
        "plan_hash":plan["plan_hash"],"validated_commit":expected_commit,
        "stage7_authorized":False,"stage7_auto_launch":False,
        "full_annual_stage7_permitted_by_plan_gate":status=="PASS",
        "range_chain_shard_count":len(range_shards),"school_core_shard_count":len(school_shards),
        "total_shard_count":len(all_shards),"exact_school_core_interpretations":exact_school_total,
        "expected_total_stage7_interpretations":plan["expected_cardinality"]["total_stage7_interpretations"],
        "projected_total_runtime_hours_with_safety":runtime_seconds/3600,
        "projected_compressed_annual_gb_with_safety":compressed_projection/1e9,
        "projected_peak_gb":peak/1e9,"usable_new_output_gb":usable/1e9,
        "projected_max_raw_shard_gb":max_projected/1e9,
        "blockers":blockers,
        "next_gate":"build/validate annual orchestrator and union validator; do not launch automatically",
    }
    report["report_hash"]=stable_hash(report)
    _atomic_json(report_path,report)
    return report


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--staging-db",type=Path,required=True);p.add_argument("--stage5-db",type=Path,required=True)
    p.add_argument("--artifacts-root",type=Path,required=True);p.add_argument("--preflight",type=Path,required=True)
    p.add_argument("--premium-benchmark",type=Path,required=True);p.add_argument("--compression-gate",type=Path,required=True)
    p.add_argument("--school-benchmark",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True)
    p.add_argument("--expected-commit",required=True);p.add_argument("--safety-floor-gb",type=float,default=120.0)
    p.add_argument("--max-runtime-hours",type=float,default=48.0);p.add_argument("--storage-safety-factor",type=float,default=1.5)
    p.add_argument("--runtime-safety-factor",type=float,default=1.5);p.add_argument("--report",type=Path,required=True)
    p.add_argument("--plan",type=Path,required=True)
    a=p.parse_args()
    r=run_plan(staging_db=a.staging_db.resolve(),stage5_db=a.stage5_db.resolve(),artifacts_root=a.artifacts_root.resolve(),preflight_path=a.preflight.resolve(),premium_benchmark_path=a.premium_benchmark.resolve(),compression_gate_path=a.compression_gate.resolve(),school_benchmark_path=a.school_benchmark.resolve(),output_root=a.output_root.resolve(),expected_commit=a.expected_commit,safety_floor_gb=a.safety_floor_gb,max_runtime_hours=a.max_runtime_hours,storage_safety_factor=a.storage_safety_factor,runtime_safety_factor=a.runtime_safety_factor,report_path=a.report.resolve(),plan_path=a.plan.resolve())
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
