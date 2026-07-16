from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import (
    authoritative_ledger_accounting,
    broker_frame,
    broker_values_from_ledger_and_holdings,
    validate_broker_frame,
)
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from reporting.holdings_report import create_holdings_report
from runtime.locks import acquire_execution_lock


SHARE_TOLERANCE = 1e-9
VALUE_TOLERANCE = 0.01
PRICE_COLUMNS = ("ticker", "price", "timestamp", "source")
REPORT_FILE = Path("data") / "derived_portfolio_state_refresh_report.json"
PROTECTED_SOURCES = (
    "trade_ledger_v1.csv",
    "trade_journal_v3.csv",
    "trade_transactions_v1.csv",
    "trade_snapshots.csv",
    "paper_portfolio_v3.csv",
)


class DerivedStateRefreshError(RuntimeError):
    pass


def read_csv(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def file_hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def position_map(frame):
    if frame is None or frame.empty or not {"ticker", "shares"}.issubset(frame.columns):
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["shares"] = pd.to_numeric(data["shares"], errors="coerce")
    if data["ticker"].eq("").any() or data["shares"].isna().any():
        raise DerivedStateRefreshError("position projection contains missing ticker or shares")
    return data.groupby("ticker")["shares"].sum().to_dict()


def validate_position_equality(accounting, portfolio):
    ledger_positions = position_map(accounting["open_lots"])
    portfolio_positions = position_map(portfolio)
    if set(ledger_positions) != set(portfolio_positions):
        raise DerivedStateRefreshError("ledger and paper portfolio ticker sets do not match")
    for ticker in sorted(ledger_positions):
        if abs(float(ledger_positions[ticker]) - float(portfolio_positions[ticker])) > SHARE_TOLERANCE:
            raise DerivedStateRefreshError(f"ledger and paper portfolio shares differ for {ticker}")
    return ledger_positions


def load_complete_prices(path, required_tickers, max_age_seconds, now=None):
    prices = read_csv(path)
    missing_columns = sorted(set(PRICE_COLUMNS) - set(prices.columns))
    if missing_columns:
        raise DerivedStateRefreshError("prices file missing columns: " + ", ".join(missing_columns))
    prices = prices[list(PRICE_COLUMNS)].copy()
    prices["ticker"] = prices["ticker"].fillna("").astype(str).str.strip().str.upper()
    if prices["ticker"].eq("").any() or prices["ticker"].duplicated().any():
        raise DerivedStateRefreshError("prices file contains missing or duplicate tickers")
    if set(prices["ticker"]) != set(required_tickers):
        raise DerivedStateRefreshError("prices file must contain exactly all open tickers")
    prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
    if prices["price"].isna().any() or not prices["price"].map(math.isfinite).all() or not prices["price"].gt(0).all():
        raise DerivedStateRefreshError("every price must be finite and positive")
    prices["parsed_timestamp"] = pd.to_datetime(prices["timestamp"], errors="coerce", utc=True)
    if prices["parsed_timestamp"].isna().any():
        raise DerivedStateRefreshError("every price requires a valid timestamp")
    if prices["source"].fillna("").astype(str).str.strip().eq("").any():
        raise DerivedStateRefreshError("every price requires a source")
    if max_age_seconds is None or int(max_age_seconds) <= 0:
        raise DerivedStateRefreshError("max price age must be a positive number of seconds")
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    ages = (now - prices["parsed_timestamp"]).dt.total_seconds()
    if ages.lt(0).any() or ages.gt(float(max_age_seconds)).any():
        raise DerivedStateRefreshError("prices file contains future or stale prices")
    prices["age_seconds"] = ages
    return prices.sort_values("ticker").reset_index(drop=True)


def frame_diff(path, frame):
    path = Path(path)
    before = path.read_text(encoding="utf-8-sig").splitlines(keepends=True) if path.exists() else []
    buffer = StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n")
    after = buffer.getvalue().splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(path), tofile=str(path) + " (refreshed)"))


