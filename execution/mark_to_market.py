from datetime import datetime
from pathlib import Path
import os

import pandas as pd

from execution.accounting import broker_frame, broker_values_from_ledger_and_holdings
from execution.accounting import authoritative_ledger_accounting
from execution.atomic_io import atomic_write_csv_frames


PORTFOLIO_FILE = "paper_portfolio_v3.csv"
TRADE_JOURNAL_FILE = "trade_journal_v3.csv"
HOLDINGS_FILE = "holdings_report.csv"
BROKER_FILE = "broker_account.csv"
PORTFOLIO_REPORT_FILE = "portfolio_v2.csv"
TRACKER_FILE = "paper_30_day_tracker.csv"
SNAPSHOT_FILE = Path("data") / "live_monitor_snapshot.json"


def _path(base_dir, file_name):
    return Path(base_dir) / file_name


def _read_csv(path, **kwargs):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, **kwargs)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _numeric(value, default=0.0):
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return default
    return float(value)


def _frames_equal(left, right):
    if list(left.columns) != list(right.columns):
        return False
    if len(left) != len(right):
        return False

    for column in left.columns:
        left_values = left[column]
        right_values = right[column]
        left_numeric = pd.to_numeric(left_values, errors="coerce")
        right_numeric = pd.to_numeric(right_values, errors="coerce")
        numeric_mask = left_numeric.notna() | right_numeric.notna()

        if numeric_mask.any():
            if not (
                (left_numeric[numeric_mask] - right_numeric[numeric_mask])
                .abs()
                .le(1e-9)
                .all()
            ):
                return False

        text_mask = ~numeric_mask
        if text_mask.any():
            left_text = left_values[text_mask].fillna("").astype(str)
            right_text = right_values[text_mask].fillna("").astype(str)
            if not left_text.reset_index(drop=True).equals(
                right_text.reset_index(drop=True)
            ):
                return False

    return True


def _close_enough(left, right, tolerance=1e-9):
    return abs(_numeric(left) - _numeric(right)) <= tolerance


def _frame_changed(path, frame):
    path = Path(path)
    existing = _read_csv(path)
    if not existing.empty or path.exists():
        return not _frames_equal(existing, frame)
    return True


def _latest_prices_from_monitor(monitor_result):
    prices = {}
    timestamps = {}

    if not monitor_result:
        return prices, timestamps

    for position in monitor_result.get("positions", []) or []:
        ticker = str(position.get("ticker", "")).strip()
        price = position.get("current_price")
        if not ticker or price is None or pd.isna(price):
            continue
        prices[ticker] = float(price)
        timestamps[ticker] = position.get("price_timestamp")

    for ticker, result in (monitor_result.get("latest_prices", {}) or {}).items():
        if result is None:
            continue
        price = result.get("price") if isinstance(result, dict) else result
        if price is None or pd.isna(price):
            continue
        prices[str(ticker)] = float(price)
        if isinstance(result, dict):
            timestamps[str(ticker)] = result.get("timestamp")

    return prices, timestamps


def _load_monitor_snapshot(base_dir):
    path = _path(base_dir, SNAPSHOT_FILE)
    if not path.exists():
        return None

    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _existing_holding_rows(base_dir):
    holdings = _read_csv(_path(base_dir, HOLDINGS_FILE))
    if holdings.empty or "ticker" not in holdings.columns:
        return {}
    return {
        str(row.get("ticker", "")).strip(): row
        for _, row in holdings.iterrows()
    }


def _position_shares_by_ticker(frame):
    if frame is None or frame.empty:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["shares"] = pd.to_numeric(data["shares"], errors="coerce").fillna(0.0)
    return data[data["ticker"].ne("")].groupby("ticker")["shares"].sum().to_dict()


def _ledger_portfolio_mismatches(portfolio, base_dir, tolerance=1e-6):
    accounting = authoritative_ledger_accounting(base_dir=base_dir)
    if accounting is None:
        return []

    ledger_positions = _position_shares_by_ticker(accounting["open_lots"])
    portfolio_positions = _position_shares_by_ticker(portfolio)
    mismatches = []
    for ticker in sorted(set(ledger_positions) | set(portfolio_positions)):
        ledger_shares = float(ledger_positions.get(ticker, 0.0))
        portfolio_shares = float(portfolio_positions.get(ticker, 0.0))
        if abs(ledger_shares - portfolio_shares) > tolerance:
            mismatches.append(
                {
                    "ticker": ticker,
                    "ledger_shares": ledger_shares,
                    "portfolio_shares": portfolio_shares,
                }
            )
    return mismatches


