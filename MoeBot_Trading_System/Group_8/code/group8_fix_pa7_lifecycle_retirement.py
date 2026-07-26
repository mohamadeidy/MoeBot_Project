#!/usr/bin/env python3
"""Apply the minimal PA7 lifecycle-retirement correctness fix for Gap008.

No frozen definition/config/schema/upstream surface is changed. The fix only
makes PA7 boundary eligibility honor already-causal lifecycle termination for:
- Group6 FVG identities at first traversed+invalidated transition_time.
- Group8 bounded-range identities at first invalidating transition/interaction
  of either locked Group4 boundary after the range became available.
Other Group6 boundary classes remain right-censored because their frozen adapter
does not expose a causal retirement timestamp. Group5 behavior remains unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-LIFECYCLE-RETIREMENT-008"
PRE_ENGINE_SHA = "a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"
REGISTRY_HASH = "70d1d4d873249ba73a20ece3d26de90054db171d28af68b4fafc5d9806173ec9"
FREEZE_HASH = "7cc865da6712c343bdaeb7fce4bb9f93ce2ddf117c45367e13b8dc637e29e1b4"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


OLD_CATALOG = '''        for t,idc,avc,lowc,upc,eventc in [("fvg_events","fvg_id","availability_time","lower","upper","creation_time"),("imbalance_variants","variant_id","availability_time","lower","upper","availability_time"),("liquidity_voids","void_id","availability_time","lower","upper","start_time"),("bpr_relations","bpr_id","availability_time","lower","upper","creation_time")]:
            cols={x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")}; event_expr=eventc if eventc in cols else avc
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=?", (tf,)):
                rows.append({"group":"group6","type":t,"id":str(r["id"]),"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"])})
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=?", (tf,)):
            rows.append({"group":"group7","type":"institutional_zones","id":str(r["zone_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?", (symbol,tf)):
            rows.append({"group":"group8","type":"pa_bounded_range_context","id":str(r["candidate_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        return rows
'''

NEW_CATALOG = '''        fvg_terminal={str(r["fvg_id"]):int(r["inactive_at"]) for r in self.input.execute("SELECT fvg_id,MIN(transition_time) inactive_at FROM group6__fvg_state_transitions WHERE lower(event_type)='traversed' AND lower(directional_validity)='invalidated' GROUP BY fvg_id")}
        for t,idc,avc,lowc,upc,eventc in [("fvg_events","fvg_id","availability_time","lower","upper","creation_time"),("imbalance_variants","variant_id","availability_time","lower","upper","availability_time"),("liquidity_voids","void_id","availability_time","lower","upper","start_time"),("bpr_relations","bpr_id","availability_time","lower","upper","creation_time")]:
            cols={x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")}; event_expr=eventc if eventc in cols else avc
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=?", (tf,)):
                inactive=fvg_terminal.get(str(r["id"])) if t=="fvg_events" else None
                rows.append({"group":"group6","type":t,"id":str(r["id"]),"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"]),"inactive_at":inactive})
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=?", (tf,)):
            rows.append({"group":"group7","type":"institutional_zones","id":str(r["zone_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        zone_invalidations: dict[str,list[int]]={}
        for r in self.input.execute("SELECT zone_id,transition_time,to_status FROM group4__zone_transitions ORDER BY zone_id,transition_time,transition_id"):
            if not self._status_active(str(r["to_status"])): zone_invalidations.setdefault(str(r["zone_id"]),[]).append(int(r["transition_time"]))
        for r in self.input.execute("SELECT zone_id,interaction_time,status_after FROM group4__zone_interactions ORDER BY zone_id,interaction_time,interaction_id"):
            if not self._status_active(str(r["status_after"])): zone_invalidations.setdefault(str(r["zone_id"]),[]).append(int(r["interaction_time"]))
        for times in zone_invalidations.values(): times.sort()
        import bisect
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper,features_json FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?", (symbol,tf)):
            start=int(r["availability_time"]); features=json.loads(r["features_json"]); invalidations=[]
            for zid in (features.get("lower_zone_id"),features.get("upper_zone_id")):
                times=zone_invalidations.get(str(zid),[]) if zid is not None else []
                pos=bisect.bisect_right(times,start)
                if pos<len(times): invalidations.append(int(times[pos]))
            inactive=min(invalidations) if invalidations else None
            rows.append({"group":"group8","type":"pa_bounded_range_context","id":str(r["candidate_id"]),"availability":start,"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"]),"inactive_at":inactive})
        return rows
'''

OLD_ACTIVE = '''    def _pa7_boundary_active_at(self, bnd: Mapping[str, Any], availability: int) -> bool:
        if int(bnd["availability"]) > int(availability): return False
        expires=bnd.get("expires_at")
        if expires is not None and int(expires) < int(availability): return False
'''

NEW_ACTIVE = '''    def _pa7_boundary_active_at(self, bnd: Mapping[str, Any], availability: int) -> bool:
        if int(bnd["availability"]) > int(availability): return False
        inactive=bnd.get("inactive_at")
        if inactive is not None and int(availability) >= int(inactive): return False
        expires=bnd.get("expires_at")
        if expires is not None and int(expires) < int(availability): return False
'''


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--group8-root", type=Path, required=True); a = p.parse_args()
    root = a.group8_root.resolve(); engine_path = root / "code/moebot_group8_engine_v0_8_0.py"; status_path = root / "STATUS.json"
    registry = json.loads((root / "01_DEFINITION_REGISTRY.json").read_text()); freeze = json.loads((root / "DESIGN_FREEZE_MANIFEST.json").read_text()); status = json.loads(status_path.read_text())
    if sha256_file(engine_path) != PRE_ENGINE_SHA: raise SystemExit("unexpected pre-fix engine identity")
    if registry.get("registry_hash") != REGISTRY_HASH or freeze.get("design_freeze_hash") != FREEZE_HASH: raise SystemExit("frozen design identity mismatch")
    gap = status.get("blocking_gap", {})
    if gap.get("gap_id") != GAP_ID or gap.get("status") != "OPEN_CORRECTNESS_FIX_REQUIRED" or gap.get("decision_required") is not False or gap.get("design_change_required") is not False: raise SystemExit("Gap008 is not the authoritative open correctness gap")
    if any(status.get(k) for k in ("engine_build_authorized","annual_execution_authorized","annual_execution_2023_authorized","annual_execution_2024_authorized")): raise SystemExit("Gap008 state must remain fail-closed")

    text = engine_path.read_text()
    if text.count(OLD_CATALOG) != 1: raise SystemExit("expected PA7 catalog block not found exactly once")
    if text.count(OLD_ACTIVE) != 1: raise SystemExit("expected PA7 active predicate block not found exactly once")
    text = text.replace(OLD_CATALOG, NEW_CATALOG, 1).replace(OLD_ACTIVE, NEW_ACTIVE, 1)
    engine_path.write_text(text)
    new_sha = sha256_file(engine_path)

    report: dict[str, Any] = {
        "format_version": 1,
        "status": "FIXED_PENDING_TECHNICAL_REFREEZE",
        "gap_id": GAP_ID,
        "classification": "FROZEN_IMPLEMENTATION_SEMANTIC_VIOLATION",
        "pre_fix_engine_sha256": PRE_ENGINE_SHA,
        "fixed_engine_sha256": new_sha,
        "definition_registry_hash": REGISTRY_HASH,
        "design_freeze_hash": FREEZE_HASH,
        "fix": {
            "group6_fvg": "PA7 catalog attaches inactive_at from first traversed+invalidated FVG transition_time",
            "group8_bounded_range": "PA7 catalog derives inactive_at from first causally inactive Group4 transition/interaction of either locked boundary after range availability",
            "active_predicate": "boundary is ineligible when availability >= inactive_at",
            "group5_changed": False,
            "other_group6_changed": False,
        },
        "frozen_surfaces_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "upstream_changed": False,
        "oos_2024_accessed": False,
    }
    report["report_hash"] = stable_hash(report)
    (root / "reports/41_PA7_LIFECYCLE_RETIREMENT_FIX.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    status["blocking_gap"] = {**gap, "status": "FIXED_PENDING_TECHNICAL_REFREEZE", "fix_report_hash": report["report_hash"], "pre_fix_engine_sha256": PRE_ENGINE_SHA, "fixed_engine_sha256": new_sha, "oos_2024_accessed": False}
    status["engine_build"]["status"] = "STALE_PENDING_TECHNICAL_REFREEZE_AFTER_PA7_LIFECYCLE_FIX"
    status["engine_build"]["engine_sha256"] = new_sha
    status["engine_build_authorized"] = False
    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["status"] = "PA7_LIFECYCLE_GAP008_FIXED_PENDING_TECHNICAL_REFREEZE"
    status["officially_closed"] = False
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status":"PASS","gap_id":GAP_ID,"fixed_engine_sha256":new_sha,"2023_authorized":False,"2024_authorized":False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
