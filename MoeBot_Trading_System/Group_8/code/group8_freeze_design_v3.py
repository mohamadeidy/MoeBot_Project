#!/usr/bin/env python3
"""Freeze Group8 v0.8.0 only from coherent corrected-v3 dependency evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ENGINE_VERSION = "0.8.0"
SCHEMA_VERSION = "8.0.0"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group8-root", type=Path, required=True)
    ap.add_argument("--annual-registry", type=Path, required=True)
    ap.add_argument("--lineage-amendment", type=Path, required=True)
    ap.add_argument("--adapter-map", type=Path, required=True)
    ap.add_argument("--categorical-dictionary", type=Path, required=True)
    ap.add_argument("--value-bindings", type=Path, required=True)
    ap.add_argument("--reference-resolution", type=Path, required=True)
    ap.add_argument("--source-semantics", type=Path, required=True)
    ap.add_argument("--design-audit", type=Path, required=True)
    args = ap.parse_args()

    root = args.group8_root.resolve()
    annual = json.loads(args.annual_registry.read_text())
    lineage = json.loads(args.lineage_amendment.read_text())
    adapters = json.loads(args.adapter_map.read_text())
    categories = json.loads(args.categorical_dictionary.read_text())
    bindings = json.loads(args.value_bindings.read_text())
    resolution = json.loads(args.reference_resolution.read_text())
    semantics = json.loads(args.source_semantics.read_text())
    audit = json.loads(args.design_audit.read_text())

    gates = {
        "annual_registry": annual.get("status") == "PASS",
        "lineage_amendment": lineage.get("status") == "PASS_COHERENT_DEPENDENCY_LINEAGE",
        "adapter_map": adapters.get("status") == "PASS",
        "categorical_dictionary": categories.get("status") == "PASS",
        "value_bindings": bindings.get("status") == "PASS",
        "reference_resolution": resolution.get("status") == "PASS",
        "source_semantics": semantics.get("status") == "PASS",
        "design_contract_audit_v3": audit.get("status") == "PASS",
    }
    bad = [name for name, passed in gates.items() if not passed]
    if bad:
        raise RuntimeError(f"freeze gates failed: {bad}")

    if annual.get("lineage_amendment_hash") != lineage.get("amendment_hash"):
        raise RuntimeError("registry/amendment hash mismatch")
    if annual.get("logical_lineage_id") != lineage.get("logical_lineage_id"):
        raise RuntimeError("registry/amendment logical lineage mismatch")
    if annual.get("lineage") != lineage.get("lineage"):
        raise RuntimeError("registry/amendment lineage mismatch")
    if bindings.get("categorical_dictionary_hash") != categories.get("dictionary_hash"):
        raise RuntimeError("binding/category hash mismatch")
    if bindings.get("source_semantics_evidence_hash") != semantics.get("evidence_hash"):
        raise RuntimeError("binding/source-semantics hash mismatch")
    if resolution.get("binding_hash") != bindings.get("binding_hash"):
        raise RuntimeError("reference-resolution/binding hash mismatch")

    config = json.loads((root / "FROZEN_CONFIG_DRAFT.json").read_text())
    config.update(
        {
            "config_status": "FROZEN",
            "engine_version": ENGINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "lineage": annual["lineage"],
            "logical_dependency_lineage_id": annual["logical_lineage_id"],
            "dependency_release_anchor_tag": annual["release_anchor_tag"],
            "coherent_lineage_amendment_hash": lineage["amendment_hash"],
            "annual_dependency_registry_hash": annual["registry_hash"],
            "adapter_map_hash": adapters["adapter_map_hash"],
            "categorical_dictionary_hash": categories["dictionary_hash"],
            "value_binding_hash": bindings["binding_hash"],
            "source_semantics_evidence_hash": semantics["evidence_hash"],
            "design_reference_resolution_hash": resolution["resolution_hash"],
            "design_contract_audit_hash": audit["report_hash"],
            "resolved_definition_references": resolution["resolved_references"],
            "group7_logic_source": annual["group7_logic_source"],
        }
    )
    config_payload = copy.deepcopy(config)
    config_payload.pop("config_id", None)
    config["config_id"] = "cfg8_" + hashlib.sha256(canonical_json(config_payload).encode()).hexdigest()
    write(root / "FROZEN_CONFIG.json", config)

    definitions = json.loads((root / "01_DEFINITION_REGISTRY_CANDIDATE_v2.json").read_text())
    definitions.update(
        {
            "status": "FROZEN",
            "engine_version": ENGINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "config_id": config["config_id"],
            "lineage": annual["lineage"],
            "logical_dependency_lineage_id": annual["logical_lineage_id"],
            "coherent_lineage_amendment_hash": lineage["amendment_hash"],
            "adapter_map_hash": adapters["adapter_map_hash"],
            "categorical_dictionary_hash": categories["dictionary_hash"],
            "value_binding_hash": bindings["binding_hash"],
            "source_semantics_evidence_hash": semantics["evidence_hash"],
            "reference_resolution_hash": resolution["resolution_hash"],
            "design_contract_audit_hash": audit["report_hash"],
        }
    )
    definitions["registry_hash"] = hashlib.sha256(
        canonical_json({k: v for k, v in definitions.items() if k != "registry_hash"}).encode()
    ).hexdigest()
    write(root / "01_DEFINITION_REGISTRY.json", definitions)

    contract = json.loads((root / "contracts/UPSTREAM_INPUT_CONTRACT_DRAFT.json").read_text())
    contract.update(
        {
            "contract_version": "1.0.0",
            "status": "FROZEN",
            "lineage": annual["lineage"],
            "logical_dependency_lineage_id": annual["logical_lineage_id"],
            "dependency_release_anchor_tag": annual["release_anchor_tag"],
            "coherent_lineage_amendment_hash": lineage["amendment_hash"],
            "annual_dependency_registry_hash": annual["registry_hash"],
            "adapter_map_hash": adapters["adapter_map_hash"],
            "categorical_dictionary_hash": categories["dictionary_hash"],
            "value_binding_hash": bindings["binding_hash"],
            "source_semantics_evidence_hash": semantics["evidence_hash"],
            "group7_logic_source": annual["group7_logic_source"],
        }
    )
    mapping = {
        "group1_canonical_bars": "source",
        "group2_regime": "group2",
        "group3_structure": "group3",
        "group4_zones": "group4",
        "group5_liquidity": "group5",
        "group6_imbalance_delivery": "group6",
        "group7_blocks": "group7",
    }
    for key, item in contract.get("inputs", {}).items():
        group = mapping.get(key)
        if group:
            item["exact_table_adapter"] = {
                "adapter_map": "UPSTREAM_ADAPTER_MAP.json",
                "group_key": group,
                "adapter_map_hash": adapters["adapter_map_hash"],
                "categorical_dictionary": "UPSTREAM_CATEGORICAL_DICTIONARY.json",
                "categorical_dictionary_hash": categories["dictionary_hash"],
                "value_bindings": "UPSTREAM_VALUE_BINDINGS.json",
                "value_binding_hash": bindings["binding_hash"],
                "lineage": annual["lineage"],
                "logical_lineage_id": annual["logical_lineage_id"],
                "release_anchor_tag": annual["release_anchor_tag"],
            }
    contract["adapter_discovery_gate"] = {
        "status": "PASS",
        "required_before_engine_build": True,
        "steps": [
            "Verify coherent corrected-v3 annual dependency registry and lineage amendment hashes.",
            "Publicly re-download SHA-pinned source and Groups2-7 annual SQLite dependencies for 2023 and untouched 2024 OOS.",
            "Verify exact filename, size, SHA-256, SQLite quick/integrity/foreign-key checks before row access.",
            "Capture exact sqlite_master/PRAGMA schemas and consumed categorical values for both years.",
            "Build exact read-only table/column adapters and source-verified value bindings.",
            "Reject guessed identifiers, historical clobbered assets and any lossy upstream-ID bridge.",
        ],
    }
    contract["contract_hash"] = hashlib.sha256(
        canonical_json({k: v for k, v in contract.items() if k != "contract_hash"}).encode()
    ).hexdigest()
    write(root / "contracts/UPSTREAM_INPUT_CONTRACT.json", contract)

    schema = (root / "02_SCHEMA_CANDIDATE_v3.sql").read_text()
    (root / "02_SCHEMA.sql").write_text(schema, encoding="utf-8")
    schema_hash = hashlib.sha256(schema.encode()).hexdigest()

    design = (root / "00_DESIGN_LOCK_DRAFT.md").read_text()
    design = design.replace("## Design Lock Draft v0.8.0-draft.1", "## Design Lock v0.8.0")
    design = design.replace(
        "**Status:** DRAFT ONLY — NOT FROZEN — ENGINE BUILD AND ANNUAL EXECUTION FORBIDDEN UNTIL DEPENDENCY INTAKE PASS",
        "**Status:** FROZEN — COHERENT DEPENDENCY INTAKE PASS — ENGINE BUILD AUTHORIZED; 2023 EXECUTION REQUIRES ENGINE TEST PASS; 2024 OOS FORBIDDEN UNTIL 2023 FREEZE",
    )
    start = design.find("## 3. Dependency and freeze gate")
    end = design.find("## 4. Time and causality contract")
    if start < 0 or end <= start:
        raise RuntimeError("dependency gate section not found")
    gate = f"""## 3. Dependency and freeze gate