def _build_valuation(portfolio, latest_prices, timestamp, existing_holdings=None):
    valued_portfolio = portfolio.copy()
    existing_holdings = existing_holdings or {}
    holdings_rows = []
    total_market_value = 0.0
    total_unrealised_pnl = 0.0

    numeric_columns = [
        "current_price",
        "market_value",
        "unrealised_pnl",
        "unrealised_pnl_pct",
    ]
    for column in numeric_columns:
        if column not in valued_portfolio.columns:
            valued_portfolio[column] = pd.Series(
                [float("nan")] * len(valued_portfolio),
                dtype="float64",
            )
        else:
            valued_portfolio[column] = pd.to_numeric(
                valued_portfolio[column],
                errors="coerce",
            )
    if "valuation_updated_at" not in valued_portfolio.columns:
        valued_portfolio["valuation_updated_at"] = pd.Series(
            [""] * len(valued_portfolio),
            dtype="object",
        )
    else:
        valued_portfolio["valuation_updated_at"] = (
            valued_portfolio["valuation_updated_at"].fillna("").astype(object)
        )

    for index, position in valued_portfolio.iterrows():
        ticker = str(position.get("ticker", "")).strip()
        if ticker not in latest_prices:
            continue

        shares = _numeric(position.get("shares"))
        entry_price = _numeric(position.get("entry_price"))
        original_value = _numeric(position.get("position_value"))
        current_price = latest_prices[ticker]
        market_value = shares * current_price
        cost_basis = shares * entry_price
        unrealised_pnl = market_value - cost_basis
        unrealised_pnl_pct = (
            (current_price / entry_price) - 1
            if entry_price
            else 0.0
        )
        previous_holding = existing_holdings.get(ticker)
        holding_unchanged = (
            previous_holding is not None
            and _close_enough(previous_holding.get("current_price"), current_price)
            and _close_enough(previous_holding.get("market_value"), market_value)
            and _close_enough(previous_holding.get("unrealised_pnl"), unrealised_pnl)
            and _close_enough(
                previous_holding.get("unrealised_pnl_percent"),
                unrealised_pnl_pct,
            )
        )
        portfolio_unchanged = (
            _close_enough(position.get("current_price"), current_price)
            and _close_enough(position.get("market_value"), market_value)
            and _close_enough(position.get("unrealised_pnl"), unrealised_pnl)
            and _close_enough(position.get("unrealised_pnl_pct"), unrealised_pnl_pct)
        )
        valuation_timestamp = (
            position.get("valuation_updated_at")
            if portfolio_unchanged and str(position.get("valuation_updated_at", "")).strip()
            else timestamp
        )
        holding_date = (
            previous_holding.get("date")
            if holding_unchanged and str(previous_holding.get("date", "")).strip()
            else timestamp
        )

        valued_portfolio.loc[index, "current_price"] = current_price
        valued_portfolio.loc[index, "market_value"] = market_value
        valued_portfolio.loc[index, "unrealised_pnl"] = unrealised_pnl
        valued_portfolio.loc[index, "unrealised_pnl_pct"] = unrealised_pnl_pct
        valued_portfolio.loc[index, "valuation_updated_at"] = valuation_timestamp

        total_market_value += market_value
        total_unrealised_pnl += market_value - original_value
        holdings_rows.append(
            {
                "date": holding_date,
                "ticker": ticker,
                "shares": shares,
                "entry_price": entry_price,
                "current_price": current_price,
                "market_value": market_value,
                "unrealised_pnl": unrealised_pnl,
                "unrealised_pnl_percent": unrealised_pnl_pct,
            }
        )

    return valued_portfolio, pd.DataFrame(holdings_rows), total_market_value, total_unrealised_pnl


def _build_broker(cash, positions_value, realised_pnl, unrealised_pnl):
    portfolio_value = cash + positions_value
    return pd.DataFrame(
        [
            {
                "cash": float(cash),
                "buying_power": float(cash),
                "positions_value": float(positions_value),
                "portfolio_value": float(portfolio_value),
                "realised_pnl": float(realised_pnl),
                "unrealised_pnl": float(unrealised_pnl),
            }
        ]
    )


