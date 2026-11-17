#!/usr/bin/env python3
"""Read-only Group 9 evidence-coverage release gate (no semantic changes)."""
from __future__ import annotations
import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

REQUIRED_WYCKOFF = (
    "wyckoff_sign_of_strength",
    "wyckoff_sign_of_weakness",
    "wyckoff_last_point_of_support",
    "wyckoff_last_point_of_supply",
)
WYCKOFF_ROOTS = ("wyckoff_spring_candidate", "wyckoff_upthrust_candidate")


def read_only_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def count_release(release: Path) -> dict:
    rec = json.loads(release.read_text(encoding="utf-8"))
    if rec.get("status") != "PASS" or int(rec.get("stage", 0)) != 6:
        raise ValueError(f"unapproved_stage6_release:{release}")
    counts: Counter[str] = Counter()
    for shard in rec["shards"]:
        path = Path(shard["database"])
        with closing(read_only_db(path)) as con:
            counts.update(dict(con.execute(
                "SELECT definition_id,COUNT(*) FROM school_interpretation GROUP BY definition_id"
            )))
    expected = sum(int(x["table_row_counts"]["school_interpretation"]) for x in rec["shards"])
    if sum(counts.values()) != expected:
        raise ValueError(f"stage6_count_mismatch:{release}")
    return {
        "year": int(rec["year"]),
        "shards_checked": len(rec["shards"]),
        "interpretations": sum(counts.values()),
        "root_count": sum(counts[d] for d in WYCKOFF_ROOTS),
        "required_support": {d: counts[d] for d in REQUIRED_WYCKOFF},
    }


def audit(releases: list[Path], support_index: Path, sample_output: Path) -> dict:
    years = [count_release(p) for p in releases]
    if len(set(y["year"] for y in years)) != len(years):
        raise ValueError("duplicate_year")
    with closing(read_only_db(support_index)) as con:
        # Use the verified dataset_year prefix of ix_subject_def: avoid four full
        # scans over the multi-GB index (definition_id alone is not indexed).
        support = {d: sum(int(con.execute(
            "SELECT COUNT(*) FROM subject WHERE dataset_year=? AND definition_id=?",
            (year["year"], d),
        ).fetchone()[0]) for year in years) for d in REQUIRED_WYCKOFF}
    with closing(read_only_db(sample_output)) as con:
        sample = {str(k): int(v) for k, v in con.execute(
            "SELECT current_state,COUNT(*) FROM setup_instance "
            "WHERE setup_family='G9_WYCKOFF_RANGE_RESOLUTION' GROUP BY current_state"
        )}
    roots = sum(y["root_count"] for y in years)
    support_missing = [d for d in REQUIRED_WYCKOFF if support[d] == 0]
    return {
        "scope": "GROUP9_WYCKOFF_UPSTREAM_COVERAGE_READ_ONLY",
        "status": "BLOCKED_MANDATORY_SUPPORT_ABSENT" if roots and support_missing else "REVIEW_REQUIRED",
        "stage6_years": years,
        "support_index_required_definitions": support,
        "missing_required_definitions": support_missing,
        "wyckoff_sample_states": sample,
        "annual_execution_authorized": False,
        "note": "Zero records do not establish a Group 8 bug; verify frozen PA7 derived coverage. No rule relaxation or output reconstruction is authorized.",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stage6-release", type=Path, action="append", required=True)
    p.add_argument("--support-index", type=Path, required=True)
    p.add_argument("--sample-output", type=Path, required=True)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    result = audit(args.stage6_release, args.support_index, args.sample_output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
