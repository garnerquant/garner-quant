"""Validate the read-only Research page information architecture."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run([sys.executable, "-m", "unittest",
                             "tests.test_research_dashboard_presentation", "-q"], cwd=ROOT)
    status = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True).stdout
    changed = tuple(line[3:].replace("\\", "/") for line in status.splitlines() if len(line) > 3)
    forbidden = ("research/", "research/scanner_v2/", "runtime/", "execution/", "canonical_accounting/")
    checks = {
        "focused research presentation tests": result.returncode == 0,
        "no scanner, generation, publication, runtime, execution, or accounting changes":
            not any(path.startswith(forbidden) for path in changed),
    }
    for label, passed in checks.items(): print(("PASS" if passed else "FAIL") + ": " + label)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__": raise SystemExit(main())
