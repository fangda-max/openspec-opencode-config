#!/usr/bin/env python3
"""Run the repository entropy audit with CLI fallback."""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import subprocess
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "entropy.config.toml").is_file():
            return candidate
    return current


def cli_prefix(project_root: Path) -> list[str]:
    if shutil.which("entropy_audit"):
        return ["entropy_audit"]
    if shutil.which("entropy-audit"):
        return ["entropy-audit"]
    if (project_root / "entropy_audit" / "cli.py").is_file():
        return [sys.executable, "-m", "entropy_audit.cli"]
    raise SystemExit(
        "Cannot find entropy_audit CLI. Install the package or run from a repository "
        "containing entropy_audit/."
    )


def main() -> int:
    today_period = _dt.date.today().strftime("%Y-%m")
    parser = argparse.ArgumentParser(description="Run entropy_audit with sensible defaults.")
    parser.add_argument("--project-root", default=".", help="Project root or any child path.")
    parser.add_argument("--period", default=today_period, help="Report period, e.g. 2026-04.")
    parser.add_argument("--mode", default="monthly", choices=["monthly", "quarterly"])
    parser.add_argument("--config", default="entropy.config.toml")
    parser.add_argument("--calibration", default="entropy.calibration.toml")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    root = find_project_root(Path(args.project_root))
    out_dir = args.out_dir or str(Path("reports") / args.period)
    prefix = cli_prefix(root)

    command = [
        *prefix,
        "run",
        "--project-root",
        ".",
        "--config",
        args.config,
        "--calibration",
        args.calibration,
        "--period",
        args.period,
        "--mode",
        args.mode,
        "--out-dir",
        out_dir,
    ]

    print("Running:", " ".join(command))
    completed = subprocess.run(command, cwd=root)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