def _build_portfolio_report_refresh(base_dir, portfolio_value):
    path = _path(base_dir, PORTFOLIO_REPORT_FILE)
    report = _read_csv(path)
    if report.empty or "equity" not in report.columns:
        return None, False

    report = report.copy()
    previous_equity = (
        _numeric(report["equity"].iloc[-2])
        if len(report) > 1
        else _numeric(report["equity"].iloc[-1])
    )
    report.loc[report.index[-1], "equity"] = float(portfolio_value)
    if "daily_return" in report.columns:
        report.loc[report.index[-1], "daily_return"] = (
            (float(portfolio_value) / previous_equity) - 1
            if previous_equity
            else 0.0
        )
    if "peak" in report.columns:
        previous_peak = (
            pd.to_numeric(report["peak"], errors="coerce")
            .dropna()
            .max()
        )
        report.loc[report.index[-1], "peak"] = max(
            float(portfolio_value),
            float(previous_peak) if not pd.isna(previous_peak) else float(portfolio_value),
        )
    if "drawdown" in report.columns and "peak" in report.columns:
        peak = _numeric(report.loc[report.index[-1], "peak"])
        report.loc[report.index[-1], "drawdown"] = (
            (float(portfolio_value) / peak) - 1
            if peak
            else 0.0
        )

    return report, _frame_changed(path, report)


def _build_tracker_refresh(base_dir, broker, timestamp):
    path = _path(base_dir, TRACKER_FILE)
    tracker = _read_csv(path)
    latest = tracker.iloc[-1].to_dict() if not tracker.empty else {}

    value_columns = [
        "portfolio_value",
        "cash",
        "realised_pnl",
        "unrealised_pnl",
    ]
    changed = any(
        abs(_numeric(latest.get(column)) - float(broker[column])) > 1e-9
        for column in value_columns
    )
    if not changed and path.exists():
        return tracker, False

    row = {
        "date": timestamp,
        "portfolio_value": float(broker["portfolio_value"]),
        "cash": float(broker["cash"]),
        "realised_pnl": float(broker["realised_pnl"]),
        "unrealised_pnl": float(broker["unrealised_pnl"]),
        "benchmark_return": _numeric(latest.get("benchmark_return")),
        "alpha": _numeric(latest.get("alpha")),
    }
    tracker = pd.concat([tracker, pd.DataFrame([row])], ignore_index=True)
    return tracker, True


def _validate_refresh_frames(frames):
    portfolio = frames.get(PORTFOLIO_FILE)
    holdings = frames.get(HOLDINGS_FILE)
    broker = frames.get(BROKER_FILE)

    if portfolio is None or holdings is None or broker is None:
        raise ValueError("Mark-to-market refresh missing core output frames.")

    if broker.empty:
        raise ValueError("Mark-to-market refresh built an empty broker frame.")

    portfolio_tickers = {
        str(ticker).strip().upper()
        for ticker in portfolio.get("ticker", pd.Series(dtype=str)).dropna()
        if str(ticker).strip()
    }
    holdings_tickers = {
        str(ticker).strip().upper()
        for ticker in holdings.get("ticker", pd.Series(dtype=str)).dropna()
        if str(ticker).strip()
    }
    if portfolio_tickers != holdings_tickers:
        raise ValueError(
            "Mark-to-market refresh portfolio/holdings tickers do not match."
        )

    required_broker_columns = {
        "cash",
        "buying_power",
        "positions_value",
        "portfolio_value",
        "realised_pnl",
        "unrealised_pnl",
    }
    if not required_broker_columns.issubset(broker.columns):
        missing = sorted(required_broker_columns - set(broker.columns))
        raise ValueError(
            "Mark-to-market broker frame missing columns: " + ", ".join(missing)
        )

    broker_row = broker.iloc[0]
    holdings_value = float(
        pd.to_numeric(
            holdings.get("market_value", pd.Series(dtype=float)),
            errors="coerce",
        )
        .fillna(0.0)
        .sum()
    )
    broker_positions_value = _numeric(broker_row.get("positions_value"))
    broker_cash = _numeric(broker_row.get("cash"))
    broker_portfolio_value = _numeric(broker_row.get("portfolio_value"))

    if abs(broker_positions_value - holdings_value) > 0.01:
        raise ValueError(
            "Mark-to-market broker positions value does not match holdings."
        )
    if abs(broker_portfolio_value - (broker_cash + holdings_value)) > 0.01:
        raise ValueError(
            "Mark-to-market broker portfolio value does not equal cash plus holdings."
        )


