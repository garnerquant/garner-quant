from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validate_accounting_reconciliation as reconciliation


PRODUCTION_REPORT = ROOT / "data" / "accounting_reconciliation_report.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def main():
    issues = []
    before = digest(PRODUCTION_REPORT)
    exit_code = reconciliation.main([])
    after = digest(PRODUCTION_REPORT)
    check(exit_code == 0, "read-only reconciliation succeeds", issues)
    check(before == after, "default validation leaves the production report byte-identical", issues)

    scratch = ROOT / ".tmp" / "accounting-reconciliation-output-validation"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    try:
        report = scratch / "reconciliation.json"
        explicit_exit = reconciliation.main(["--report-file", str(report)])
        check(explicit_exit == 0 and report.is_file(), "explicit report generation succeeds", issues)
        payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
        check(
            "expected_ledger_cash" in payload and "issues" in payload,
            "explicit report retains the reconciliation contract",
            issues,
        )
        check(before == digest(PRODUCTION_REPORT), "explicit isolated output does not touch production report", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if issues:
        print(f"Accounting reconciliation output validation failed: {len(issues)} issue(s)")
        return 1
    print("Accounting reconciliation output validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
