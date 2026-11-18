#!/usr/bin/env python3
"""Fail-closed Group 9 mandatory-evidence presence gate (read-only).

This is a necessary-condition check before production annual materialization,
not a proof of causal linkage, producer absence, or permission to run the year.
Only checks the frozen Group 9 required support definitions in the previously
built Group 8 Stage5/Stage7 support index. All sources remain immutable.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from group9_real_root_inventory import atomic_json, load_hashed, stable


def required_paths(family: dict) -> dict[str, list[tuple[str, list[str]]]]:
    """Per root definition, each required role has a disjunction of definitions."""
    out = {}
    for root_def in family["root_definitions"]:
        roles = []
        for requirement in family["ready_requirements"]:
            names = requirement.get("one_of")
            if names is None:
                names = requirement["by_root"].get(root_def)
            if not names:
                raise ValueError("missing_requirement_for_root:" + root_def)
            roles.append((str(requirement["role"]), list(names)))
        out[root_def] = roles
    return out


def compute(inventory: dict, benchmark: dict, registry: dict,
            counts: dict[tuple[int, str], int], years: tuple[int, ...]) -> dict:
    if registry["status"] != "FROZEN":
        raise ValueError("registry_not_frozen")
    if registry["registry_hash"] != benchmark["semantic_registry_hash"]:
        raise ValueError("definition_registry_benchmark_drift")
    if inventory["report_hash"] != benchmark["inventory_report_hash"]:
        raise ValueError("inventory_benchmark_drift")
    if sum(benchmark["sample"]["allocations"][i]["population"]
           for i in range(len(benchmark["sample"]["allocations"]))) != inventory["candidate_count"]:
        raise ValueError("allocation_population_mismatch")
    if any(benchmark.get(x) for x in ("outcome_data_accessed", "trade_policy_accessed")):
        raise ValueError("outcome_or_trade_policy_in_coverage")
    allocation = {
        (int(x["year"]), str(x["family"])): int(x["population"])
        for x in benchmark["sample"]["allocations"]
    }
    failures = []
    family_checks = []
    for year in years:
        for family_name, family in registry["setup_families"].items():
            population = allocation.get((year, family_name), 0)
            if population < 1:
                continue
            paths = required_paths(family)
            root_type_counts = {}
            # For multiple root defs, an actual scope-def count is necessary.
            # Inventory aggregate can only resolve per-def by year when family
            # has no roots in the other year (the current Wyckoff layout).
            if len(paths) == 1:
                root_type_counts[next(iter(paths))] = population
            else:
                other_years = [x for x in years if x != year and
                               allocation.get((x, family_name), 0)]
                if other_years:
                    raise ValueError("per_year_root_definition_counts_required:" + family_name)
                for root_def in paths:
                    root_type_counts[root_def] = int(
                        inventory["counts_by_definition"].get(root_def, 0)
                    )
                if sum(root_type_counts.values()) != population:
                    raise ValueError("root_definition_population_mismatch:" + family_name)
            for root_def, n_roots in root_type_counts.items():
                if n_roots == 0:
                    continue
                roles = []
                for role, definitions in paths[root_def]:
                    evidence = {name: int(counts.get((year, name), 0))
                                for name in definitions}
                    present = any(v > 0 for v in evidence.values())
                    item = {"role": role, "definitions": evidence, "definition_present": present}
                    roles.append(item)
                    if not present:
                        failures.append({
                            "year": year,
                            "family": family_name,
                            "root_definition": root_def,
                            "root_population": n_roots,
                            "missing_mandatory_role": role,
                            "required_definitions": definitions,
                        })
                family_checks.append({
                    "year": year, "family": family_name, "root_definition": root_def,
                    "root_population": n_roots, "roles": roles,
                    "all_required_definitions_present": all(x["definition_present"] for x in roles),
                })
    if not family_checks:
        raise ValueError("empty_family_coverage")
    result = {
        "format_version": 1,
        "scope": "G9_REQUIRED_DEFINITION_PRESENCE_FROM_EXISTING_FULL_SUPPORT_INDEX",
        "status": "BLOCKED_REQUIRED_DEFINITION_ABSENT" if failures else "PRESENCE_ONLY_PASS",
        "registry_hash": registry["registry_hash"],
        "inventory_report_hash": inventory["report_hash"],
        "benchmark_report_hash": benchmark["report_hash"],
        "all_family_roots": sum(x["root_population"] for x in family_checks),
        "yearly_support_definition_counts": {
            str(year): {definition: int(n)
                        for (y, definition), n in sorted(counts.items()) if y == year}
            for year in years
        },
        "family_checks": family_checks,
        "failures": failures,
        "provenance_limitation": (
            "A zero count means absent from the benchmark-built support index, "
            "NOT proven absent from every frozen Group 8 derived or release artifact."
        ),
        "presence_not_sufficient_for_causal_linkage": True,
        "full_production_support_coverage_verified": False,
        "real_annual_execution_authorized": False,
        "upstream_read_only": True,
        "outcome_data_accessed": False,
        "trade_policy_accessed": False,
    }
    result["report_hash"] = stable(result)
    return result


def gather_counts(index: Path, registry: dict, years: tuple[int, ...]) -> dict:
    if not index.exists():
        raise FileNotFoundError(index)
    definitions = set()
    for f in registry["setup_families"].values():
        for roles in required_paths(f).values():
            for _, ds in roles:
                definitions.update(ds)
    counts = {}
    with closing(sqlite3.connect(index.resolve().as_uri() + "?mode=ro&immutable=1",
                                 uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        for year in years:
            for definition in sorted(definitions):
                n = con.execute(
                    "SELECT COUNT(*) FROM subject WHERE dataset_year=? AND definition_id=?",
                    (year, definition)
                ).fetchone()[0]
                counts[(year, definition)] = int(n)
    return counts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--benchmark", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--support-index", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    inv = load_hashed(a.inventory)
    bench = load_hashed(a.benchmark)
    defs = load_hashed(a.registry, ("registry_hash",))
    if a.support_index.stat().st_size != int(bench["support_index_bytes"]):
        raise ValueError("support_index_size_drift")
    years = (2023, 2024)
    counts = gather_counts(a.support_index, defs, years)
    result = compute(inv, bench, defs, counts, years)
    if a.report.exists():
        raise FileExistsError("coverage_gate_report_already_exists")
    atomic_json(a.report, result)
    print(json.dumps({
        "status": result["status"],
        "checked_root_population": result["all_family_roots"],
        "definition_role_gaps": len(result["failures"]),
        "failures": result["failures"],
        "full_production_support_coverage_verified": False,
        "real_annual_execution_authorized": False,
        "report": str(a.report),
    }, indent=2))
    # Exit 2 is a valid fail-closed diagnostic, not a script crash.
    return 0 if not result["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
