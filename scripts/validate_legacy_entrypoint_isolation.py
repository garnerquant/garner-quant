from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.legacy_isolation import LegacyExecutionError  # noqa: E402
from execution.paper_trader import (  # noqa: E402
    load_portfolio,
    paper_trade,
    save_portfolio,
    send_telegram_alert,
)


PRODUCTION_FILES = [
    "broker_account.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
    "trade_transactions_v1.csv",
    "trade_snapshots.csv",
    "trade_ledger_v1.csv",
    "holdings_report.csv",
    "portfolio_v2.csv",
    "paper_30_day_tracker.csv",
    "data/notification_state.json",
    "data/market_intelligence.json",
]

LEGACY_OUTPUT_FILES = [
    "prices.csv",
    "signals.csv",
    "weights.csv",
    "risk_levels.csv",
    "portfolio.csv",
    "signal_report.csv",
    "paper_portfolio.csv",
]


def digest(path):
    path = Path(path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(paths):
    return {str(path): digest(ROOT / path) for path in paths}


def unchanged(before, paths):
    return before == snapshot(paths)


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def main_py_refuses_without_flag():
    before = snapshot(PRODUCTION_FILES + LEGACY_OUTPUT_FILES)
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = result.stdout + result.stderr
    return (
        result.returncode != 0
        and "deprecated legacy execution path" in output
        and unchanged(before, PRODUCTION_FILES + LEGACY_OUTPUT_FILES)
    )


def paper_trader_refuses_default_writes():
    before = snapshot(PRODUCTION_FILES + LEGACY_OUTPUT_FILES)
    calls = [
        lambda: load_portfolio(),
        lambda: save_portfolio(pd.DataFrame([{"ticker": "TEST", "entry_price": 1.0}])),
        lambda: send_telegram_alert("test"),
        lambda: paper_trade(
            pd.DataFrame({"TEST": [1]}, index=pd.to_datetime(["2026-01-01"])),
            pd.DataFrame({"TEST": [1.0]}, index=pd.to_datetime(["2026-01-01"])),
        ),
    ]
    refused = 0
    for call in calls:
        try:
            call()
        except LegacyExecutionError:
            refused += 1
    return refused == len(calls) and unchanged(before, PRODUCTION_FILES + LEGACY_OUTPUT_FILES)


def paper_trader_sandbox_writes_only_to_sandbox():
    sandbox = ROOT / "data" / "legacy_sandbox_validation"
    output = sandbox / "paper_portfolio.csv"
    output.unlink(missing_ok=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    before = snapshot(PRODUCTION_FILES + LEGACY_OUTPUT_FILES)

    signals = pd.DataFrame(
        {"TEST": [1]},
        index=pd.to_datetime(["2026-01-01"]),
    )
    prices = pd.DataFrame(
        {"TEST": [12.34]},
        index=pd.to_datetime(["2026-01-01"]),
    )
    trades, portfolio = paper_trade(
        signals,
        prices,
        legacy_mode=True,
        sandbox_dir=sandbox,
    )
    try:
        return (
            output.exists()
            and len(trades) == 1
            and len(portfolio) == 1
            and unchanged(before, PRODUCTION_FILES + LEGACY_OUTPUT_FILES)
        )
    finally:
        output.unlink(missing_ok=True)


def main_py_has_sandbox_gate():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    return (
        "--legacy-sandbox" in source
        and "require_legacy_sandbox" in source
        and "legacy_sandbox" in source
    )


def paper_trader_has_sandbox_gate():
    source = (ROOT / "execution" / "paper_trader.py").read_text(encoding="utf-8")
    return (
        "require_legacy_sandbox" in source
        and "legacy_sandbox" in source
        and "notify_plain_message" not in source
    )


def main():
    issues = []
    check(main_py_has_sandbox_gate(), "main.py has explicit legacy sandbox gate", issues)
    check(
        paper_trader_has_sandbox_gate(),
        "execution.paper_trader has explicit legacy sandbox gate",
        issues,
    )
    check(
        main_py_refuses_without_flag(),
        "main.py refuses without mutating production or legacy root files",
        issues,
    )
    check(
        paper_trader_refuses_default_writes(),
        "paper_trader default helpers refuse without mutating state",
        issues,
    )
    check(
        paper_trader_sandbox_writes_only_to_sandbox(),
        "paper_trader sandbox mode writes only to sandbox",
        issues,
    )

    if issues:
        print("\nLegacy entrypoint isolation validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nLegacy entrypoint isolation validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
