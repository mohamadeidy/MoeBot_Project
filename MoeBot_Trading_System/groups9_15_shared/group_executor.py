#!/usr/bin/env python3
"""Gated resumable Group9-15 shard executor; never a predecessor-intake gate.

Only a separately attested FULL_ANNUAL_SHARDS preflight may launch workers.
The preflight must bind the exact hashed shard plan. No implicit group handoff,
broker action, storage deletion or authorization is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def stable(doc: dict) -> str:
    return hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def load_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(doc: dict, field: str) -> str:
    copy = dict(doc)
    saved = copy.pop(field, None)
    calculated = stable(copy)
    if saved is not None and saved != calculated:
        raise SystemExit(f"{field} mismatch")
    return str(saved or calculated)


def atomic(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def shard_identity(shard: dict) -> str:
    value = shard.get("shard_id") or shard.get("shard_key")
    if not isinstance(value, str) or not value:
        raise SystemExit("shard missing shard_id or shard_key")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group-dir", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--preflight", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--python", default="python")
    a = p.parse_args()
    group = int(a.group_dir.name.split("_")[-1])

    pf = load_doc(a.preflight)
    if (pf.get("status") != "PASS"
        or pf.get("real_execution_authorized") is not True
        or pf.get("purpose") != "FULL_ANNUAL_SHARDS"
        or pf.get("group") != group):
        raise SystemExit("preflight does not authorize real execution")
    pf_hash = digest(pf, "report_hash")
    if "report_hash" not in pf:
        raise SystemExit("preflight missing report_hash")

    plan = load_doc(a.plan)
    plan_hash = digest(plan, "report_hash")
    if pf.get("plan_hash") != plan_hash:
        raise SystemExit("preflight plan_hash mismatch")
    if not isinstance(plan.get("shards"), list) or not plan["shards"]:
        raise SystemExit("empty shard plan")
    ids = [shard_identity(s) for s in plan["shards"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate shard identities")
    if plan.get("group") not in (None, group):
        raise SystemExit("plan group mismatch")

    cmd_path = a.group_dir / "EXECUTION_COMMAND.json"
    if not cmd_path.is_file():
        raise SystemExit("EXECUTION_COMMAND.json missing; semantics executor not frozen")
    cfg = load_doc(cmd_path)
    if cfg.get("status") != "FROZEN":
        raise SystemExit("execution command not frozen")
    entrypoint = a.group_dir / str(cfg.get("entrypoint", ""))
    if (not entrypoint.is_file() or
        not entrypoint.resolve().is_relative_to(a.group_dir.resolve())):
        raise SystemExit("invalid frozen entrypoint path")
    if not isinstance(cfg.get("args_template"), list):
        raise SystemExit("invalid frozen args_template")

    a.work_root.mkdir(parents=True, exist_ok=True)
    cp = a.work_root / "progress.json"
    state = {
        "group": group, "status": "RUNNING", "completed": [], "failed": [],
        "total": len(ids), "plan_hash": plan_hash, "preflight_hash": pf_hash,
        "started_unix": time.time(),
    }
    if cp.is_file():
        old = load_doc(cp)
        completed = old.get("completed", [])
        if (old.get("group") != group or old.get("plan_hash") != plan_hash or
            old.get("preflight_hash") != pf_hash or old.get("total") != len(ids) or
            not isinstance(completed, list) or len(completed) != len(set(completed)) or
            not set(completed).issubset(set(ids))):
            raise SystemExit("checkpoint identity mismatch; refuse unsafe resume")
        state["completed"] = completed
        state["started_unix"] = old.get("started_unix", state["started_unix"])

    done = set(state["completed"])
    for shard in plan["shards"]:
        sid = shard_identity(shard)
        if sid in done:
            continue
        values = {
            "shard_id": sid, "shard_key": sid,
            "bucket_index": shard["bucket_index"],
            "bucket_count": shard["bucket_count"],
            "year": shard.get("year", ""),
            "symbol": shard.get("symbol", ""),
            "timeframe": shard.get("timeframe", ""),
            "root_month": shard.get("root_month", ""),
            "group": group, "work_root": str(a.work_root),
            "plan": str(a.plan),
        }
        args = [a.python, str(entrypoint)]
        args.extend(str(token).format(**values) for token in cfg["args_template"])
        result = subprocess.run(args)
        if result.returncode:
            state["status"] = "FAILED"
            state["failed"].append({"shard_id": sid, "returncode": result.returncode})
            atomic(cp, state)
            return result.returncode
        state["completed"].append(sid)
        atomic(cp, state)

    state["status"] = "SHARDS_COMPLETE"
    state["finished_unix"] = time.time()
    atomic(cp, state)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
