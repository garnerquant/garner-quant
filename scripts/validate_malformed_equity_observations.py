"""Validate fail-closed malformed-equity diagnostics and safety boundaries."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv",
             "broker_account.csv", "paper_30_day_tracker.csv", "trade_transactions_v1.csv")


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED}


def main():
    before = hashes()
    result = subprocess.run([sys.executable, "-m", "unittest",
                             "tests.test_malformed_equity_observations", "-q"], cwd=ROOT)
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    checks = {
        "focused malformed-equity tests": result.returncode == 0,
        "monitor_only": config.get("mode") == "monitor_only",
        "paper execution disabled": config.get("paper_execution_enabled") is False,
        "live execution disabled": config.get("live_execution_enabled", False) is False,
        "canonical accounting inactive": config.get("canonical_accounting_enabled", False) is False,
        "no accounting pointer": not (ROOT / "data/accounting_generations/accounting_generation.json").exists(),
        "protected files unchanged": hashes() == before,
    }
    for label, passed in checks.items():
        print(("PASS" if passed else "FAIL") + ": " + label)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
