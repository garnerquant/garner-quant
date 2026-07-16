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

from execution.accounting import ledger_accounting
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from execution.portfolio_manager import PORTFOLIO_COLUMNS
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import load_trade_ledger
from runtime.locks import acquire_execution_lock


SHARE_TOLERANCE = 1e-9
VALUE_TOLERANCE = 1e-6
REPORT_NAME = "portfolio_projection_rebuild_report.json"
SOURCE_FILES = (
    "trade_ledger_v1.csv",
    "trade_snapshots.csv",
)
VALUATION_PHASE_DECLARED_OUTPUTS = (
    "paper_portfolio_v3.csv",
    "holdings_report.csv",
    "broker_account.csv",
    "portfolio_v2.csv",
    "paper_30_day_tracker.csv",
)


class ProjectionRebuildError(RuntimeError):
    pass


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def finite_positive(value, field: str) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed) or not math.isfinite(float(parsed)) or float(parsed) <= 0:
        raise ProjectionRebuildError(f"{field} must be finite and positive")
    return float(parsed)


def frame_csv_text(frame: pd.DataFrame) -> str:
    buffer = StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n")
    return buffer.getvalue()


def proposed_diff(before_path: Path, after: pd.DataFrame) -> str:
    before = before_path.read_text(encoding="utf-8-sig").splitlines(keepends=True) if before_path.exists() else []
    after_lines = frame_csv_text(after).splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after_lines, fromfile=str(before_path), tofile=str(before_path) + " (rebuilt)"))


def position_map(frame: pd.DataFrame, shares_column="shares") -> dict[str, float]:
    if frame.empty:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data[shares_column] = pd.to_numeric(data[shares_column], errors="coerce")
    return data.groupby("ticker")[shares_column].sum().to_dict()


def build_projection(base_dir) -> tuple[pd.DataFrame, dict]:
    base = Path(base_dir)
    ledger_path = base / "trade_ledger_v1.csv"
    snapshots_path = base / "trade_snapshots.csv"
    ledger = load_trade_ledger(ledger_path)
    if ledger.empty:
        raise ProjectionRebuildError("authoritative trade ledger is empty")
    ids = ledger["event_id"].fillna("").astype(str).str.strip()
    if ids.eq("").any() or ids.duplicated().any():
        raise ProjectionRebuildError("ledger event IDs must be present and unique")

    clean = clean_ledger_events(ledger)
    accounting = ledger_accounting(clean)
    if not accounting["orphan_sells"].empty:
        raise ProjectionRebuildError("clean ledger contains orphan SELL events")
    open_lots = accounting["open_lots"].copy()
    if open_lots.empty:
        projection = pd.DataFrame(columns=PORTFOLIO_COLUMNS)
        return projection, {"positions": [], "open_cost_basis": 0.0}
    counts = open_lots.groupby("ticker").size()
    if (counts > 1).any():
        raise ProjectionRebuildError("multiple unresolved open lots for one ticker are unsupported")

    snapshots = read_csv(snapshots_path)
    required_snapshot_columns = {"trade_id", "event", "ticker", "timestamp", "price", "shares", "position_value", "stop_loss", "take_profit"}
    if not required_snapshot_columns.issubset(snapshots.columns):
        missing = sorted(required_snapshot_columns - set(snapshots.columns))
        raise ProjectionRebuildError("trade snapshots missing columns: " + ", ".join(missing))
    snapshots = snapshots.copy()
    snapshots["_row_number"] = snapshots.index + 2
    snapshots["_ticker"] = snapshots["ticker"].fillna("").astype(str).str.strip().str.upper()
    snapshots["_event"] = snapshots["event"].fillna("").astype(str).str.strip().str.upper()

    rows = []
    sources = []
    for _, lot in open_lots.sort_values("ticker").iterrows():
        ticker = str(lot["ticker"]).strip().upper()
        shares = finite_positive(lot["shares"], f"{ticker} shares")
        entry_price = finite_positive(lot["entry_price"], f"{ticker} entry price")
        cost_basis = finite_positive(lot["cost_basis"], f"{ticker} cost basis")
        timestamp = pd.to_datetime(lot["timestamp"], errors="coerce")
        if pd.isna(timestamp):
            raise ProjectionRebuildError(f"{ticker} ledger timestamp is invalid")
        matches = snapshots[
            snapshots["_ticker"].eq(ticker)
            & snapshots["_event"].eq("BUY")
            & pd.to_numeric(snapshots["shares"], errors="coerce").sub(shares).abs().le(SHARE_TOLERANCE)
            & pd.to_numeric(snapshots["price"], errors="coerce").sub(entry_price).abs().le(VALUE_TOLERANCE)
            & pd.to_numeric(snapshots["position_value"], errors="coerce").sub(cost_basis).abs().le(VALUE_TOLERANCE)
            & pd.to_datetime(snapshots["timestamp"], errors="coerce").eq(timestamp)
        ]
        if len(matches) != 1:
            raise ProjectionRebuildError(f"{ticker} requires exactly one matching BUY snapshot; found {len(matches)}")
        snapshot = matches.iloc[0]
        stop_loss = finite_positive(snapshot["stop_loss"], f"{ticker} stop loss")
        take_profit = finite_positive(snapshot["take_profit"], f"{ticker} take profit")
        row = {
            "ticker": ticker,
            "entry_date": timestamp.strftime("%Y-%m-%d"),
            "entry_price": entry_price,
            "shares": shares,
            "position_value": cost_basis,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "signal_exit_count": 0,
            "last_signal_exit_check": "",
        }
        rows.append(row)
        sources.append({
            "ticker": ticker,
            "ledger_event_id": str(lot["event_id"]),
            "snapshot_row_number": int(snapshot["_row_number"]),
            "snapshot_trade_id": str(snapshot["trade_id"]),
        })

    projection = pd.DataFrame(rows, columns=PORTFOLIO_COLUMNS)
    if projection["ticker"].duplicated().any():
        raise ProjectionRebuildError("reconstructed projection contains duplicate tickers")
    ledger_positions = position_map(open_lots)
    projection_positions = position_map(projection)
    equality = all(
        abs(float(ledger_positions.get(ticker, 0)) - float(projection_positions.get(ticker, 0))) <= SHARE_TOLERANCE
        for ticker in set(ledger_positions) | set(projection_positions)
    )
    if not equality:
        raise ProjectionRebuildError("reconstructed shares do not equal ledger open shares")
    return projection, {
        "positions": sources,
        "open_cost_basis": float(accounting["open_cost_basis"]),
        "validation": {
            "orphan_sells": 0,
            "unique_tickers": True,
            "ledger_portfolio_shares_equal": True,
            "position_count": len(projection),
        },
    }


