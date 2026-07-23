#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from moebot_group7_engine import DEFINITIONS, canonical_json, file_sha256, sha256_text, stable_id


def run(db_path: Path, write_audit: bool = False, source_override: Path | None = None, group6_override: Path | None = None) -> Dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    checks: Dict[str, Dict[str, Any]] = {}

    def add(name: str, errors: int, details: Any = None) -> None:
        checks[name] = {"status": "PASS" if errors == 0 else "FAIL", "errors": int(errors), "details": details}

    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    add("sqlite_integrity", 0 if integrity == "ok" else 1, integrity)
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    add("foreign_keys", fk)

    ds = con.execute("SELECT * FROM dataset_registry").fetchone()
    source = source_override or Path(ds["source_db"]); g6 = group6_override or Path(ds["group6_db"])
    if not source.is_absolute(): source = db_path.parent / source
    if not g6.is_absolute(): g6 = db_path.parent / g6
    add("source_file_present", 0 if source.exists() else 1, str(source))
    add("group6_file_present", 0 if g6.exists() else 1, str(g6))
    source_sha = file_sha256(source) if source.exists() else None
    g6_sha = file_sha256(g6) if g6.exists() else None
    add("source_fingerprint", 0 if source_sha == ds["source_sha256"] else 1, {"expected": ds["source_sha256"], "actual": source_sha})
    add("group6_fingerprint", 0 if g6_sha == ds["group6_sha256"] else 1, {"expected": ds["group6_sha256"], "actual": g6_sha})

    # Registry reconstruction.
    errors = 0
    for row in con.execute("SELECT * FROM config_registry"):
        errors += sha256_text(row["config_json"]) != row["config_hash"]
    add("config_hash_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM definition_registry"):
        errors += sha256_text(row["definition_json"]) != row["definition_hash"]
        spec = DEFINITIONS.get(row["definition_id"])
        errors += spec is None or canonical_json(spec) != row["definition_json"]
    add("definition_registry_reconstruction", errors)
    ds_payload = {"dataset_id": ds["dataset_id"], "source_sha256": ds["source_sha256"], "group6_sha256": ds["group6_sha256"]}
    add("dataset_hash_reconstruction", 0 if sha256_text(canonical_json(ds_payload)) == ds["record_hash"] else 1)
    errors = 0
    for row in con.execute("SELECT * FROM dependency_registry"):
        payload = {"group_name": row["group_name"], "sha256": row["sha256"], "read_only": row["read_only"], "transitive": row["transitive"]}
        if row["transitive"]:
            payload["source_dependency_id"] = row["source_dependency_id"]
        errors += stable_id("dep7_", payload) != row["dependency_id"]
        errors += sha256_text(canonical_json(payload)) != row["record_hash"]
        errors += row["read_only"] != 1
    add("dependency_id_hash_readonly", errors)

    leg_hashes: Dict[str, str] = {}
    fvg_availability: Dict[str, int] = {}
    evidence_availability: Dict[str, int] = {}
    if g6.exists():
        cg = sqlite3.connect(f"file:{g6}?mode=ro", uri=True); cg.row_factory = sqlite3.Row
        leg_hashes = {r["leg_id"]: r["record_hash"] for r in cg.execute("SELECT leg_id,record_hash FROM displacement_legs")}
        fvg_availability = {r["fvg_id"]: r["availability_time"] for r in cg.execute("SELECT fvg_id,availability_time FROM fvg_events")}
        evidence_availability = {r["source_id"]: r["availability_time"] for r in cg.execute("SELECT source_id,availability_time FROM group6_evidence")}
        cg.close()

    config_id = con.execute("SELECT config_id FROM config_registry").fetchone()[0]
    # Candidate and match records are immutable and separately reconstructed.
    errors = 0
    for row in con.execute("SELECT * FROM definition_candidates"):
        features = json.loads(row["features_json"]); reasons = json.loads(row["reasons_json"])
        payload = {
            "config_id": config_id, "definition_id": row["definition_id"], "source_leg_id": row["source_leg_id"],
            "candidate_time": row["candidate_time"], "availability_time": row["availability_time"],
            "lower": row["lower"], "upper": row["upper"], "source_bar_id": row["source_bar_id"],
            "intrinsic_pass": bool(row["intrinsic_pass"]), "reasons": reasons, "features": features,
            "upstream_leg_record_hash": leg_hashes.get(row["source_leg_id"]),
        }
        errors += sha256_text(row["features_json"]) != row["feature_hash"]
        errors += stable_id("cand7_", payload) != row["candidate_id"]
        errors += sha256_text(canonical_json(payload)) != row["candidate_hash"]
    add("candidate_full_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM definition_matches"):
        candidate = con.execute("SELECT availability_time FROM definition_candidates WHERE candidate_id=?", (row["candidate_id"],)).fetchone()
        evidence = [(str(item[0]), int(item[1])) for item in json.loads(row["evidence_json"])]
        evidence_ids = json.loads(row["evidence_ids_json"]); features = json.loads(row["features_json"]); reasons = json.loads(row["reasons_json"])
        payload = {
            "candidate_id": row["candidate_id"], "definition_id": row["definition_id"],
            "source_leg_id": row["source_leg_id"], "match_time": row["match_time"],
            "availability_time": row["availability_time"], "evidence": evidence,
            "reasons": reasons, "features": features,
        }
        errors += candidate is None
        errors += row["availability_time"] < (candidate[0] if candidate else 0)
        errors += row["availability_time"] != row["evidence_availability_max"]
        errors += row["evidence_availability_max"] != max([candidate[0] if candidate else 0] + [t for _, t in evidence])
        errors += evidence_ids != [i for i, _ in evidence]
        errors += stable_id("match7_", payload) != row["match_id"]
        errors += sha256_text(canonical_json(payload)) != row["match_hash"]
    add("match_full_reconstruction", errors)
    # Evaluation full ID/hash reconstruction.
    errors = 0
    for row in con.execute("SELECT * FROM block_evaluations"):
        payload = {
            "config_id": config_id,
            "definition_id": row["definition_id"],
            "source_leg_id": row["source_leg_id"],
            "parent_zone_id": row["parent_zone_id"],
            "candidate_id": row["candidate_id"],
            "match_id": row["match_id"],
            "evaluation_time": row["evaluation_time"],
            "availability_time": row["availability_time"],
            "passed": bool(row["passed"]),
            "reasons": json.loads(row["reasons_json"]),
            "features": json.loads(row["features_json"]),
        }
        errors += sha256_text(row["features_json"]) != row["feature_hash"]
        errors += stable_id("eval7_", payload) != row["evaluation_id"]
        errors += sha256_text(canonical_json(payload)) != row["evaluation_hash"]
    add("evaluation_full_reconstruction", errors)

    # Zone full ID/hash reconstruction.
    errors = 0
    for row in con.execute("SELECT * FROM institutional_zones"):
        features = json.loads(row["creation_features_json"])
        creation = {
            "config_id": config_id,
            "definition_id": row["definition_id"],
            "definition_version": DEFINITIONS[row["definition_id"]]["definition_version"],
            "timeframe": row["timeframe"],
            "direction": row["direction"],
            "lower": round(float(row["lower"]), 8),
            "upper": round(float(row["upper"]), 8),
            "event_time": row["event_time"],
            "confirmation_time": row["confirmation_time"],
            "availability_time": row["availability_time"],
            "source_leg_id": row["source_leg_id"],
            "candidate_id": row["candidate_id"],
            "match_id": row["match_id"],
            "source_bar_id": row["source_bar_id"],
            "parent_zone_id": row["parent_zone_id"],
            "features": features,
            "upstream_leg_record_hash": leg_hashes.get(row["source_leg_id"]),
        }
        errors += sha256_text(row["creation_features_json"]) != row["feature_hash"]
        errors += stable_id("zone7_", creation) != row["zone_id"]
        errors += sha256_text(canonical_json(creation)) != row["creation_hash"]
    add("zone_full_reconstruction", errors)

    # Evidence, relation, transition, visit, summary reconstruction.
    errors = 0
    for row in con.execute("SELECT * FROM zone_evidence"):
        payload = {"zone_id": row["zone_id"], "evidence_type": row["evidence_type"], "source_group": row["source_group"], "source_id": row["source_id"], "relation_type": row["relation_type"], "availability_time": row["availability_time"], "details": json.loads(row["details_json"])}
        errors += stable_id("zev7_", payload) != row["evidence_id"]
        errors += sha256_text(canonical_json(payload)) != row["evidence_hash"]
    add("evidence_full_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM zone_relations"):
        payload = {"subject": row["subject_zone_id"], "object": row["object_zone_id"], "relation_type": row["relation_type"], "availability_time": row["availability_time"], "overlap_ratio": row["overlap_ratio"], "details": json.loads(row["details_json"])}
        errors += stable_id("zrel7_", payload) != row["relation_id"]
        errors += sha256_text(canonical_json(payload)) != row["relation_hash"]
    add("relation_full_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM zone_state_transitions"):
        payload = {"zone_id": row["zone_id"], "ordinal": row["transition_ordinal"], "bar_id": row["bar_id"], "transition_time": row["transition_time"], "event_type": row["event_type"], "status": row["status"], "freshness": row["freshness"], "visit_count": row["visit_count"], "mitigation_count": row["mitigation_count"], "max_penetration": row["max_penetration"], "details": json.loads(row["details_json"])}
        errors += stable_id("ztr7_", payload) != row["transition_id"]
        errors += sha256_text(canonical_json(payload)) != row["transition_hash"]
    add("transition_full_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM zone_visit_observations"):
        payload = {k: row[k] for k in ("zone_id", "visit_ordinal", "start_bar_id", "start_time", "end_time", "duration_bars", "max_penetration", "mitigated", "right_censored")}
        errors += stable_id("visit7_", payload) != row["visit_id"]
        errors += sha256_text(canonical_json(payload)) != row["visit_hash"]
    add("visit_full_reconstruction", errors)
    errors = 0
    for row in con.execute("SELECT * FROM zone_lifecycle_summary"):
        payload = {k: row[k] for k in ("zone_id", "status", "freshness", "visit_count", "mitigation_count", "max_penetration", "first_touch_time", "invalidated_time")}
        errors += sha256_text(canonical_json(payload)) != row["summary_hash"]
    add("summary_hash_reconstruction", errors)

    # Causality and semantic gates.
    add("zone_time_order", con.execute("SELECT COUNT(*) FROM institutional_zones WHERE event_time>confirmation_time OR confirmation_time>availability_time").fetchone()[0])
    add("candidate_cardinality", con.execute("SELECT COUNT(*) FROM (SELECT source_leg_id,COUNT(*) n FROM definition_candidates GROUP BY source_leg_id HAVING n!=6)").fetchone()[0])
    add("match_after_candidate", con.execute("SELECT COUNT(*) FROM definition_matches m JOIN definition_candidates c USING(candidate_id) WHERE m.availability_time<c.availability_time").fetchone()[0])
    add("match_after_evidence", con.execute("SELECT COUNT(*) FROM definition_matches WHERE availability_time<evidence_availability_max").fetchone()[0])
    add("zone_after_match", con.execute("SELECT COUNT(*) FROM institutional_zones z JOIN definition_matches m USING(match_id) WHERE z.availability_time<m.availability_time").fetchone()[0])
    add("base_zone_has_match", con.execute("SELECT COUNT(*) FROM institutional_zones WHERE definition_id IN ('strict_order_block','loose_order_block','last_opposing_candle','rejection_block','propulsion_block','supply_demand_origin') AND match_id IS NULL").fetchone()[0])
    add("transition_causality", con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE t.transition_time<z.availability_time").fetchone()[0])
    add("evidence_causality", con.execute("SELECT COUNT(*) FROM zone_evidence e JOIN institutional_zones z USING(zone_id) WHERE e.availability_time<z.availability_time AND e.evidence_type NOT IN ('source_leg','parent_zone')").fetchone()[0])
    add("immutable_summary_coverage", con.execute("SELECT COUNT(*) FROM institutional_zones z LEFT JOIN zone_lifecycle_summary s USING(zone_id) WHERE s.zone_id IS NULL").fetchone()[0])
    add("duplicate_transition_ordinals", con.execute("SELECT COUNT(*) FROM (SELECT zone_id,transition_ordinal,COUNT(*) n FROM zone_state_transitions GROUP BY 1,2 HAVING n!=1)").fetchone()[0])
    add("invalid_bounds", con.execute("SELECT COUNT(*) FROM institutional_zones WHERE upper<=lower").fetchone()[0])
    add("breaker_parent_contract", con.execute("SELECT COUNT(*) FROM institutional_zones b LEFT JOIN institutional_zones p ON p.zone_id=b.parent_zone_id WHERE b.definition_id='breaker_block' AND (p.zone_id IS NULL OR p.definition_id NOT IN ('strict_order_block','loose_order_block','last_opposing_candle') OR b.direction=p.direction)").fetchone()[0])
    add("mitigation_parent_contract", con.execute("SELECT COUNT(*) FROM institutional_zones m JOIN institutional_zones p ON p.zone_id=m.parent_zone_id JOIN zone_lifecycle_summary s ON s.zone_id=p.zone_id WHERE m.definition_id='mitigation_block' AND (s.first_touch_time IS NULL OR m.availability_time<=s.first_touch_time OR (s.invalidated_time IS NOT NULL AND m.availability_time>=s.invalidated_time))").fetchone()[0])
    add("two_close_candidate_presence", 0 if con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE z.definition_id IN ('loose_order_block','supply_demand_origin') AND t.event_type='invalidated'").fetchone()[0] == 0 or con.execute("SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE z.definition_id IN ('loose_order_block','supply_demand_origin') AND t.event_type='invalidation_candidate'").fetchone()[0] > 0 else 1)
    add("definitions_not_merged", con.execute("SELECT COUNT(*) FROM institutional_zones WHERE definition_id NOT IN (%s)" % ",".join("?" * len(DEFINITIONS)), tuple(DEFINITIONS)).fetchone()[0])
    add("no_trade_schema", sum(1 for table in con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL") for token in ("entry_price", "stop_loss", "take_profit", "pnl", "mfe", "mae") if token in table[0].lower()))

    passed = all(v["errors"] == 0 for v in checks.values())
    if write_audit:
        now = int(time.time())
        for name, value in checks.items():
            payload = {"check_name": name, "status": value["status"], "scope": "independent_full_database", "details": value, "checked_at": now}
            row = (stable_id("audit7_", payload), name, value["status"], "independent_full_database", canonical_json(value), now, sha256_text(canonical_json(payload)))
            existing = con.execute("SELECT audit_hash FROM group7_audit_evidence WHERE audit_id=?", (row[0],)).fetchone()
            if existing is None:
                con.execute("INSERT INTO group7_audit_evidence VALUES(?,?,?,?,?,?,?)", row)
            elif existing[0] != row[-1]:
                raise ValueError(f"Conflicting audit identity {row[0]}")
        con.commit()
    con.close()
    return {"passed": passed, "database": str(db_path), "checks": checks, "summary": {"pass": sum(v["errors"] == 0 for v in checks.values()), "fail": sum(v["errors"] != 0 for v in checks.values()), "total": len(checks)}}


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--db", required=True); p.add_argument("--write-audit", action="store_true"); p.add_argument("--json-out"); p.add_argument("--source"); p.add_argument("--group6")
    a = p.parse_args(); result = run(Path(a.db), a.write_audit, Path(a.source) if a.source else None, Path(a.group6) if a.group6 else None); text = json.dumps(result, indent=2, sort_keys=True)
    if a.json_out: Path(a.json_out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__": main()
