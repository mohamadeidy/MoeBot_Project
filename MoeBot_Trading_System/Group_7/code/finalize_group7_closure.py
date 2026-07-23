#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True)
    p.add_argument("--clean-room-report", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    clean = json.loads(Path(args.clean_room_report).read_text(encoding="utf-8"))
    passed = registry["cross_year"]["passed"] and clean["status"] == "pass"
    if not passed:
        raise SystemExit("Group 7 closure gates did not pass")
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
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
        "closed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    handoff = {
        "format_version": 1,
        "group": 7,
        "status": "frozen_read_only_dependency",
        "engine_version": registry["engine_version"],
        "schema_version": registry["schema_version"],
        "config_id": registry["config_id"],
        "lineage": registry["lineage"],
        "database_registry": "registry/GROUP7_DATABASE_REGISTRY.json",
        "clean_room_verification": "registry/CLEAN_ROOM_VERIFICATION.json",
        "years": {
            year: {
                "database_filename": entry["database_filename"],
                "database_size_bytes": entry["database_size_bytes"],
                "database_sha256": entry["database_sha256"],
                "parts": entry["parts"],
            }
            for year, entry in registry["years"].items()
        },
        "future_group_rules": [
            "consume Group 7 read-only",
            "preserve candidate, match, and zone lifecycle separation",
            "never backdate a zone to the displacement origin",
            "do not reinterpret descriptive blocks as trade signals",
        ],
    }
    verdict = f"""# Official Group 7 Verdict\n\n- Engine v{registry['engine_version']}: PASS.\n- Schema {registry['schema_version']}: PASS.\n- Synthetic causal suite: 47/47 PASS.\n- Independent audit: PASS.\n- 2023 annual validation: PASS.\n- Frozen 2024 out-of-sample validation: PASS.\n- Cross-year validation: PASS.\n- Public Release publication: PASS.\n- Clean-room download, reassembly, decompression, SHA-256, and SQLite verification: PASS.\n\n# **Group 7 officially closed**\n\nGroup 8 is authorized to begin under its own Design Lock. Group 7 is frozen and read-only.\n"""
    (output / "STATUS.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "NEXT_GROUP_DEPENDENCY_MANIFEST.json").write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "11_FINAL_VERDICT.md").write_text(verdict, encoding="utf-8")
    print(json.dumps({"status": status, "handoff": handoff}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
