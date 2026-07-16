from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import ledger_accounting
from execution.portfolio_manager import (
    PORTFOLIO_COLUMNS,
    append_portfolio_position,
)
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def position(ticker, shares=1.0, price=100.0):
    return [ticker, "2026-07-01", price, shares, price * shares, 90.0, 120.0, 0, ""]


def frame(tickers, index=None):
    result = pd.DataFrame([position(ticker) for ticker in tickers], columns=PORTFOLIO_COLUMNS)
    if index is not None:
        result.index = index
    return result


def append_many(portfolio, tickers):
    for ticker in tickers:
        portfolio = append_portfolio_position(portfolio, position(ticker))
    return portfolio


def ledger_for_open_positions(portfolio):
    events = []
    for row_number, (_, row) in enumerate(portfolio.iterrows(), start=1):
        events.append(build_trade_event(
            timestamp=f"2026-07-16 13:25:{row_number:02d}", trade_date="2026-07-16",
            trade_time=f"13:25:{row_number:02d}", ticker=row["ticker"], action="BUY",
            shares=row["shares"], price=row["entry_price"], value=row["position_value"],
            currency="GBP", reason="SIGNAL ENTRY", legacy_trade_id=f"test-{row['ticker']}",
            run_id="portfolio-append-regression", position_id=f"{row['ticker']}-open",
        ))
    return pd.DataFrame(events, columns=LEDGER_COLUMNS)


def shares_by_ticker(data, column="shares"):
    return data.groupby("ticker")[column].sum().sort_index().to_dict()


def main():
    issues = []

    portfolio = frame(["AAPL", "IUSA.L", "NVDA", "VWRL.L"])
    portfolio = portfolio[~portfolio["ticker"].isin(["AAPL", "NVDA"])].reset_index(drop=True)
    portfolio = append_many(portfolio, ["MSFT", "BTC-GBP", "ETH-GBP"])
    expected = {"IUSA.L", "VWRL.L", "MSFT", "BTC-GBP", "ETH-GBP"}
    check(set(portfolio["ticker"]) == expected, "multiple exits and buys retain every expected ticker", issues)
    check(portfolio["ticker"].value_counts().eq(1).all(), "all expected tickers occur exactly once", issues)
    check("VWRL.L" in set(portfolio["ticker"]), "VWRL survives later BTC and ETH appends", issues)
    check("BTC-GBP" in set(portfolio["ticker"]) and "ETH-GBP" in set(portfolio["ticker"]), "BTC and ETH survive consecutive appends", issues)

    clean = clean_ledger_events(ledger_for_open_positions(portfolio))
    accounting = ledger_accounting(clean)
    ledger_shares = shares_by_ticker(accounting["open_lots"])
    portfolio_shares = shares_by_ticker(portfolio)
    check(ledger_shares == portfolio_shares, "portfolio shares equal clean ledger open lots", issues)

    one = frame(["AAPL", "VWRL.L"])
    one = one[one["ticker"].ne("AAPL")].reset_index(drop=True)
    one = append_portfolio_position(one, position("MSFT"))
    check(list(one["ticker"]) == ["VWRL.L", "MSFT"], "one exit followed by one buy is safe", issues)

    empty = append_many(frame([]), ["MSFT", "BTC-GBP", "ETH-GBP"])
    check(list(empty["ticker"]) == ["MSFT", "BTC-GBP", "ETH-GBP"], "multiple buys append safely to an empty portfolio", issues)

    sparse = append_portfolio_position(frame(["IUSA.L", "VWRL.L"], index=[4, 9]), position("BTC-GBP"))
    check(list(sparse.index) == [0, 1, 2] and list(sparse["ticker"]) == ["IUSA.L", "VWRL.L", "BTC-GBP"], "append normalizes an arbitrary non-contiguous index", issues)

    try:
        append_portfolio_position(sparse, position("BTC-GBP"))
        duplicate_refused = False
    except ValueError:
        duplicate_refused = True
    check(duplicate_refused, "duplicate open ticker append is refused", issues)

    check(list(portfolio.columns) == PORTFOLIO_COLUMNS, "portfolio column order is preserved", issues)
    check(len(clean) == len(portfolio) and accounting["orphan_sells"].empty, "atomic accounting inputs remain valid", issues)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
