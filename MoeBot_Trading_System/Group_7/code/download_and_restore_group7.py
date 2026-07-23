#!/usr/bin/env python3
"""Restore published Group 7 SQLite databases with strict identity and integrity gates."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RESTORE_VERSION = "1.1-resumable-long-window"
ACCEPTED_REGISTRY_STATES = {
    "published_pending_clean_room",
    "published_verified_officially_closed",
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry(location: str) -> dict[str, Any]:
    path = Path(location)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    headers = {"User-Agent": f"MoeBot-Group7-Restore/{RESTORE_VERSION}"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in location:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(location, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def curl_download(url: str, partial: Path) -> None:
    curl = shutil.which("curl")
    if not curl:
        raise FileNotFoundError("curl is unavailable")
    subprocess.run(
        [
            curl,
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry", "8",
            "--retry-all-errors",
            "--retry-delay", "2",
            "--connect-timeout", "30",
            "--speed-time", "120",
            "--speed-limit", "1024",
            "--continue-at", "-",
            "--output", str(partial),
            "--user-agent", f"MoeBot-Group7-Restore/{RESTORE_VERSION}",
            url,
        ],
        check=True,
    )


def urllib_download(url: str, partial: Path) -> None:
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {
        "User-Agent": f"MoeBot-Group7-Restore/{RESTORE_VERSION}",
        "Accept": "application/octet-stream",
    }
    if existing:
        headers["Range"] = f"bytes={existing}-"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    mode = "ab" if existing else "wb"
    with urllib.request.urlopen(request, timeout=600) as response, partial.open(mode) as output:
        shutil.copyfileobj(response, output, length=8 * 1024 * 1024)


def download_verified(url: str, destination: Path, expected_size: int, expected_sha256: str, attempts: int = 6) -> None:
    if (
        destination.is_file()
        and destination.stat().st_size == expected_size
        and sha256_file(destination) == expected_sha256
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".tmp")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if shutil.which("curl"):
                curl_download(url, partial)
            else:
                urllib_download(url, partial)
            actual_size = partial.stat().st_size
            actual_sha = sha256_file(partial)
            if actual_size != expected_size or actual_sha != expected_sha256:
                partial.unlink(missing_ok=True)
                raise RuntimeError(
                    "Release part identity mismatch: "
                    f"size={actual_size}/{expected_size}, sha256={actual_sha}/{expected_sha256}, url={url}"
                )
            partial.replace(destination)
            return
        except (
            OSError,
            RuntimeError,
            subprocess.CalledProcessError,
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.HTTPException,
        ) as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = min(2 ** attempt, 30)
            print(
                f"Download attempt {attempt}/{attempts} failed for {url}: {exc}; "
                f"retrying in {delay}s from {partial.stat().st_size if partial.exists() else 0} bytes",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"Unable to restore verified Release part: {url}: {last_error}")


def sqlite_verify(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    quick = connection.execute("PRAGMA quick_check").fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    if quick != "ok" or integrity != "ok" or foreign_key_errors:
        raise RuntimeError(
            f"SQLite verification failed for {path}: quick={quick}, "
            f"integrity={integrity}, foreign_key_errors={foreign_key_errors}"
        )
    return {
        "quick_check": quick,
        "integrity_check": integrity,
        "foreign_key_errors": foreign_key_errors,
    }


def restore_year(year: str, entry: dict[str, Any], download_root: Path, output_root: Path) -> dict[str, Any]:
    year_downloads = download_root / year
    year_downloads.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    for part in entry["parts"]:
        destination = year_downloads / part["filename"]
        download_verified(
            part["url"],
            destination,
            int(part["size_bytes"]),
            part["sha256"],
        )
        part_paths.append(destination)

    compressed = year_downloads / entry["compressed_filename"]
    with compressed.open("wb") as output:
        for part_path in part_paths:
            with part_path.open("rb") as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    compressed_size = compressed.stat().st_size
    compressed_sha = sha256_file(compressed)
    if (
        compressed_size != int(entry["compressed_size_bytes"])
        or compressed_sha != entry["compressed_sha256"]
    ):
        raise RuntimeError(
            f"Compressed stream identity mismatch for {year}: "
            f"size={compressed_size}/{entry['compressed_size_bytes']}, "
            f"sha256={compressed_sha}/{entry['compressed_sha256']}"
        )

    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd executable is required")
    output_root.mkdir(parents=True, exist_ok=True)
    database = output_root / entry["database_filename"]
    subprocess.run(
        [zstd, "-d", "--long=31", "-f", str(compressed), "-o", str(database)],
        check=True,
    )
    database_size = database.stat().st_size
    database_sha = sha256_file(database)
    if (
        database_size != int(entry["database_size_bytes"])
        or database_sha != entry["database_sha256"]
    ):
        raise RuntimeError(
            f"Database identity mismatch for {year}: "
            f"size={database_size}/{entry['database_size_bytes']}, "
            f"sha256={database_sha}/{entry['database_sha256']}"
        )
    sqlite_checks = sqlite_verify(database)
    return {
        "path": str(database.resolve()),
        "filename": database.name,
        "size_bytes": database_size,
        "sha256": database_sha,
        **sqlite_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--year", choices=("2023", "2024", "both"), default="both")
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    registry = load_registry(args.registry)
    if registry.get("status") not in ACCEPTED_REGISTRY_STATES:
        raise SystemExit(f"Group 7 registry is not restorable: {registry.get('status')}")
    years = ("2023", "2024") if args.year == "both" else (args.year,)
    download_root = Path(args.download_dir)
    output_root = Path(args.output_dir)
    restored = {
        year: restore_year(year, registry["years"][year], download_root, output_root)
        for year in years
    }
    print(
        json.dumps(
            {
                "status": "pass",
                "restore_version": RESTORE_VERSION,
                "restored": restored,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
