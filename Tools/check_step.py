"""
Tools/check_step.py
Per-step gate: runs the i18n lint, prints coverage, then runs the test
suite. Designed to be invoked after every translation step so issues are
caught before commit.

Exit codes:
    0  all green — safe to commit
    2  i18n_lint failed (catalog or t() reference error)
    3  pytest failed (regression)

Usage:
    python Tools/check_step.py
    python Tools/check_step.py --fast        # skip pytest (lint + coverage only)
    python Tools/check_step.py --pytest-args="-k splash"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(label: str, cmd: list[str]) -> int:
    print(f"\n{'=' * 60}\n  {label}\n{'=' * 60}")
    proc = subprocess.run(cmd, cwd=REPO_ROOT)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip pytest (lint + coverage only). Useful mid-edit.",
    )
    parser.add_argument(
        "--pytest-args",
        default="-q",
        help="Extra arguments forwarded to pytest (default: '-q').",
    )
    args = parser.parse_args()

    # 1. i18n lint — must pass
    rc = run("i18n_lint", [PYTHON, "Tools/i18n_lint.py"])
    if rc != 0:
        print("\n❌ i18n_lint failed — fix before committing.", file=sys.stderr)
        return 2

    # 2. coverage — informational, never fails
    run("i18n_coverage", [PYTHON, "Tools/i18n_coverage.py"])

    # 3. pytest — must pass unless --fast
    if not args.fast:
        pytest_argv = args.pytest_args.split() if args.pytest_args else []
        rc = run("pytest", [PYTHON, "-m", "pytest"] + pytest_argv)
        if rc != 0:
            print("\n❌ pytest failed — fix before committing.", file=sys.stderr)
            return 3

    print("\n✅ check_step: all green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
