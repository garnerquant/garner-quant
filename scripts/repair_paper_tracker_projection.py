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

from config import STARTING_CASH
from execution.accounting import (
    authoritative_ledger_accounting,
    broker_values_from_ledger_and_holdings,
)
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from runtime.locks import acquire_execution_lock


TRACKER_COLUMNS = (
    "date",
    "portfolio_value",
    "cash",
    "realised_pnl",
    "unrealised_pnl",
    "benchmark_return",
    "alpha",
)
SHARE_TOLERANCE = 1e-6
VALUE_TOLERANCE = 0.01
REPORT_FILE = Path("data") / "paper_tracker_projection_repair_report.json"
PROTECTED_FILES = (
    "trade_ledger_v1.csv",
    "trade_journal_v3.csv",
    "trade_transactions_v1.csv",
    "trade_snapshots.csv",
    "paper_portfolio_v3.csv",
    "holdings_report.csv",
    "broker_account.csv",
)


class TrackerRepairError(RuntimeError):
    pass


def read_csv(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def file_hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def finite(value, name):
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed) or not math.isfinite(float(parsed)):
        raise TrackerRepairError(f"{name} must be finite")
    return float(parsed)


def positions(frame):
    if frame.empty or not {"ticker", "shares"}.issubset(frame.columns):
        raise TrackerRepairError("position projection is missing ticker or shares")
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["shares"] = pd.to_numeric(data["shares"], errors="coerce")
    if data["ticker"].eq("").any() or data["shares"].isna().any():
        raise TrackerRepairError("position projection contains invalid ticker or shares")
    return data.groupby("ticker")["shares"].sum().to_dict()


def validate_healthy_accounting(base):
    base = Path(base)
    portfolio = read_csv(base / "paper_portfolio_v3.csv")
    holdings = read_csv(base / "holdings_report.csv")
    broker = read_csv(base / "broker_account.csv")
    accounting = authoritative_ledger_accounting(base_dir=base)
    if accounting is None or not accounting["orphan_sells"].empty:
        raise TrackerRepairError("authoritative ledger accounting is unhealthy")
    ledger_positions = positions(accounting["open_lots"])
    portfolio_positions = positions(portfolio)
    holdings_positions = positions(holdings)
    if not (set(ledger_positions) == set(portfolio_positions) == set(holdings_positions)):
        raise TrackerRepairError("ledger, portfolio, and holdings ticker sets are not healthy")
    for ticker in sorted(ledger_positions):
        ledger_shares = float(ledger_positions[ticker])
        if abs(ledger_shares - float(portfolio_positions[ticker])) > SHARE_TOLERANCE:
            raise TrackerRepairError(f"portfolio shares are unhealthy for {ticker}")
        if abs(ledger_shares - float(holdings_positions[ticker])) > SHARE_TOLERANCE:
            raise TrackerRepairError(f"holdings shares are unhealthy for {ticker}")
    if broker.empty or len(broker) != 1:
        raise TrackerRepairError("broker account must contain exactly one row")
    target = broker_values_from_ledger_and_holdings(
        holdings=holdings,
        portfolio=portfolio,
        base_dir=base,
    )
    broker_row = broker.iloc[0]
    for field in (
        "cash",
        "buying_power",
        "positions_value",
        "portfolio_value",
        "realised_pnl",
        "unrealised_pnl",
    ):
        if abs(finite(broker_row.get(field), f"broker {field}") - float(target[field])) > VALUE_TOLERANCE:
            raise TrackerRepairError(f"broker {field} does not match canonical accounting")
    return {
        "portfolio_value": float(target["portfolio_value"]),
        "cash": float(target["cash"]),
        "realised_pnl": float(target["realised_pnl"]),
        "unrealised_pnl": float(target["unrealised_pnl"]),
        "position_count": len(ledger_positions),
    }


def tracker_text(frame):
    buffer = StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n")
    return buffer.getvalue()


def unified_diff(path, repaired):
    path = Path(path)
    before = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    after = tracker_text(repaired).splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(path), tofile=str(path) + " (repaired)"))


