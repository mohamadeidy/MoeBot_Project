#!/usr/bin/env python3
"""Freeze Group 8 design only after annual dependency and exact adapter gates PASS."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ENGINE_VERSION = "0.8.0"
SCHEMA_VERSION = "8.0.0"


def canonical_json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group8-root", type=Path, required=True)
    ap.add_argument("--annual-registry", type=Path, required=True)
    ap.add_argument("--adapter-map", type=Path, required=True)
    ap.add_argument("--group7-amendment", type=Path, required=True)
    args = ap.parse_args()

    root = args.group8_root.resolve()
    annual = json.loads(args.annual_registry.read_text(encoding="utf-8"))
    adapters = json.loads(args.adapter_map.read_text(encoding="utf-8"))
    g7 = json.loads(args.group7_amendment.read_text(encoding="utf-8"))
    if annual.get("status") != "PASS":
        raise RuntimeError("annual upstream registry is not PASS")
    if adapters.get("status") != "PASS":
        raise RuntimeError("adapter map is not PASS")
    if g7.get("status") != "PASS_RECOVERY_AMENDMENT":
        raise RuntimeError("Group7 recovery amendment is not PASS")
    if annual.get("group7_source_closure_commit_sha") != g7.get("source_closure_commit_sha"):
        raise RuntimeError("Group7 closure identity mismatch")

    # Frozen configuration.
    cfg = json.loads((root / "FROZEN_CONFIG_DRAFT.json").read_text(encoding="utf-8"))
    cfg["config_status"] = "FROZEN"
    cfg["engine_version"] = ENGINE_VERSION
    cfg["schema_version"] = SCHEMA_VERSION
    cfg["annual_dependency_registry_hash"] = annual["registry_hash"]
    cfg["adapter_map_hash"] = adapters["adapter_map_hash"]
    cfg["group7_recovery_reference"] = {
        "mode": g7["recovery_reference_mode"],
        "anchor_tag": g7["recovery_release_anchor_tag"],
        "anchor_commit_sha": g7["recovery_release_anchor_commit_sha"],
        "logical_recovery_id": g7["logical_recovery_id"],
    }
    cfg_payload = copy.deepcopy(cfg)
    cfg_payload.pop("config_id", None)
    cfg["config_id"] = "cfg8_" + hashlib.sha256(canonical_json(cfg_payload).encode()).hexdigest()
    write_json(root / "FROZEN_CONFIG.json", cfg)

    # Frozen definition registry.
    definitions = json.loads((root / "01_DEFINITION_REGISTRY_DRAFT.json").read_text(encoding="utf-8"))
    definitions["status"] = "FROZEN"
    definitions["engine_version"] = ENGINE_VERSION
    definitions["schema_version"] = SCHEMA_VERSION
    definitions["config_id"] = cfg["config_id"]
    definitions["adapter_map_hash"] = adapters["adapter_map_hash"]
    definitions["registry_hash"] = hashlib.sha256(canonical_json({k:v for k,v in definitions.items() if k != "registry_hash"}).encode()).hexdigest()
    write_json(root / "01_DEFINITION_REGISTRY.json", definitions)

    # Exact upstream contract binds the semantic draft to the audited adapter map.
    contract = json.loads((root / "contracts/UPSTREAM_INPUT_CONTRACT_DRAFT.json").read_text(encoding="utf-8"))
    contract["contract_version"] = "1.0.0"
    contract["status"] = "FROZEN"
    contract["annual_dependency_registry_hash"] = annual["registry_hash"]
    contract["adapter_map_hash"] = adapters["adapter_map_hash"]
    for key, item in contract.get("inputs", {}).items():
        group = {
            "group1_canonical_bars": "source",
            "group2_regime": "group2",
            "group3_structure": "group3",
            "group4_zones": "group4",
            "group5_liquidity": "group5",
            "group6_imbalance_delivery": "group6",
            "group7_blocks": "group7",
        }.get(key)
        if group:
            item["exact_table_adapter"] = {
                "adapter_map": "UPSTREAM_ADAPTER_MAP.json",
                "group_key": group,
                "adapter_map_hash": adapters["adapter_map_hash"],
            }
    contract["contract_hash"] = hashlib.sha256(canonical_json({k:v for k,v in contract.items() if k != "contract_hash"}).encode()).hexdigest()
    write_json(root / "contracts/UPSTREAM_INPUT_CONTRACT.json", contract)

    # Frozen SQL is byte-preserved from the reviewed draft candidate.
    schema = (root / "02_SCHEMA_DRAFT.sql").read_text(encoding="utf-8")
    (root / "02_SCHEMA.sql").write_text(schema, encoding="utf-8")
    schema_hash = hashlib.sha256(schema.encode("utf-8")).hexdigest()

    # Frozen design lock updates only governance references; ontology body remains reviewed draft text.
    design = (root / "00_DESIGN_LOCK_DRAFT.md").read_text(encoding="utf-8")
    design = design.replace("## Design Lock Draft v0.8.0-draft.1", "## Design Lock v0.8.0")
    old_status = "**Status:** DRAFT ONLY — NOT FROZEN — ENGINE BUILD AND ANNUAL EXECUTION FORBIDDEN UNTIL DEPENDENCY INTAKE PASS"
    design = design.replace(old_status, "**Status:** FROZEN — DEPENDENCY INTAKE PASS — ENGINE BUILD AUTHORIZED; 2024 OOS REMAINS FORBIDDEN UNTIL 2023 FREEZE")
    design = design.replace("**Data release tag:** `moebot-group7-v0.7.5`.", "**Recovered annual data reference:** closure-anchored recovery assets on `moebot-group7-v0.7.5-closure`, governed by `Group_7/registry/DATA_RELEASE_RECOVERY_AMENDMENT_v1.json`.")
    start = design.find("## 3. Dependency and freeze gate")
    end = design.find("## 4. Time and causality contract")
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("unable to locate dependency gate section in design draft")
    gate = f'''## 3. Dependency and freeze gate\n\n**FROZEN PASS.** The following evidence is mandatory and satisfied at this freeze:\n\n1. Group 7 source closure tag `{g7["source_closure_tag"]}` resolves to `{g7["source_closure_commit_sha"]}`.\n2. Historical data tag `moebot-group7-v0.7.5` is explicitly rejected for new dependencies after post-closure clobber.\n3. Group 7 recovery amendment status is `{g7["status"]}` and recovered annual assets are anchored to the immutable source-closure tag.\n4. Corrected Groups 2–6 runtime bundle v3 is restored and all engine SHA-256 identities pass.\n5. Real annual Group 2–5 SQLite dependencies are materialized from runtime v3, published additively, and clean-room verified.\n6. Candidate v3 Group 6 semantic core matches the published Data Vault Group 6 for both annual years before Group 2–5 materialization is accepted.\n7. Real 2023 and 2024 SQLite schemas for source and Groups 2–7 were introspected; required Group 8 adapters are cross-year stable.\n8. `UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json` hash is `{annual["registry_hash"]}`.\n9. `UPSTREAM_ADAPTER_MAP.json` hash is `{adapters["adapter_map_hash"]}`.\n10. Guessed source identifiers, legacy Group 6 identities, historical-clobbered Group 7 assets, and mutable dependency access remain forbidden.\n\n'''
    design = design[:start] + gate + design[end:]
    design += f'''\n## Frozen artifact identities\n\n- Engine version: `{ENGINE_VERSION}`\n- Schema version: `{SCHEMA_VERSION}`\n- Config ID: `{cfg["config_id"]}`\n- Definition registry hash: `{definitions["registry_hash"]}`\n- Upstream contract hash: `{contract["contract_hash"]}`\n- SQL schema SHA-256: `{schema_hash}`\n- Annual dependency registry hash: `{annual["registry_hash"]}`\n- Adapter map hash: `{adapters["adapter_map_hash"]}`\n'''
    (root / "00_DESIGN_LOCK.md").write_text(design, encoding="utf-8")

    # Freeze status.
    status = json.loads((root / "STATUS.json").read_text(encoding="utf-8"))
    status.update({
        "annual_execution_authorized": True,
        "config_id": cfg["config_id"],
        "design_frozen": True,
        "engine_build_authorized": True,
        "officially_closed": False,
        "proposed_engine_version": ENGINE_VERSION,
        "proposed_schema_version": SCHEMA_VERSION,
        "status": "DESIGN_FROZEN_ENGINE_BUILD_AUTHORIZED_2023_ONLY",
        "required_group7_data_release_tag": None,
        "required_group7_recovery_anchor_tag": g7["recovery_release_anchor_tag"],
        "required_group7_recovery_anchor_commit_sha": g7["recovery_release_anchor_commit_sha"],
        "annual_dependency_registry_hash": annual["registry_hash"],
        "adapter_map_hash": adapters["adapter_map_hash"],
    })
    status["dependency_intake"] = {
        "verdict": "PASS",
        "closure_reference": "PASS",
        "group7_recovery_amendment": "PASS",
        "annual_upstream_registry": "PASS",
        "real_cross_year_adapter_map": "PASS",
        "runtime_bundle_v3": "PASS",
        "annual_dependency_registry_hash": annual["registry_hash"],
        "adapter_map_hash": adapters["adapter_map_hash"],
    }
    write_json(root / "STATUS.json", status)

    manifest = {
        "format_version": 1,
        "status": "FROZEN",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": cfg["config_id"],
        "definition_registry_hash": definitions["registry_hash"],
        "upstream_contract_hash": contract["contract_hash"],
        "schema_sha256": schema_hash,
        "annual_dependency_registry_hash": annual["registry_hash"],
        "adapter_map_hash": adapters["adapter_map_hash"],
        "group7_closure_tag": g7["source_closure_tag"],
        "group7_closure_commit_sha": g7["source_closure_commit_sha"],
    }
    manifest["design_freeze_hash"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    write_json(root / "DESIGN_FREEZE_MANIFEST.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
