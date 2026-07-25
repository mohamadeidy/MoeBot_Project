#!/usr/bin/env python3
"""Narrow runtime bootstrap for the coherent Group 7 visual-audit wrapper only.

This does not alter any frozen Group 7 source or research rule. It installs the
external plotting dependency only when the coherent annual wrapper starts and
matplotlib is absent from the GitHub Actions runner.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

if Path(sys.argv[0]).name == "group8_build_coherent_v3_year.py" and importlib.util.find_spec("matplotlib") is None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "matplotlib",
        ],
        check=True,
    )