**FROZEN PASS.**

1. Runtime bundle v3 is the exact corrected Groups2–6 source and all engine SHA-256 identities pass.
2. Group7 logic is unchanged v0.7.5 from closure `{annual['group7_logic_source']['closure_tag']}` / `{annual['group7_logic_source']['closure_commit_sha']}`.
3. Groups2–7 are rebuilt as one coherent lineage `{annual['logical_lineage_id']}` for 2023 and untouched 2024 OOS.
4. Every annual dependency passes public re-download, SHA-256, size, SQLite quick/integrity/foreign-key, exact-schema and categorical intake.
5. Cross-year validation and coherent-lineage amendment are SHA-bound; no historical or lossy ID bridge is permitted.
6. Exact adapter, categorical, source-semantics, value-binding, definition-reference and design-contract gates pass.
7. Definition Candidate v2 and Schema Candidate v3 are the only ontology/persistence artifacts eligible for this freeze.
8. BUY/SELL, entries, stops, targets, sizing, risk/PnL, future-return labels, profitability optimization and preferred-school ranking remain forbidden.

"""
    design = design[:start] + gate + design[end:]
    design += f"""
## Frozen artifact identities

- Engine version: `{ENGINE_VERSION}`
- Schema version: `{SCHEMA_VERSION}`
- Config ID: `{config['config_id']}`
- Logical dependency lineage ID: `{annual['logical_lineage_id']}`
- Dependency release anchor tag: `{annual['release_anchor_tag']}`
- Definition registry hash: `{definitions['registry_hash']}`
- Upstream contract hash: `{contract['contract_hash']}`
- SQL schema SHA-256: `{schema_hash}`
- Coherent lineage amendment hash: `{lineage['amendment_hash']}`
- Annual dependency registry hash: `{annual['registry_hash']}`
- Adapter map hash: `{adapters['adapter_map_hash']}`
- Categorical dictionary hash: `{categories['dictionary_hash']}`
- Value binding hash: `{bindings['binding_hash']}`
- Source semantics evidence hash: `{semantics['evidence_hash']}`
- Reference resolution hash: `{resolution['resolution_hash']}`
- Design contract audit v3 hash: `{audit['report_hash']}`
"""
    (root / "00_DESIGN_LOCK.md").write_text(design, encoding="utf-8")

    status = json.loads((root / "STATUS.json").read_text())
    status.update(
        {
            "config_id": config["config_id"],
            "design_frozen": True,
            "engine_build_authorized": True,
            "annual_execution_authorized": False,
            "annual_execution_2023_authorized": False,
            "annual_execution_2024_authorized": False,
            "officially_closed": False,
            "proposed_engine_version": ENGINE_VERSION,
            "proposed_schema_version": SCHEMA_VERSION,
            "status": "DESIGN_FROZEN_ENGINE_BUILD_AUTHORIZED",
            "lineage": annual["lineage"],
            "logical_dependency_lineage_id": annual["logical_lineage_id"],
            "dependency_release_anchor_tag": annual["release_anchor_tag"],
            "coherent_lineage_amendment_hash": lineage["amendment_hash"],
            "annual_dependency_registry_hash": annual["registry_hash"],
            "adapter_map_hash": adapters["adapter_map_hash"],
            "categorical_dictionary_hash": categories["dictionary_hash"],
            "value_binding_hash": bindings["binding_hash"],
            "source_semantics_evidence_hash": semantics["evidence_hash"],
            "reference_resolution_hash": resolution["resolution_hash"],
            "design_contract_audit_hash": audit["report_hash"],
        }
    )
    status["dependency_intake"] = {name: "PASS" for name in gates}
    write(root / "STATUS.json", status)

    manifest = {
        "format_version": 4,
        "status": "FROZEN",
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_id": config["config_id"],
        "lineage": annual["lineage"],
        "logical_dependency_lineage_id": annual["logical_lineage_id"],
        "dependency_release_anchor_tag": annual["release_anchor_tag"],
        "coherent_lineage_amendment_hash": lineage["amendment_hash"],
        "definition_registry_hash": definitions["registry_hash"],
        "upstream_contract_hash": contract["contract_hash"],
        "schema_sha256": schema_hash,
        "annual_dependency_registry_hash": annual["registry_hash"],
        "adapter_map_hash": adapters["adapter_map_hash"],
        "categorical_dictionary_hash": categories["dictionary_hash"],
        "value_binding_hash": bindings["binding_hash"],
        "source_semantics_evidence_hash": semantics["evidence_hash"],
        "reference_resolution_hash": resolution["resolution_hash"],
        "design_contract_audit_hash": audit["report_hash"],
        "group7_logic_source": annual["group7_logic_source"],
        "rejected_bridge_policy": "NO_UPSTREAM_ID_BRIDGE",
    }
    manifest["design_freeze_hash"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    write(root / "DESIGN_FREEZE_MANIFEST.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