def build_repair(base_dir, repair_date=None):
    base = Path(base_dir)
    tracker_path = base / "paper_30_day_tracker.csv"
    tracker = read_csv(tracker_path)
    if tracker.empty:
        raise TrackerRepairError("paper tracker is empty")
    if list(tracker.columns) != list(TRACKER_COLUMNS):
        raise TrackerRepairError("paper tracker columns do not match canonical schema")
    parsed_dates = pd.to_datetime(tracker["date"], errors="coerce")
    if parsed_dates.isna().any():
        raise TrackerRepairError("paper tracker contains invalid dates")
    if parsed_dates.duplicated().any():
        raise TrackerRepairError("paper tracker contains duplicate timestamps")
    target_date = (
        pd.Timestamp(repair_date).date()
        if repair_date
        else parsed_dates.max().date()
    )
    candidates = tracker.index[parsed_dates.dt.date == target_date].tolist()
    if len(candidates) != 1:
        raise TrackerRepairError(
            f"repair date {target_date} is ambiguous; found {len(candidates)} tracker rows"
        )
    target_index = candidates[0]
    if parsed_dates.loc[target_index] != parsed_dates.max():
        raise TrackerRepairError("repair candidate must be the latest tracker row")
    canonical = validate_healthy_accounting(base)
    repaired = tracker.copy()
    before_row = tracker.loc[target_index].to_dict()
    for field in ("portfolio_value", "cash", "realised_pnl", "unrealised_pnl"):
        repaired.loc[target_index, field] = canonical[field]
    if not repaired.drop(index=target_index).equals(tracker.drop(index=target_index)):
        raise TrackerRepairError("repair changed historical tracker rows")
    if repaired["date"].duplicated().any():
        raise TrackerRepairError("repair would create duplicate tracker timestamps")
    start = float(STARTING_CASH)
    if not math.isfinite(start) or start <= 0:
        raise TrackerRepairError("starting balance must be finite and positive")
    current = float(canonical["portfolio_value"])
    total_return = (current / start) - 1
    return repaired, {
        "repair_date": str(target_date),
        "target_row_index": int(target_index),
        "target_timestamp": str(tracker.loc[target_index, "date"]),
        "before_row": before_row,
        "after_row": repaired.loc[target_index].to_dict(),
        "starting_balance": start,
        "current_balance": current,
        "total_return": total_return,
        "return_percent": total_return * 100,
        "realised_pnl": canonical["realised_pnl"],
        "unrealised_pnl": canonical["unrealised_pnl"],
        "equity_curve_final_return": total_return,
        "historical_rows_preserved": True,
        "accounting_validator_healthy": True,
    }


def run(base_dir=ROOT, repair_date=None, apply=False):
    base = Path(base_dir)
    tracker_path = base / "paper_30_day_tracker.csv"
    report_path = base / REPORT_FILE
    repaired, details = build_repair(base, repair_date=repair_date)
    print(unified_diff(tracker_path, repaired) or "No tracker changes proposed.")
    print(
        f"current_balance={details['current_balance']:.12f} "
        f"return={details['total_return']:.8%}"
    )
    if not apply:
        print("dry-run only; no files or reports written")
        return 0
    lock_path = base / "data" / "execution.lock"
    lock = acquire_execution_lock(lock_path, context="paper_tracker_projection_repair")
    if not lock.acquired:
        raise TrackerRepairError("another execution holds the runtime lock")
    try:
        repaired, details = build_repair(base, repair_date=repair_date)
        protected_before = {name: file_hash(base / name) for name in PROTECTED_FILES}
        before_hash = file_hash(tracker_path)
        atomic_write_csv_frames({tracker_path: repaired}, lock_path=lock_path)
        protected_after = {name: file_hash(base / name) for name in PROTECTED_FILES}
        if protected_before != protected_after:
            raise TrackerRepairError("protected accounting state changed during tracker repair")
        after_hash = file_hash(tracker_path)
        report = {
            "repaired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tracker_file": "paper_30_day_tracker.csv",
            "before_hash": before_hash,
            "after_hash": after_hash,
            "protected_hashes": protected_after,
            **details,
        }
        atomic_write_json(report, report_path, lock_path=lock_path)
        print(f"applied report={report_path}")
    finally:
        lock.release()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Repair one latest-day paper tracker projection from healthy broker accounting"
    )
    parser.add_argument("--base-dir", default=ROOT)
    parser.add_argument("--repair-date", help="Target YYYY-MM-DD; defaults to latest tracker date")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(args.base_dir, repair_date=args.repair_date, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
