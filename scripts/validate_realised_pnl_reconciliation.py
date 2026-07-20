"""Validate one exact realised-P&L chain from ledger FIFO to dashboard series."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.paper_challenge import build_realised_pnl_series
from execution.accounting import authoritative_ledger_accounting, ledger_accounting
from execution.trade_audit import (
    build_authoritative_trade_audit,
    build_trade_audit_trail_from_ledger,
    clean_ledger_events,
)
from execution.trade_ledger import build_trade_event, load_trade_ledger


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def main():
    issues = []
    ledger = load_trade_ledger(ROOT / "trade_ledger_v1.csv")
    clean = clean_ledger_events(ledger)
    sells = clean[clean["action"].eq("SELL")].copy()
    accounting = authoritative_ledger_accounting(ROOT)
    audit = build_authoritative_trade_audit(ledger_path=ROOT / "trade_ledger_v1.csv")
    broker = pd.read_csv(ROOT / "broker_account.csv").iloc[0]
    headline = float(broker["realised_pnl"])
    curve = build_realised_pnl_series(
        audit, headline, starting_balance=10000.0, challenge_start_date="2026-06-21",
        display_end_date="2026-07-20",
    )

    ledger_total = float(accounting["realised_pnl"])
    event_total = float(audit["pnl"].sum())
    event_endpoint = float(curve.data.iloc[-1]["cumulative_realised_pnl"])
    equity_endpoint = float(curve.data.iloc[-1]["realised_equity"])
    sell_ids = set(sells["event_id"].astype(str))
    curve_ids = {
        event_id
        for value in curve.data.loc[curve.data["has_realisation_event"], "event_id"].astype(str)
        for event_id in value.split(" | ")
    }

    check(len(sells) == sells["event_id"].nunique(), "every canonical SELL has a unique event ID", issues)
    check(sell_ids == curve_ids and curve.event_count == len(sells), "every SELL produces exactly one consolidated realised event", issues)
    check(audit[["entry_event_id", "exit_event_id"]].duplicated().sum() == 0, "FIFO lot matches cannot be duplicated", issues)
    check(float(curve.data.iloc[0]["realised_equity"]) == 10000.0, "realised-equity curve starts at configured balance", issues)
    check(curve.reconciliation_error is None, "dashboard reconciliation accepts the exact canonical chain", issues)
    check(headline == ledger_total == event_total == event_endpoint, "headline, ledger, and event-level cumulative total are exactly equal", issues)
    check(equity_endpoint == 10000.0 + headline, "realised-equity endpoint exactly equals starting balance plus headline", issues)
    check(curve.data["date"].is_monotonic_increasing and not curve.data["date"].duplicated().any(),
          "daily realised-equity dates are strictly chronological and unique", issues)

    fixture = pd.DataFrame([
        {"close_time": "2026-01-01", "entry_event_id": "buy-a", "exit_event_id": "sell-a", "pnl": 4.25},
        {"close_time": "2026-01-01", "entry_event_id": "buy-b", "exit_event_id": "sell-a", "pnl": 1.75},
        {"close_time": "2026-01-01", "entry_event_id": "buy-b", "exit_event_id": "sell-a", "pnl": 999.0},
        {"close_time": "bad", "entry_event_id": "", "exit_event_id": "", "pnl": 1000.0},
    ])
    fixture_curve = build_realised_pnl_series(
        fixture, 6.0, starting_balance=10000.0, challenge_start_date="2025-12-31",
        display_end_date="2026-01-03",
    )
    check(fixture_curve.event_count == 1 and float(fixture_curve.data.iloc[-1]["cumulative_realised_pnl"]) == 6.0,
          "partial FIFO matches consolidate once and altered duplicates do not double count", issues)
    check(fixture_curve.malformed_events == 1, "malformed realised events are ignored", issues)
    check("cumulative" not in " ".join(fixture_curve.data.columns).replace("cumulative_realised_pnl", ""),
          "no input cumulative field is cumulatively summed", issues)

    fee_ledger = pd.DataFrame([
        build_trade_event(timestamp="2026-01-01 09:00", trade_date="2026-01-01", trade_time="09:00", ticker="PART", action="BUY", shares=10, price=10, value=100, fees=2, currency="GBP", reason="fixture", legacy_trade_id="buy", run_id="fixture"),
        build_trade_event(timestamp="2026-01-02 09:00", trade_date="2026-01-02", trade_time="09:00", ticker="PART", action="SELL", shares=4, price=12, value=48, fees=1, currency="GBP", reason="fixture", legacy_trade_id="sell-1", run_id="fixture"),
        build_trade_event(timestamp="2026-01-03 09:00", trade_date="2026-01-03", trade_time="09:00", ticker="PART", action="SELL", shares=6, price=11, value=66, fees=1.5, currency="GBP", reason="fixture", legacy_trade_id="sell-2", run_id="fixture"),
    ])
    fee_events = clean_ledger_events(fee_ledger)
    fee_accounting = ledger_accounting(fee_events)
    fee_audit = build_trade_audit_trail_from_ledger(fee_ledger)
    check(len(fee_audit) == 2 and fee_audit["exit_event_id"].nunique() == 2,
          "partial closes produce one realised event per SELL", issues)
    check(float(fee_accounting["realised_pnl"]) == 9.5 and float(fee_audit["pnl"].sum()) == 9.5,
          "entry and exit fees are allocated exactly once across partial closes", issues)

    print(f"headline={headline!r}")
    print(f"ledger={ledger_total!r}")
    print(f"events={event_total!r}")
    print(f"event_endpoint={event_endpoint!r}")
    print(f"realised_equity_endpoint={equity_endpoint!r}")
    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
