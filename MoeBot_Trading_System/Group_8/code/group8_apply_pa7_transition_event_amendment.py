#!/usr/bin/env python3
"""Apply the approved PA7 transition-event design amendment for Gap 007.

This is a formal design amendment, not a performance-only optimization.
It changes only PA7 enumeration semantics from persistent-state records to
causal NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY transitions while preserving
Exact / ATR-buffer / Point-buffer as independent variants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GAP_ID = "G8-PA7-ENUMERATION-EXPLOSION-007"
PREVIOUS_ENGINE_SHA256 = "f77252cc07c5d4e2fe6481a811441674983ec4d00c36c0c07f618950a4f4877d"
PREVIOUS_REGISTRY_HASH = "fbb23ca75836e7bf29949d2c30b8940fb1f4b5c8115314665e2a862841111579"
PREVIOUS_FREEZE_HASH = "b8847f6e5d9f24893ae0cd2dfc7a9f44ec05ed76fa05abd804197c470ce00672"
WORKLOAD_REPORT_HASH = "6308c8b0e614fd81bc73f64fbc86f037cdd9ff5dc28696bfe3111997db031dbc"
BLOCKER_REPORT_HASH = "b8a3cd3209d949783ffee172f4ab4c7c56a7258fbeeb426343f0cdbab5951940"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def self_hash(record: dict[str, Any], field: str) -> str:
    payload = dict(record)
    payload.pop(field, None)
    return stable_hash(payload)


def write_hashed(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rec = dict(payload)
    rec["report_hash"] = stable_hash(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


NEW_BREAKOUT_BLOCK = r'''    def _pa7_boundary_catalog(self, symbol: str, tf: str) -> list[dict[str, Any]]:
        """Load each PA7 boundary identity once; eligibility is checked causally later."""
        rows: list[dict[str, Any]] = []
        for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=?", (symbol, tf)):
            rows.append({"group":"group4","type":"zones","id":str(r["zone_id"]),"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(r["lower"]),"upper":float(r["upper"]),"expires_at":int(r["expires_at"]) if r["expires_at"] is not None else None,"base_status":str(r["status"] or "active")})
        for r in self.input.execute("SELECT * FROM group5__liquidity_pools WHERE symbol=? AND timeframe=?", (symbol, tf)):
            vals=[("anchor",r["anchor_price"]),("lower",r["lower"]),("upper",r["upper"])]; seen=set()
            for label,val in vals:
                if val is None or float(val) in seen: continue
                seen.add(float(val)); rows.append({"group":"group5","type":"liquidity_pools","id":f"{r['pool_id']}:{label}","source_id":str(r["pool_id"]),"availability":int(r["available_at"]),"event":int(r["origin_time"]),"lower":float(val),"upper":float(val),"expires_at":int(r["expires_at"]) if r["expires_at"] is not None else None})
        for t,idc,avc,lowc,upc,eventc in [("fvg_events","fvg_id","availability_time","lower","upper","creation_time"),("imbalance_variants","variant_id","availability_time","lower","upper","availability_time"),("liquidity_voids","void_id","availability_time","lower","upper","start_time"),("bpr_relations","bpr_id","availability_time","lower","upper","creation_time")]:
            cols={x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")}; event_expr=eventc if eventc in cols else avc
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=?", (tf,)):
                rows.append({"group":"group6","type":t,"id":str(r["id"]),"availability":int(r["av"]),"event":int(r["ev"]),"lower":float(r["lo"]),"upper":float(r["hi"])})
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=?", (tf,)):
            rows.append({"group":"group7","type":"institutional_zones","id":str(r["zone_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?", (symbol,tf)):
            rows.append({"group":"group8","type":"pa_bounded_range_context","id":str(r["candidate_id"]),"availability":int(r["availability_time"]),"event":int(r["event_time"]),"lower":float(r["lower"]),"upper":float(r["upper"])})
        return rows

    def _pa7_boundary_active_at(self, bnd: Mapping[str, Any], availability: int) -> bool:
        if int(bnd["availability"]) > int(availability): return False
        expires=bnd.get("expires_at")
        if expires is not None and int(expires) < int(availability): return False
        if bnd["group"]=="group4":
            return self._status_active(self._active_zone_status_at(str(bnd["id"]),str(bnd.get("base_status","active")),int(availability)))
        if bnd["group"]=="group7":
            tr=self.input.execute("SELECT status FROM group7__zone_state_transitions WHERE zone_id=? AND transition_time<=? ORDER BY transition_time DESC,transition_ordinal DESC LIMIT 1", (bnd["id"],int(availability))).fetchone()
            return not tr or self._status_active(str(tr[0]))
        return True

    def _pa7_beyond(self, definition_id: str, direction: str, bar: Bar, bnd: Mapping[str, Any], *, increment: float | None, atr_fraction: float) -> bool | None:
        level=float(bnd["upper"] if direction=="bullish" else bnd["lower"])
        if definition_id=="pa_breakout_exact":
            return bar.close>level if direction=="bullish" else bar.close<level
        if definition_id=="pa_breakout_point_buffer":
            if increment is None: return None
            return bar.close>=level+increment if direction=="bullish" else bar.close<=level-increment
        if definition_id=="pa_breakout_atr_buffer":
            atr=self.atr_by_bar.get(bar.id)
            if atr in (None,0): return None
            buffer=atr_fraction*float(atr)
            return bar.close>=level+buffer if direction=="bullish" else bar.close<=level-buffer
        raise Group8InvariantError(f"unknown PA7 variant {definition_id}")

    def _pa7_state_boundary_identity(self, bnd: Mapping[str, Any], direction: str) -> str:
        side="upper" if direction=="bullish" else "lower"
        return f"{bnd['group']}:{bnd['type']}:{bnd['id']}:{side}"

    def _pa7_emit_transition(self, definition_id: str, direction: str, bar: Bar, bnd: Mapping[str, Any], *, increment: float | None, atr_fraction: float, previous_bar_id: int | None, initialization_transition: bool) -> None:
        side="upper" if direction=="bullish" else "lower"; level=float(bnd["upper"] if direction=="bullish" else bnd["lower"])
        state_boundary_identity=self._pa7_state_boundary_identity(bnd,direction)
        state_payload={"symbol":bar.symbol,"timeframe":bar.timeframe,"direction":direction,"boundary_identity":state_boundary_identity,"variant":definition_id}
        state_key=deterministic_id("g8pa7state",state_payload)
        features={"boundary_identity":bnd["id"],"state_boundary_identity":state_boundary_identity,"boundary_side":side,"locked_level":level,"pa7_variant":definition_id,"state_key":state_key,"transition_from":"NOT_BEYOND_BOUNDARY","transition_to":"BEYOND_BOUNDARY","previous_eligible_bar_id":previous_bar_id,"initialization_transition":bool(initialization_transition)}
        if definition_id=="pa_breakout_point_buffer": features["verified_increment"]=increment
        elif definition_id=="pa_breakout_atr_buffer":
            atr=self.atr_by_bar.get(bar.id); features["atr14"]=atr; features["buffer"]=atr_fraction*float(atr) if atr not in (None,0) else None
        avail=max_time(bar.available_at,bnd["availability"])
        refs=[self._ref("source","bars",bar.id,bar.available_at,event_time=bar.close_time,timeframe=bar.timeframe),self._ref(bnd["group"],bnd["type"],bnd.get("source_id",bnd["id"]),bnd["availability"],event_time=bnd["event"],timeframe=bar.timeframe,details={"boundary_identity":bnd["id"],"state_boundary_identity":state_boundary_identity,"lower":bnd["lower"],"upper":bnd["upper"]})]
        self._write_pattern(definition_id,symbol=bar.symbol,timeframe=bar.timeframe,direction=direction,source_bar_id=bar.id,event_time=bar.close_time,confirmation_time=bar.close_time,availability_time=avail,lower=level,upper=level,features=features,upstream_refs=refs)

    @staticmethod
    def _pa7_window(levels: Sequence[float], *, definition_id: str, direction: str, previous_bar: Bar, bar: Bar, previous_atr: float | None, current_atr: float | None, increment: float | None, atr_fraction: float) -> tuple[int,int] | None:
        import bisect
        if definition_id=="pa_breakout_exact":
            if direction=="bullish":
                if bar.close<=previous_bar.close: return None
                return bisect.bisect_left(levels,previous_bar.close),bisect.bisect_left(levels,bar.close)
            if bar.close>=previous_bar.close: return None
            return bisect.bisect_right(levels,bar.close),bisect.bisect_right(levels,previous_bar.close)
        if definition_id=="pa_breakout_point_buffer":
            if increment is None: return None
            prev_adj=previous_bar.close-increment if direction=="bullish" else previous_bar.close+increment
            cur_adj=bar.close-increment if direction=="bullish" else bar.close+increment
        elif definition_id=="pa_breakout_atr_buffer":
            if previous_atr in (None,0) or current_atr in (None,0): return None
            prev_buf=atr_fraction*float(previous_atr); cur_buf=atr_fraction*float(current_atr)
            prev_adj=previous_bar.close-prev_buf if direction=="bullish" else previous_bar.close+prev_buf
            cur_adj=bar.close-cur_buf if direction=="bullish" else bar.close+cur_buf
        else:
            raise Group8InvariantError(f"unknown PA7 variant {definition_id}")
        if direction=="bullish":
            if cur_adj<=prev_adj: return None
            return bisect.bisect_right(levels,prev_adj),bisect.bisect_right(levels,cur_adj)
        if cur_adj>=prev_adj: return None
        return bisect.bisect_left(levels,cur_adj),bisect.bisect_left(levels,prev_adj)

    def process_breakouts(self) -> None:
        """Emit only causal PA7 NOT_BEYOND -> BEYOND transition events.

        The level-indexed sweep is semantically required by PA7E/A/P.2 and avoids
        persistent-state bar×boundary materialization. Re-arm is causal: after a
        prior eligible bar is NOT_BEYOND, a later qualifying close may transition
        again. Newly available boundaries initialize in NOT_BEYOND and may
        transition on their first causally eligible confirmed close.
        """
        import bisect
        atr_fraction=float(self.config["pattern_thresholds"]["atr_buffer_breakout_fraction"])
        variants=("pa_breakout_exact","pa_breakout_point_buffer","pa_breakout_atr_buffer")
        for (symbol,tf),bars in sorted(self.bars_by_tf.items()):
            increment=self.point_increment.get(symbol); catalog=self._pa7_boundary_catalog(symbol,tf)
            by_avail=sorted(catalog,key=lambda b:(int(b["availability"]),b["group"],b["type"],b["id"]))
            avail_keys=[int(b["availability"]) for b in by_avail]
            upper=sorted(catalog,key=lambda b:(float(b["upper"]),b["group"],b["type"],b["id"])); upper_levels=[float(b["upper"]) for b in upper]
            lower=sorted(catalog,key=lambda b:(float(b["lower"]),b["group"],b["type"],b["id"])); lower_levels=[float(b["lower"]) for b in lower]
            for idx,bar in enumerate(bars):
                prev=bars[idx-1] if idx else None; current_atr=self.atr_by_bar.get(bar.id); previous_atr=self.atr_by_bar.get(prev.id) if prev else None
                for definition_id in variants:
                    if definition_id=="pa_breakout_point_buffer" and increment is None: continue
                    current_evaluable=definition_id!="pa_breakout_atr_buffer" or current_atr not in (None,0)
                    if not current_evaluable: continue
                    previous_evaluable=prev is not None and (definition_id!="pa_breakout_atr_buffer" or previous_atr not in (None,0))
                    emitted: set[tuple[str,str,str,str]] = set()
                    if previous_evaluable and prev is not None:
                        for direction,entries,levels in (("bullish",upper,upper_levels),("bearish",lower,lower_levels)):
                            window=self._pa7_window(levels,definition_id=definition_id,direction=direction,previous_bar=prev,bar=bar,previous_atr=previous_atr,current_atr=current_atr,increment=increment,atr_fraction=atr_fraction)
                            if window is None: continue
                            lo,hi=window
                            for bnd in entries[lo:hi]:
                                if int(bnd["availability"])>prev.available_at: continue
                                if not self._pa7_boundary_active_at(bnd,prev.available_at) or not self._pa7_boundary_active_at(bnd,bar.available_at): continue
                                key=(bnd["group"],bnd["type"],bnd["id"],direction)
                                if key in emitted: continue
                                if self._pa7_beyond(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction) is True:
                                    self._pa7_emit_transition(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction,previous_bar_id=prev.id,initialization_transition=False); emitted.add(key)
                    if previous_evaluable and prev is not None:
                        a=bisect.bisect_right(avail_keys,prev.available_at); z=bisect.bisect_right(avail_keys,bar.available_at); initial_candidates=by_avail[a:z]
                    else:
                        z=bisect.bisect_right(avail_keys,bar.available_at); initial_candidates=by_avail[:z]
                    for bnd in initial_candidates:
                        if not self._pa7_boundary_active_at(bnd,bar.available_at): continue
                        for direction in ("bullish","bearish"):
                            key=(bnd["group"],bnd["type"],bnd["id"],direction)
                            if key in emitted: continue
                            if self._pa7_beyond(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction) is True:
                                self._pa7_emit_transition(definition_id,direction,bar,bnd,increment=increment,atr_fraction=atr_fraction,previous_bar_id=None,initialization_transition=True); emitted.add(key)
        self.out.commit()

'''


def amend_registry(registry: dict[str, Any]) -> str:
    if registry.get("registry_hash") != PREVIOUS_REGISTRY_HASH:
        raise SystemExit("unexpected pre-amendment definition registry identity")
    defs = registry["definitions"]
    exact = defs["pa_breakout_exact"]
    atr = defs["pa_breakout_atr_buffer"]
    point = defs["pa_breakout_point_buffer"]
    exact.update({
        "version": "PA7E.2",
        "enumeration_rule": "one record only for each causal NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY transition for the exact state key; persistent BEYOND state emits no additional records",
        "state_key": ["symbol", "timeframe", "direction", "exact_boundary_identity", "pa7_variant"],
        "initial_state_rule": "when an exact boundary identity first becomes causally eligible, initialize that PA7 variant/direction state as NOT_BEYOND_BOUNDARY; the first confirmed close satisfying the variant may create the transition event",
        "rearm_rule": "after a later causally eligible confirmed closed bar does not satisfy this variant's BEYOND predicate, state is NOT_BEYOND_BOUNDARY and a subsequent qualifying confirmed close may create a new transition; no future information is used",
        "lifecycle_identity_rule": "state belongs only to the exact boundary identity and is never carried to a different boundary identity; lifecycle termination retires that identity's state",
        "transition_rule": "NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY only",
        "persistent_state_records_forbidden": True,
    })
    for rec, version, name in ((atr, "PA7A.2", "pa_breakout_atr_buffer"), (point, "PA7P.2", "pa_breakout_point_buffer")):
        rec.update({
            "version": version,
            "enumeration_rule": f"same independent transition-event state machine as pa_breakout_exact, keyed separately for {name}; no cross-variant deduplication",
            "state_key": ["symbol", "timeframe", "direction", "exact_boundary_identity", "pa7_variant"],
            "initial_state_rule": "initialize NOT_BEYOND_BOUNDARY at first causal eligibility for this variant; emit only on first confirmed qualifying close",
            "rearm_rule": "a causally later eligible confirmed close that no longer satisfies this variant's BEYOND predicate returns state to NOT_BEYOND_BOUNDARY; a later crossing may emit again",
            "lifecycle_identity_rule": "state is scoped to the exact boundary identity and this PA7 variant; no carry to another boundary identity",
            "transition_rule": "NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY only",
            "persistent_state_records_forbidden": True,
        })
    rules = registry["global_rules"]
    old = "Create one record for every qualifying evidence tuple unless a definition explicitly states first-qualifying resolution; never select a preferred object or school."
    new = "Create one record for every qualifying evidence tuple unless a definition explicitly states transition-event or first-qualifying resolution; transition-event definitions emit only on their frozen causal state transition; never select a preferred object or school."
    if old not in rules:
        raise SystemExit("expected global persistent enumeration rule missing")
    rules[rules.index(old)] = new
    registry["format_version"] = 3
    registry["design_amendment"] = {
        "amendment_id": "G8-PA7-TRANSITION-EVENT-AMENDMENT-001",
        "gap_id": GAP_ID,
        "reason": "approved correction of frozen PA7 persistent-state cardinality contradiction",
        "semantics": "PA7_TRANSITION_EVENT_ENUMERATION",
        "previous_registry_hash": PREVIOUS_REGISTRY_HASH,
        "variants": {"pa_breakout_exact":"PA7E.2","pa_breakout_atr_buffer":"PA7A.2","pa_breakout_point_buffer":"PA7P.2"},
        "2024_oos_used": False,
    }
    registry["registry_hash"] = self_hash(registry, "registry_hash")
    return str(registry["registry_hash"])


def amend_freeze(freeze: dict[str, Any], registry_hash: str) -> str:
    if freeze.get("design_freeze_hash") != PREVIOUS_FREEZE_HASH or freeze.get("definition_registry_hash") != PREVIOUS_REGISTRY_HASH:
        raise SystemExit("unexpected pre-amendment Design Freeze identity")
    freeze["format_version"] = 5
    freeze["definition_registry_hash"] = registry_hash
    freeze["design_amendment"] = {
        "amendment_version": 1,
        "amendment_id": "G8-PA7-TRANSITION-EVENT-AMENDMENT-001",
        "gap_id": GAP_ID,
        "approved_semantics": "PA7_TRANSITION_EVENT_ENUMERATION",
        "previous_design_freeze_hash": PREVIOUS_FREEZE_HASH,
        "previous_definition_registry_hash": PREVIOUS_REGISTRY_HASH,
        "scope": ["pa_breakout_exact", "pa_breakout_atr_buffer", "pa_breakout_point_buffer", "PA7 enumeration state machine"],
        "groups_1_7_changed": False,
        "thresholds_changed": False,
        "schema_changed": False,
        "upstream_lineage_changed": False,
        "oos_2024_accessed": False,
    }
    freeze["identity_hash_algorithm"] = "sha256(canonical_json_without_design_freeze_hash)"
    freeze["design_freeze_hash"] = self_hash(freeze, "design_freeze_hash")
    return str(freeze["design_freeze_hash"])


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--group8-root", type=Path, required=True); a = p.parse_args()
    root = a.group8_root.resolve(); engine_path=root/"code/moebot_group8_engine_v0_8_0.py"; registry_path=root/"01_DEFINITION_REGISTRY.json"; freeze_path=root/"DESIGN_FREEZE_MANIFEST.json"; status_path=root/"STATUS.json"
    if sha256_file(engine_path) != PREVIOUS_ENGINE_SHA256: raise SystemExit("unexpected pre-amendment engine identity")
    status=json.loads(status_path.read_text())
    gap=status.get("blocking_gap",{})
    if gap.get("gap_id")!=GAP_ID or gap.get("status")!="OPEN_DESIGN_DECISION_REQUIRED" or gap.get("report_hash")!=BLOCKER_REPORT_HASH or gap.get("workload_report_hash")!=WORKLOAD_REPORT_HASH:
        raise SystemExit("Gap 007 is not the exact authoritative open design blocker")
    if status.get("annual_execution_2024_authorized") is not False or status.get("officially_closed") is not False:
        raise SystemExit("invalid OOS/closure precondition")

    registry=json.loads(registry_path.read_text()); registry_hash=amend_registry(registry); registry_path.write_text(json.dumps(registry,indent=2,sort_keys=True)+"\n")
    freeze=json.loads(freeze_path.read_text()); freeze_hash=amend_freeze(freeze,registry_hash); freeze_path.write_text(json.dumps(freeze,indent=2,sort_keys=True)+"\n")

    text=engine_path.read_text()
    start=text.index("    def process_breakouts(self) -> None:\n")
    end=text.index("    def process_context_rejections(self) -> None:\n",start)
    text=text[:start]+NEW_BREAKOUT_BLOCK+text[end:]
    old_reg=f'EXPECTED_DEFINITION_REGISTRY_HASH = "{PREVIOUS_REGISTRY_HASH}"'; new_reg=f'EXPECTED_DEFINITION_REGISTRY_HASH = "{registry_hash}"'
    old_freeze=f'EXPECTED_DESIGN_FREEZE_HASH = "{PREVIOUS_FREEZE_HASH}"'; new_freeze=f'EXPECTED_DESIGN_FREEZE_HASH = "{freeze_hash}"'
    if text.count(old_reg)!=1 or text.count(old_freeze)!=1: raise SystemExit("engine frozen identity constants not found exactly once")
    text=text.replace(old_reg,new_reg,1).replace(old_freeze,new_freeze,1); engine_path.write_text(text)
    amended_engine_sha=sha256_file(engine_path)

    report=write_hashed(root/"reports/37_PA7_TRANSITION_EVENT_DESIGN_AMENDMENT.json",{
        "format_version":1,"status":"DESIGN_AMENDMENT_APPLIED_PENDING_TECHNICAL_REFREEZE","gap_id":GAP_ID,"amendment_id":"G8-PA7-TRANSITION-EVENT-AMENDMENT-001","approved_semantics":"PA7_TRANSITION_EVENT_ENUMERATION","previous_engine_sha256":PREVIOUS_ENGINE_SHA256,"amended_engine_sha256":amended_engine_sha,"previous_definition_registry_hash":PREVIOUS_REGISTRY_HASH,"amended_definition_registry_hash":registry_hash,"previous_design_freeze_hash":PREVIOUS_FREEZE_HASH,"amended_design_freeze_hash":freeze_hash,"variant_versions":{"exact":"PA7E.2","atr":"PA7A.2","point":"PA7P.2"},"state_key_minimum":["symbol","timeframe","direction","exact_boundary_identity","pa7_variant"],"transition":"NOT_BEYOND_BOUNDARY -> BEYOND_BOUNDARY","rearm":"later causal eligible closed bar not satisfying the same variant BEYOND predicate rearms NOT_BEYOND; next crossing may emit","availability":"max(closed bar availability, exact boundary availability); never before confirmation","persistent_state_enumeration_removed":True,"groups_1_7_changed":False,"upstream_lineage_changed":False,"thresholds_changed":False,"schema_changed":False,"oos_2024_accessed":False,"blocker_report_hash":BLOCKER_REPORT_HASH,"workload_report_hash":WORKLOAD_REPORT_HASH})

    status["annual_execution_authorized"]=False; status["annual_execution_2023_authorized"]=False; status["annual_execution_2024_authorized"]=False; status["engine_build_authorized"]=False
    status["design_frozen"]=True
    status["blocking_gap"]={"gap_id":GAP_ID,"severity":"BLOCKING","status":"FIXED_PENDING_TECHNICAL_REFREEZE","classification":"FROZEN_DESIGN_CARDINALITY_CONTRADICTION","decision_required":False,"design_change_required":True,"approved_design":"PA7_TRANSITION_EVENT_ENUMERATION","design_amendment_report_hash":report["report_hash"],"previous_engine_sha256":PREVIOUS_ENGINE_SHA256,"amended_engine_sha256":amended_engine_sha,"previous_definition_registry_hash":PREVIOUS_REGISTRY_HASH,"amended_definition_registry_hash":registry_hash,"previous_design_freeze_hash":PREVIOUS_FREEZE_HASH,"amended_design_freeze_hash":freeze_hash,"oos_2024_accessed":False}
    status["engine_build"]["status"]="STALE_PENDING_TECHNICAL_REFREEZE_AFTER_PA7_DESIGN_AMENDMENT"; status["engine_build"]["engine_sha256"]=amended_engine_sha
    status["status"]="PA7_TRANSITION_EVENT_DESIGN_AMENDMENT_APPLIED_PENDING_TECHNICAL_REFREEZE"; status["officially_closed"]=False
    status["design_amendment_hash"]=report["report_hash"]; status_path.write_text(json.dumps(status,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":"PASS","gap_id":GAP_ID,"registry_hash":registry_hash,"design_freeze_hash":freeze_hash,"engine_sha256":amended_engine_sha,"2023_authorized":False,"2024_authorized":False},indent=2,sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
