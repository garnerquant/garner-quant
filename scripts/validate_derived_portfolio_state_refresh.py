from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.portfolio_manager import PORTFOLIO_COLUMNS
from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event
from scripts.refresh_derived_portfolio_state import (
    DerivedStateRefreshError,
    build_refresh,
    file_hash,
    position_map,
    run,
)


POSITIONS = [
    ("AAPL", 3.0, 300.0, 900.0),
    ("BTC-GBP", 0.02, 50000.0, 1000.0),
    ("IUSA.L", 0.35, 5600.0, 1960.0),
    ("MSFT", 2.5, 400.0, 1000.0),
    ("NVDA", 5.0, 200.0, 1000.0),
]


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def write_fixture(base):
    base.mkdir(parents=True, exist_ok=True)
    events = []
    portfolio_rows = []
    for offset, (ticker, shares, price, value) in enumerate(POSITIONS):
        timestamp = f"2026-07-16 12:00:{offset:02d}"
        events.append(build_trade_event(
            timestamp=timestamp, trade_date="2026-07-16", trade_time=f"12:00:{offset:02d}",
            ticker=ticker, action="BUY", shares=shares, price=price, value=value,
            currency="GBP", reason="fixture", legacy_trade_id=f"fixture-{ticker}",
            run_id="derived-refresh-fixture", position_id=f"{ticker}-open",
        ))
        portfolio_rows.append([
            ticker, "2026-07-16", price, shares, value, price * 0.9,
            price * 1.1, 0, "",
        ])
    pd.DataFrame(events, columns=LEDGER_COLUMNS).to_csv(base / "trade_ledger_v1.csv", index=False)
    pd.DataFrame(portfolio_rows, columns=PORTFOLIO_COLUMNS).to_csv(base / "paper_portfolio_v3.csv", index=False)
    pd.DataFrame([{"ticker": "AAPL", "shares": 3, "market_value": 1}]).to_csv(base / "holdings_report.csv", index=False)
    pd.DataFrame([{"cash": 1, "buying_power": 1, "positions_value": 1, "portfolio_value": 2, "realised_pnl": 0, "unrealised_pnl": 0}]).to_csv(base / "broker_account.csv", index=False)
    for name in ["trade_journal_v3.csv", "trade_transactions_v1.csv", "trade_snapshots.csv"]:
        (base / name).write_bytes(f"protected {name}\n".encode())
    (base / "paper_30_day_tracker.csv").write_bytes(b"tracker unchanged\n")
    (base / "portfolio_v2.csv").write_bytes(b"portfolio report unchanged\n")