def build_refresh(base_dir, prices_file, max_age_seconds, now=None):
    base = Path(base_dir)
    portfolio = read_csv(base / "paper_portfolio_v3.csv")
    if portfolio.empty:
        raise DerivedStateRefreshError("paper portfolio is empty")
    accounting = authoritative_ledger_accounting(base_dir=base)
    if accounting is None:
        raise DerivedStateRefreshError("authoritative ledger accounting is unavailable")
    if not accounting["orphan_sells"].empty:
        raise DerivedStateRefreshError("clean ledger contains orphan SELL events")
    positions = validate_position_equality(accounting, portfolio)
    price_rows = load_complete_prices(prices_file, positions, max_age_seconds, now=now)
    valuation_time = max(price_rows["parsed_timestamp"])
    price_series = price_rows.set_index("ticker")["price"]
    canonical_prices = pd.DataFrame(
        [price_series.to_dict()],
        index=pd.DatetimeIndex([valuation_time]),
    )
    holdings = create_holdings_report(portfolio, canonical_prices)
    if position_map(holdings) != positions:
        raise DerivedStateRefreshError("canonical holdings shares do not equal ledger shares")
    market_value = float(pd.to_numeric(holdings["market_value"], errors="coerce").sum())
    broker_values = broker_values_from_ledger_and_holdings(
        holdings=holdings,
        portfolio=portfolio,
        base_dir=base,
    )
    broker = broker_frame(broker_values)
    validate_broker_frame(broker)
    if abs(float(broker.iloc[0]["positions_value"]) - market_value) > VALUE_TOLERANCE:
        raise DerivedStateRefreshError("broker positions value does not equal holdings market value")
    if abs(float(broker.iloc[0]["cash"]) - float(accounting["expected_cash"])) > VALUE_TOLERANCE:
        raise DerivedStateRefreshError("broker cash is not ledger-derived")
    if abs(float(broker.iloc[0]["realised_pnl"]) - float(accounting["realised_pnl"])) > VALUE_TOLERANCE:
        raise DerivedStateRefreshError("broker realised PnL is not ledger-derived")
    return holdings, broker, price_rows, {
        "ledger_portfolio_shares_equal": True,
        "holdings_ledger_shares_equal": True,
        "broker_positions_equal_holdings_market_value": True,
        "broker_cash_ledger_derived": True,
        "broker_realised_pnl_ledger_derived": True,
        "position_count": len(positions),
    }


def run(base_dir, prices_file, max_age_seconds, apply=False, now=None):
    base = Path(base_dir)
    holdings_path = base / "holdings_report.csv"
    broker_path = base / "broker_account.csv"
    report_path = base / REPORT_FILE
    holdings, broker, prices, validation = build_refresh(
        base, prices_file, max_age_seconds, now=now
    )
    print(frame_diff(holdings_path, holdings) or "No holdings changes proposed.")
    print(frame_diff(broker_path, broker) or "No broker changes proposed.")
    print("declared outputs: holdings_report.csv, broker_account.csv")
    if not apply:
        print("dry-run only; no files or reports written")
        return 0

    lock_path = base / "data" / "execution.lock"
    lock = acquire_execution_lock(lock_path, context="derived_portfolio_state_refresh")
    if not lock.acquired:
        raise DerivedStateRefreshError("another execution holds the runtime lock")
    try:
        # Rebuild from current sources under the lock; never write a pre-lock frame.
        holdings, broker, prices, validation = build_refresh(
            base, prices_file, max_age_seconds, now=now
        )
        protected_before = {name: file_hash(base / name) for name in PROTECTED_SOURCES}
        before = {
            "holdings_report.csv": file_hash(holdings_path),
            "broker_account.csv": file_hash(broker_path),
        }
        atomic_write_csv_frames(
            {holdings_path: holdings, broker_path: broker},
            lock_path=lock_path,
        )
        protected_after = {name: file_hash(base / name) for name in PROTECTED_SOURCES}
        if protected_before != protected_after:
            raise DerivedStateRefreshError("protected accounting source changed during refresh")
        after = {
            "holdings_report.csv": file_hash(holdings_path),
            "broker_account.csv": file_hash(broker_path),
        }
        report = {
            "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "before_hashes": before,
            "after_hashes": after,
            "protected_source_hashes": protected_after,
            "prices": prices[["ticker", "price", "timestamp", "source", "age_seconds"]].to_dict(orient="records"),
            "validation": validation,
            "updated_files": ["holdings_report.csv", "broker_account.csv"],
            "untouched_derived_files": ["paper_30_day_tracker.csv", "portfolio_v2.csv"],
            "sync_remote": False,
        }
        atomic_write_json(report, report_path, lock_path=lock_path)
        print(f"applied report={report_path}")
    finally:
        lock.release()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Refresh holdings and broker derived state from an explicit complete price snapshot"
    )
    parser.add_argument("--base-dir", default=ROOT)
    parser.add_argument("--prices-file", required=True)
    parser.add_argument("--max-price-age-seconds", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(
        args.base_dir,
        args.prices_file,
        args.max_price_age_seconds,
        apply=args.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