def run(base_dir=ROOT, apply=False):
    base = Path(base_dir)
    portfolio_path = base / "paper_portfolio_v3.csv"
    report_path = base / "data" / REPORT_NAME
    projection, details = build_projection(base)
    diff = proposed_diff(portfolio_path, projection)
    print(diff if diff else "No portfolio projection changes proposed.")
    print(f"positions={len(projection)} open_cost_basis={details['open_cost_basis']:.12g}")
    if not apply:
        print("dry-run only; no files or reports written")
        return 0

    lock_path = base / "data" / "execution.lock"
    lock = acquire_execution_lock(lock_path, context="portfolio_projection_rebuild")
    if not lock.acquired:
        raise ProjectionRebuildError("another execution holds the runtime lock")
    try:
        before_hash = file_hash(portfolio_path)
        source_hashes_before = {name: file_hash(base / name) for name in SOURCE_FILES}
        atomic_write_csv_frames({portfolio_path: projection}, lock_path=lock_path)
        after_hash = file_hash(portfolio_path)
        source_hashes_after = {name: file_hash(base / name) for name in SOURCE_FILES}
        if source_hashes_before != source_hashes_after:
            raise ProjectionRebuildError("authoritative source files changed during rebuild")
        written = read_csv(portfolio_path)
        if position_map(written) != position_map(projection):
            raise ProjectionRebuildError("written portfolio failed exact share validation")
        report = {
            "repair_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "portfolio_file": "paper_portfolio_v3.csv",
            "before_hash": before_hash,
            "after_hash": after_hash,
            "source_hashes": source_hashes_after,
            "source_positions": details["positions"],
            "reconstructed_rows": projection.where(pd.notna(projection), None).to_dict(orient="records"),
            "validation": details["validation"],
            "operational_field_policy": {"signal_exit_count": 0, "last_signal_exit_check": "empty"},
            "valuation_outputs_refreshed": False,
            "note": "Accounting projection only; holdings and broker valuation were not refreshed.",
        }
        atomic_write_json(report, report_path, lock_path=lock_path)
        print(f"applied portfolio={portfolio_path} report={report_path}")
    finally:
        lock.release()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild paper portfolio projection from the clean trade ledger",
        epilog=(
            "Reserved Phase B interface: --refresh-valuation --prices-file PATH "
            "--max-price-age-seconds N. A future implementation must validate a "
            "complete timestamped/source-labelled price set and explicitly transact: "
            + ", ".join(VALUATION_PHASE_DECLARED_OUTPUTS)
        ),
    )
    parser.add_argument("--base-dir", default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh-valuation", action="store_true", help="Reserved Phase B interface; requires explicit complete prices file")
    parser.add_argument("--prices-file")
    parser.add_argument("--max-price-age-seconds", type=int)
    args = parser.parse_args()
    if args.refresh_valuation:
        parser.error("Phase B valuation refresh is not implemented; no market data will be fetched or written")
    if args.prices_file or args.max_price_age_seconds is not None:
        parser.error("--prices-file and --max-price-age-seconds require --refresh-valuation")
    return run(args.base_dir, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
