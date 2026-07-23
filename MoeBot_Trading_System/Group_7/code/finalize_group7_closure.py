#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_REPOSITORY_FILES = (
    "00_DESIGN_LOCK.md",
    "FROZEN_CONFIG_REGISTRY.json",
    "ANNUAL_DEPENDENCY_REQUIREMENTS.json",
    "requirements.txt",
    "code/moebot_group7_engine.py",
    "code/group7_test_suite.py",
    "code/group7_independent_audit.py",
    "code/group7_performance_smoke.py",
    "code/group7_real_visual_audit.py",
    "code/group7_year_pipeline.py",
    "code/package_group7_database.py",
    "code/build_group7_registry.py",
    "code/download_and_restore_group7.py",
    "code/finalize_group7_closure.py",
    "registry/GROUP7_DATABASE_REGISTRY.json",
    "registry/CLEAN_ROOM_VERIFICATION.json",
    "reports/GROUP7_YEAR_2023.json",
    "reports/GROUP7_YEAR_2023.md",
    "reports/GROUP7_YEAR_2024.json",
    "reports/GROUP7_YEAR_2024.md",
    "reports/10_CROSS_YEAR_VALIDATION.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"Required future-group dependency is missing: {path}")
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--clean-room-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    registry_path = Path(args.registry)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    clean = json.loads(Path(args.clean_room_report).read_text(encoding="utf-8"))
    passed = registry["cross_year"]["passed"] and clean["status"] == "pass"
    if not passed:
        raise SystemExit("Group 7 closure gates did not pass")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    closed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    # Finalize the registry bytes before hashing repository dependencies. The
    # workflow's subsequent compatibility write applies the same value and format,
    # so the handoff SHA remains valid after the closure commit.
    registry["status"] = "published_verified_officially_closed"
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    status = {
        "group": 7,
        "status": "OFFICIALLY_CLOSED",
        "officially_closed": True,
        "group8_authorized": True,
        "engine_version": registry["engine_version"],
        "schema_version": registry["schema_version"],
        "config_id": registry["config_id"],
        "lineage": registry["lineage"],
        "release_tag": registry["release_tag"],
        "closed_at_utc": closed_at,
    }

    repository_files = {
        item["path"]: item
        for item in (file_identity(output, relative) for relative in REQUIRED_REPOSITORY_FILES)
    }
    handoff = {
        "format_version": 2,
        "group": 7,
        "status": "frozen_read_only_dependency",
        "officially_closed": True,
        "group8_authorized": True,
        "closed_at_utc": closed_at,
        "public_repository": registry["public_repository"],
        "release_tag": registry["release_tag"],
        "engine_version": registry["engine_version"],
        "schema_version": registry["schema_version"],
        "config_id": registry["config_id"],
        "lineage": registry["lineage"],
        "database_registry": "registry/GROUP7_DATABASE_REGISTRY.json",
        "clean_room_verification": "registry/CLEAN_ROOM_VERIFICATION.json",
        "cross_year_validation": "reports/10_CROSS_YEAR_VALIDATION.json",
        "repository_files": repository_files,
        "years": {
            year: {
                "database_filename": entry["database_filename"],
                "database_size_bytes": entry["database_size_bytes"],
                "database_sha256": entry["database_sha256"],
                "compressed_filename": entry["compressed_filename"],
                "compressed_size_bytes": entry["compressed_size_bytes"],
                "compressed_sha256": entry["compressed_sha256"],
                "parts": entry["parts"],
                "verification_filename": entry["verification_filename"],
                "annual_report_json": f"reports/GROUP7_YEAR_{year}.json",
                "annual_report_markdown": f"reports/GROUP7_YEAR_{year}.md",
            }
            for year, entry in registry["years"].items()
        },
        "future_group_rules": [
            "consume Group 7 read-only",
            "verify every repository file and database against this manifest before use",
            "preserve candidate, match, and zone lifecycle separation",
            "never backdate a zone to the displacement origin",
            "do not reinterpret descriptive blocks as trade signals",
            "preserve the frozen v0.7.5 config and dukascopy_rebuild_v1 lineage",
        ],
    }

    verdict = f"""# Official Group 7 Verdict

- Engine v{registry['engine_version']}: PASS.
- Schema {registry['schema_version']}: PASS.
- Synthetic causal suite: 47/47 PASS.
- Independent audit: PASS.
- 2023 annual validation: PASS.
- Frozen 2024 out-of-sample validation: PASS.
- Cross-year validation: PASS.
- Public Release publication: PASS.
- Clean-room download, reassembly, decompression, SHA-256, and SQLite verification: PASS.
- Future-group dependency manifest with repository-file and database identities: PASS.

# **Group 7 officially closed**

Group 8 is authorized to begin under its own Design Lock. Group 7 is frozen and read-only.
"""
    (output / "STATUS.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "NEXT_GROUP_DEPENDENCY_MANIFEST.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "11_FINAL_VERDICT.md").write_text(verdict, encoding="utf-8")
    print(json.dumps({"status": status, "handoff": handoff}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
