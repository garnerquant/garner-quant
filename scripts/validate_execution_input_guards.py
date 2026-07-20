from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import ledger_accounting
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import (
    TradeLedgerError,
    normalise_trade_event,
    prepare_trade_ledger_append,
)
from runtime.live_runtime import paper_execution_blocked_reason


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def event(**overrides):
    values = {
        "timestamp": "2026-07-20T12:00:00+00:00",
        "ticker": "ABC",
        "action": "BUY",
        "shares": 1.0,
        "price": 10.0,
        "value": 10.0,
        "fees": 0.0,
        "currency": "GBP",
        "source": "fixture",
        "mode": "paper",
        "status": "RECORDED",
    }
    values.update(overrides)
    return values


def refused(values):
    try:
        normalise_trade_event(values)
    except TradeLedgerError:
        return True
    return False


def main():
    issues = []
    for field, value in (
        ("shares", 0),
        ("shares", -1),
        ("price", 0),
        ("price", -1),
        ("value", 0),
        ("value", -1),
    ):
        check(
            refused(event(**{field: value})),
            f"invalid {field}={value} is refused",
            issues,
        )

    duplicate = normalise_trade_event(event())
    ledger_path = ROOT / ".tmp" / "nonexistent-input-guard-ledger.csv"
    try:
        prepare_trade_ledger_append(
            [duplicate, duplicate],
            path=ledger_path,
        )
        duplicate_refused = False
    except TradeLedgerError:
        duplicate_refused = True
    check(
        duplicate_refused,
        "duplicate events in one append are refused",
        issues,
    )

    orphan_sell = normalise_trade_event(
        event(action="SELL", legacy_trade_id="orphan-sell")
    )
    accounting = ledger_accounting(
        clean_ledger_events(pd.DataFrame([orphan_sell]))
    )
    check(
        len(accounting["orphan_sells"]) == 1,
        "SELL without an open FIFO lot is classified as orphaned",
        issues,
    )

    now = datetime(2026, 7, 20, 12, 0, tzinfo=ZoneInfo("UTC"))
    blocked = paper_execution_blocked_reason(
        {"_config_exists": False},
        ["CRYPTO"],
        execution_log={},
        now=now,
    )
    check(
        blocked == "config missing",
        "missing runtime configuration blocks paper execution",
        issues,
    )

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