def write_prices(path, now, rows=None):
    rows = rows or [
        {"ticker": ticker, "price": price * 1.01, "timestamp": now.isoformat(), "source": "fixture"}
        for ticker, _, price, _ in POSITIONS
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def main():
    issues = []
    base = ROOT / ".derived_portfolio_refresh_fixture"
    if base.exists():
        shutil.rmtree(base)
    now = datetime.now(timezone.utc)
    try:
        write_fixture(base)
        prices_path = base / "prices.csv"
        write_prices(prices_path, now)
        holdings, broker, prices, validation = build_refresh(base, prices_path, 300, now=now)
        expected = {ticker: shares for ticker, shares, _, _ in POSITIONS}
        check(position_map(holdings) == expected, "canonical holdings contain all five ledger positions", issues)
        holdings_value = float(holdings["market_value"].sum())
        check(abs(float(broker.iloc[0]["positions_value"]) - holdings_value) <= 0.01, "broker positions value equals holdings market value", issues)
        check(validation["broker_cash_ledger_derived"] and validation["broker_realised_pnl_ledger_derived"], "cash and realised PnL remain ledger-derived", issues)

        protected = ["trade_ledger_v1.csv", "trade_journal_v3.csv", "trade_transactions_v1.csv", "trade_snapshots.csv", "paper_portfolio_v3.csv", "paper_30_day_tracker.csv", "portfolio_v2.csv"]
        before = {name: (base / name).read_bytes() for name in protected}
        holdings_before = (base / "holdings_report.csv").read_bytes()
        broker_before = (base / "broker_account.csv").read_bytes()
        check(run(base, prices_path, 300, apply=False, now=now) == 0, "dry-run succeeds", issues)
        check((base / "holdings_report.csv").read_bytes() == holdings_before and (base / "broker_account.csv").read_bytes() == broker_before and not (base / "data").exists(), "dry-run mutates no outputs and writes no report", issues)

        check(run(base, prices_path, 300, apply=True, now=now) == 0, "fixture apply succeeds atomically", issues)
        report = json.loads((base / "data" / "derived_portfolio_state_refresh_report.json").read_text())
        check(report["updated_files"] == ["holdings_report.csv", "broker_account.csv"], "report declares only holdings and broker outputs", issues)
        check(len(report["prices"]) == 5 and all(row["source"] == "fixture" for row in report["prices"]), "report records every exact price, timestamp, and source", issues)
        check(before == {name: (base / name).read_bytes() for name in protected}, "ledger, portfolio, journals, snapshots, tracker, and portfolio report remain byte-identical", issues)

        def refused(rows, max_age=300, phrase=""):
            write_fixture(base)
            write_prices(prices_path, now, rows)
            original_h = (base / "holdings_report.csv").read_bytes()
            original_b = (base / "broker_account.csv").read_bytes()
            try:
                run(base, prices_path, max_age, apply=True, now=now)
                ok = False
            except DerivedStateRefreshError as exc:
                ok = phrase.lower() in str(exc).lower()
            return ok and (base / "holdings_report.csv").read_bytes() == original_h and (base / "broker_account.csv").read_bytes() == original_b

        valid_rows = [
            {"ticker": ticker, "price": price, "timestamp": now.isoformat(), "source": "fixture"}
            for ticker, _, price, _ in POSITIONS
        ]
        check(refused(valid_rows[:-1], phrase="exactly all"), "partial price snapshot is refused before mutation", issues)
        check(refused(valid_rows + [valid_rows[0]], phrase="duplicate"), "duplicate price ticker is refused before mutation", issues)
        stale = [dict(row, timestamp="2020-01-01T00:00:00+00:00") for row in valid_rows]
        check(refused(stale, phrase="stale"), "stale prices are refused before mutation", issues)
        invalid = [dict(row) for row in valid_rows]
        invalid[0]["price"] = -1
        check(refused(invalid, phrase="finite and positive"), "invalid prices are refused before mutation", issues)

        write_fixture(base)
        portfolio = pd.read_csv(base / "paper_portfolio_v3.csv")
        portfolio.loc[0, "shares"] += 1
        portfolio.to_csv(base / "paper_portfolio_v3.csv", index=False)
        write_prices(prices_path, now)
        try:
            build_refresh(base, prices_path, 300, now=now)
            mismatch_refused = False
        except DerivedStateRefreshError as exc:
            mismatch_refused = "shares differ" in str(exc)
        check(mismatch_refused, "ledger/portfolio share mismatch is refused", issues)

        write_fixture(base)
        write_prices(prices_path, now)
        original_h = (base / "holdings_report.csv").read_bytes()
        original_b = (base / "broker_account.csv").read_bytes()
        with patch("scripts.refresh_derived_portfolio_state.build_refresh", side_effect=DerivedStateRefreshError("simulated invariant failure")):
            try:
                run(base, prices_path, 300, apply=True, now=now)
                invariant_refused = False
            except DerivedStateRefreshError:
                invariant_refused = True
        check(invariant_refused and (base / "holdings_report.csv").read_bytes() == original_h and (base / "broker_account.csv").read_bytes() == original_b, "invariant failure occurs before mutation", issues)
    finally:
        if base.exists():
            shutil.rmtree(base)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
