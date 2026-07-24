#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_SOURCES = {
    "group2": {
        "filename": "moebot_group2_engine_v0_2_1.py",
        "sha256": "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926",
        "version": "0.2.1",
        "schema_version": "2.1.0",
    },
    "group3": {
        "filename": "moebot_group3_structure_engine_v0_1_1.py",
        "sha256": "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512",
        "version": "0.1.1",
        "schema_version": "3.0.0",
    },
    "group4": {
        "filename": "moebot_group4_zones_engine_v0_1_6.py",
        "sha256": "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad",
        "version": "0.1.6",
        "schema_version": "4.5.0",
    },
    "group5": {
        "filename": "moebot_group5_liquidity_engine_v0_1_6.py",
        "sha256": "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc",
        "version": "0.1.6",
        "schema_version": "5.1.0",
    },
    "group6": {
        "filename": "moebot_group6_engine.py",
        "sha256": "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877",
        "version": "0.6.4",
        "schema_version": "6.35.0",
    },
}

CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[`\"\[])?([A-Za-z_][A-Za-z0-9_]*)(?:[`\"\]])?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[`\"\[])?([A-Za-z_][A-Za-z0-9_]*)(?:[`\"\]])?\s+ON\s+(?:[`\"\[])?([A-Za-z_][A-Za-z0-9_]*)(?:[`\"\]])?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def split_sql_items(body: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(body):
        char = body[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    current.append(body[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"', "`"):
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)
        index += 1
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def parse_column(item: str) -> dict[str, Any] | None:
    compact = " ".join(item.replace("\n", " ").split())
    upper = compact.upper()
    if upper.startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "CONSTRAINT")):
        return None
    match = re.match(r"^[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)[`\"\]]?\s*(.*)$", compact)
    if not match:
        return None
    name, definition = match.groups()
    type_match = re.match(r"([A-Za-z0-9_]+(?:\s*\([^)]*\))?)", definition)
    declared_type = type_match.group(1).strip().upper() if type_match else ""
    return {
        "name": name,
        "declared_type": declared_type,
        "not_null": "NOT NULL" in upper,
        "primary_key_inline": "PRIMARY KEY" in upper,
        "unique_inline": "UNIQUE" in upper,
        "default_present": " DEFAULT " in f" {upper} ",
        "definition": compact,
    }


def extract_schema(source_text: str) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for match in CREATE_TABLE_RE.finditer(source_text):
        table_name = match.group(1)
        body = match.group(2)
        columns = []
        table_constraints = []
        for item in split_sql_items(body):
            parsed = parse_column(item)
            if parsed is None:
                table_constraints.append(" ".join(item.replace("\n", " ").split()))
            else:
                columns.append(parsed)
        normalized = {
            "table": table_name,
            "columns": columns,
            "table_constraints": table_constraints,
        }
        normalized["schema_hash"] = hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()
        existing = tables.get(table_name)
        if existing is not None and existing["schema_hash"] != normalized["schema_hash"]:
            raise ValueError(f"Conflicting CREATE TABLE definitions for {table_name}")
        tables[table_name] = normalized

    indexes = []
    for match in CREATE_INDEX_RE.finditer(source_text):
        index_name, table_name, body = match.groups()
        indexes.append(
            {
                "index": index_name,
                "table": table_name,
                "columns_or_expression": " ".join(body.replace("\n", " ").split()),
            }
        )
    indexes.sort(key=lambda item: (item["table"], item["index"]))
    return {
        "tables": dict(sorted(tables.items())),
        "indexes": indexes,
    }


def find_unique(root: Path, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one {filename}, found: {matches}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restored-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = args.restored_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Restored root does not exist: {root}")

    sources: dict[str, Any] = {}
    failures: list[str] = []
    for group, expected in EXPECTED_SOURCES.items():
        path = find_unique(root, expected["filename"])
        actual_sha = sha256_file(path)
        if actual_sha != expected["sha256"]:
            failures.append(f"sha256:{group}:{actual_sha}")
        text = path.read_text(encoding="utf-8")
        schema = extract_schema(text)
        source_record = {
            "filename": expected["filename"],
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": actual_sha,
            "expected_sha256": expected["sha256"],
            "sha256_pass": actual_sha == expected["sha256"],
            "version": expected["version"],
            "schema_version": expected["schema_version"],
            "table_count": len(schema["tables"]),
            "index_count": len(schema["indexes"]),
            "tables": schema["tables"],
            "indexes": schema["indexes"],
        }
        source_record["inventory_hash"] = hashlib.sha256(canonical_json(source_record).encode("utf-8")).hexdigest()
        sources[group] = source_record

    report = {
        "format_version": 1,
        "status": "pass" if not failures else "fail",
        "bundle_sha256": "174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf",
        "source_identity_failures": failures,
        "sources": sources,
        "limitations": [
            "This inventory extracts static CREATE TABLE and CREATE INDEX statements from exact frozen runtime sources.",
            "Final Group 8 adapters must also be checked against PRAGMA table_info, foreign_key_list and index_list on the real annual SQLite dependencies before engine build.",
        ],
    }
    report["report_hash"] = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report_hash": report["report_hash"]}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