def _commit_refresh_frames(
    frames,
    base_dir=".",
    failure_hook=None,
    output_paths=None,
    source_portfolio=None,
):
    validation_frames = dict(frames)
    if source_portfolio is not None:
        validation_frames[PORTFOLIO_FILE] = source_portfolio
    _validate_refresh_frames(validation_frames)
    if PORTFOLIO_FILE in frames:
        raise ValueError(
            "Mark-to-market refresh cannot write the upstream paper portfolio."
        )
    output_paths = output_paths or {}
    changed_frames = {}
    changed_files = []
    for file_name, frame in frames.items():
        if frame is None:
            continue
        output_path = Path(output_paths.get(file_name, _path(base_dir, file_name)))
        if _frame_changed(output_path, frame):
            changed_frames[output_path] = frame
            changed_files.append(file_name)
    if not changed_frames:
        return []

    atomic_write_csv_frames(changed_frames, failure_hook=failure_hook)
    return changed_files


def _sync_changed_files(changed_files):
    if not changed_files:
        return []

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        return []

    sync_errors = []
    try:
        from execution.supabase_sync import (
            sync_broker_account,
            sync_holdings,
            sync_30_day_tracker,
            sync_holdings_history,
        )

        if BROKER_FILE in changed_files:
            sync_broker_account()
        if HOLDINGS_FILE in changed_files:
            sync_holdings()
            sync_holdings_history()
        if TRACKER_FILE in changed_files:
            sync_30_day_tracker()
    except Exception as exc:
        sync_errors.append(str(exc))

    return sync_errors


def mark_to_market_refresh(monitor_result=None, sync_remote=True, base_dir="."):
    """
    Refresh valuation CSVs from already-fetched live monitor prices.

    This function never opens or closes positions and never calls strategy,
    signal, risk, broker, or notification decision code.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    portfolio = _read_csv(_path(base_dir, PORTFOLIO_FILE))

    if portfolio.empty:
        return {
            "status": "skipped",
            "reason": "no open paper positions",
            "changed_files": [],
            "holdings_refreshed": 0,
            "sync_errors": [],
        }

    if monitor_result is None:
        monitor_result = _load_monitor_snapshot(base_dir)

    latest_prices, _ = _latest_prices_from_monitor(monitor_result)
    held_tickers = {
        str(ticker).strip()
        for ticker in portfolio.get("ticker", pd.Series(dtype=str)).dropna()
    }
    missing_tickers = sorted(held_tickers - set(latest_prices))
    ledger_mismatches = _ledger_portfolio_mismatches(portfolio, base_dir)

    if ledger_mismatches:
        return {
            "status": "skipped",
            "reason": "ledger open lots do not match paper portfolio",
            "changed_files": [],
            "holdings_refreshed": 0,
            "missing_tickers": missing_tickers,
            "ledger_mismatches": ledger_mismatches,
            "sync_errors": [],
        }

    if not latest_prices:
        return {
            "status": "skipped",
            "reason": "no monitor prices available",
            "changed_files": [],
            "holdings_refreshed": 0,
            "missing_tickers": missing_tickers,
            "sync_errors": [],
        }

    if missing_tickers:
        return {
            "status": "skipped",
            "reason": "missing prices for open holdings",
            "changed_files": [],
            "holdings_refreshed": 0,
            "missing_tickers": missing_tickers,
            "sync_errors": [],
        }

    valued_portfolio, holdings, positions_value, unrealised_pnl = _build_valuation(
        portfolio,
        latest_prices,
        timestamp,
        existing_holdings=_existing_holding_rows(base_dir),
    )
    broker_values = broker_values_from_ledger_and_holdings(
        holdings=holdings,
        portfolio=portfolio,
        base_dir=base_dir,
    )
    broker = broker_frame(broker_values)

    portfolio_value = float(broker.loc[0, "portfolio_value"])
    portfolio_report, _ = _build_portfolio_report_refresh(base_dir, portfolio_value)
    tracker, _ = _build_tracker_refresh(base_dir, broker.loc[0], timestamp)
    refresh_frames = {
        HOLDINGS_FILE: holdings,
        BROKER_FILE: broker,
        PORTFOLIO_REPORT_FILE: portfolio_report,
        TRACKER_FILE: tracker,
    }
    changed_files = _commit_refresh_frames(
        refresh_frames,
        base_dir=base_dir,
        source_portfolio=valued_portfolio,
    )

    sync_errors = _sync_changed_files(changed_files) if sync_remote else []

    return {
        "status": "success",
        "changed_files": changed_files,
        "holdings_refreshed": len(holdings),
        "missing_tickers": missing_tickers,
        "portfolio_value": portfolio_value,
        "unrealised_pnl": float(unrealised_pnl),
        "sync_errors": sync_errors,
    }
