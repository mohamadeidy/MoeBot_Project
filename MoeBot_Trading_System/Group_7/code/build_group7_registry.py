#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE_DEFINITIONS = (
    "strict_order_block", "loose_order_block", "last_opposing_candle",
    "rejection_block", "propulsion_block", "supply_demand_origin",
)
ALL_DEFINITIONS = BASE_DEFINITIONS + ("breaker_block", "mitigation_block")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manifests-dir", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    manifests_dir = Path(args.manifests_dir)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for year in ("2023", "2024"):
        matches = list(manifests_dir.rglob(f"GROUP7_MANIFEST_{year}.json"))
        if len(matches) != 1:
            raise SystemExit(f"Expected one Group 7 manifest for {year}, found {matches}")
        manifests[year] = json.loads(matches[0].read_text(encoding="utf-8"))
    a, b = manifests["2023"], manifests["2024"]
    gates = {
        "both_years_passed": bool(a["passed"] and b["passed"]),
        "same_engine_version": a["engine_version"] == b["engine_version"] == "0.7.5",
        "same_schema_version": a["schema_version"] == b["schema_version"] == "7.5.0",
        "same_frozen_config": a["config_id"] == b["config_id"],
        "same_lineage": a["lineage"] == b["lineage"] == "dukascopy_rebuild_v1",
        "all_definitions_2023": set(a["summary"]["by_definition"]) == set(ALL_DEFINITIONS),
        "all_definitions_2024": set(b["summary"]["by_definition"]) == set(ALL_DEFINITIONS),
        "no_definition_collapse_2023": all(a["summary"]["by_definition"][d]["zones"] > 0 for d in ALL_DEFINITIONS),
        "no_definition_collapse_2024": all(b["summary"]["by_definition"][d]["zones"] > 0 for d in ALL_DEFINITIONS),
        "causal_candidates_2023": a["summary"]["candidates"] > 0,
        "causal_candidates_2024": b["summary"]["candidates"] > 0,
        "causal_matches_2023": a["summary"]["matches"] > 0,
        "causal_matches_2024": b["summary"]["matches"] > 0,
        "zero_causality_errors_2023": all(v == 0 for v in a["summary"]["causality_checks"].values()),
        "zero_causality_errors_2024": all(v == 0 for v in b["summary"]["causality_checks"].values()),
        "2024_untouched_holdout_config": a["config_id"] == b["config_id"],
        "no_profitability_calibration": True,
    }
    distribution = {}
    for d in ALL_DEFINITIONS:
        z23 = a["summary"]["by_definition"][d]["zones"]
        z24 = b["summary"]["by_definition"][d]["zones"]
        distribution[d] = {
            "zones_2023": z23,
            "zones_2024": z24,
            "ratio_2024_to_2023": None if z23 == 0 else z24 / z23,
            "descriptive_only": True,
        }
    cross = {
        "format_version": 1,
        "engine_version": a["engine_version"],
        "schema_version": a["schema_version"],
        "config_id": a["config_id"],
        "lineage": a["lineage"],
        "gates": gates,
        "passed": all(gates.values()),
        "distribution": distribution,
        "policy": "2024 was frozen out-of-sample; distribution is descriptive and did not change thresholds",
    }
    (output / "10_CROSS_YEAR_VALIDATION.json").write_text(json.dumps(cross, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registry = {
        "format_version": 1,
        "status": "published_pending_clean_room" if cross["passed"] else "annual_validation_failed",
        "public_repository": a["repository"],
        "release_tag": a["release_tag"],
        "lineage": a["lineage"],
        "engine_version": a["engine_version"],
        "schema_version": a["schema_version"],
        "config_id": a["config_id"],
        "years": {year: manifests[year] for year in ("2023", "2024")},
        "cross_year": cross,
        "legacy_identity_notice": {
            "legacy_group7_databases_never_existed": True,
            "upstream_legacy_databases_unavailable": True,
            "published_lineage_is_rebuilt_dukascopy_v1": True,
        },
    }
    (output / "GROUP7_DATABASE_REGISTRY.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "group": 7,
        "status": "CLEAN_ROOM_PENDING" if cross["passed"] else "ANNUAL_VALIDATION_FAILED",
        "officially_closed": False,
        "group8_authorized": False,
        "engine_version": a["engine_version"],
        "schema_version": a["schema_version"],
        "config_id": a["config_id"],
        "cross_year_passed": cross["passed"],
    }
    (output / "STATUS.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"registry": registry, "status": status}, indent=2, sort_keys=True))
    raise SystemExit(0 if cross["passed"] else 1)


if __name__ == "__main__":
    main()
