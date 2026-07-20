from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import ledger_accounting
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import (
    LEDGER_COLUMNS,
    build_trade_event,
    load_trade_ledger,
    prepare_trade_ledger_append,
)

SHARE_TOLERANCE = 1e-9
VALUE_TOLERANCE = 1e-6


def read_csv(path):
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def norm(value):
    return "" if value is None or pd.isna(value) else str(value).strip().upper()


def number(value):
    parsed = pd.to_numeric(value, errors="coerce")
    return 0.0 if pd.isna(parsed) else float(parsed)


def positions(frame, shares_column="shares"):
    if frame.empty or "ticker" not in frame or shares_column not in frame:
        return {}
    data = frame.copy()
    data["_ticker"] = data["ticker"].map(norm)
    data["_shares"] = pd.to_numeric(data[shares_column], errors="coerce").fillna(0)
    return data[data["_ticker"].ne("")].groupby("_ticker")["_shares"].sum().to_dict()


def matching_rows(frame, *, ticker, action, shares, price=None, value=None, date=None):
    if frame.empty or not {"ticker", "action", "shares"}.issubset(frame.columns):
        return frame.iloc[0:0].copy()
    rows = frame.copy()
    rows["_row_number"] = rows.index + 2
    mask = rows["ticker"].map(norm).eq(ticker) & rows["action"].map(norm).eq(action)
    mask &= pd.to_numeric(rows["shares"], errors="coerce").sub(shares).abs().le(SHARE_TOLERANCE)
    if price is not None:
        mask &= pd.to_numeric(rows.get("price"), errors="coerce").sub(price).abs().le(VALUE_TOLERANCE)
    if value is not None:
        value_column = "value" if "value" in rows else "position_value"
        mask &= pd.to_numeric(rows.get(value_column), errors="coerce").sub(value).abs().le(VALUE_TOLERANCE)
    if date is not None:
        source = rows["date"] if "date" in rows else rows.get("timestamp")
        mask &= pd.to_datetime(source, errors="coerce").dt.date.eq(pd.Timestamp(date).date())
    return rows[mask].copy()


def plan_reconciliation(base_dir):
    base = Path(base_dir)
    paths = {
        "ledger": base / "trade_ledger_v1.csv",
        "portfolio": base / "paper_portfolio_v3.csv",
        "journal": base / "trade_journal_v3.csv",
        "transactions": base / "trade_transactions_v1.csv",
        "snapshots": base / "trade_snapshots.csv",
    }
    ledger = load_trade_ledger(paths["ledger"])
    clean = clean_ledger_events(ledger)
    accounting = ledger_accounting(clean)
    portfolio = read_csv(paths["portfolio"])
    ledger_positions = positions(accounting["open_lots"])
    portfolio_positions = positions(portfolio)
    mismatches = {
        ticker: {"ledger": float(ledger_positions.get(ticker, 0)), "portfolio": float(portfolio_positions.get(ticker, 0))}
        for ticker in sorted(set(ledger_positions) | set(portfolio_positions))
        if abs(float(ledger_positions.get(ticker, 0)) - float(portfolio_positions.get(ticker, 0))) > SHARE_TOLERANCE
    }
    report = {"status": "consistent" if not mismatches else "refused", "mismatches": mismatches, "repairs": []}
    if not mismatches:
        return ledger, [], report

    journal = read_csv(paths["journal"])
    transactions = read_csv(paths["transactions"])
    snapshots = read_csv(paths["snapshots"])
    repairs = []
    for ticker, mismatch in mismatches.items():
        if mismatch["portfolio"] != 0 or mismatch["ledger"] <= 0:
            report["reason"] = f"{ticker}: only a ledger-open/portfolio-absent mismatch is repairable"
            return ledger, [], report
        lots = accounting["open_lots"][accounting["open_lots"]["ticker"].map(norm).eq(ticker)]
        if len(lots) != 1:
            report["reason"] = f"{ticker}: expected exactly one open ledger lot, found {len(lots)}"
            return ledger, [], report
        lot = lots.iloc[0]
        journal_candidates = matching_rows(journal, ticker=ticker, action="SELL", shares=number(lot["shares"]))
        journal_candidates = journal_candidates[
            pd.to_datetime(journal_candidates["date"], errors="coerce") >= pd.Timestamp(lot["timestamp"])
        ]
        if journal_candidates.empty:
            buy = clean[clean["event_id"].astype(str).eq(str(lot["event_id"]))].iloc[0]
            buy_date, buy_price, buy_value = buy["trade_date"], number(buy["price"]), number(buy["value"])
            journal_buy = matching_rows(journal, ticker=ticker, action="BUY", shares=number(lot["shares"]), price=buy_price, value=buy_value, date=buy_date)
            tx_buy = matching_rows(transactions, ticker=ticker, action="BUY", shares=number(lot["shares"]), price=buy_price, value=buy_value, date=buy_date)
            snap_buy = matching_rows(snapshots.rename(columns={"event": "action"}), ticker=ticker, action="BUY", shares=number(lot["shares"]), price=buy_price, value=buy_value, date=buy_date)
            if len(journal_buy) != 1 or len(tx_buy) != 1 or len(snap_buy) != 1:
                report["reason"] = f"{ticker}: open BUY corroboration is ambiguous (journal={len(journal_buy)}, transactions={len(tx_buy)}, snapshots={len(snap_buy)})"
                return ledger, [], report
            snapshot = snap_buy.iloc[0]
            row = {
                "ticker": ticker, "entry_date": str(buy_date), "entry_price": buy_price,
                "shares": number(lot["shares"]), "position_value": buy_value,
                "stop_loss": number(snapshot.get("stop_loss")), "take_profit": number(snapshot.get("take_profit")),
                "signal_exit_count": 0, "last_signal_exit_check": "",
            }
            repairs.append({"kind": "restore_portfolio_open_lot", "row": row})
            report["repairs"].append({
                "ticker": ticker, "action": "restore_portfolio_open_lot", "open_buy_event_id": lot["event_id"],
                "journal_row": int(journal_buy.iloc[0]["_row_number"]), "transaction_row": int(tx_buy.iloc[0]["_row_number"]),
                "snapshot_row": int(snapshot["_row_number"]), "portfolio_row": row,
            })
            continue
        if len(journal_candidates) != 1:
            report["reason"] = f"{ticker}: expected at most one later matching journal SELL, found {len(journal_candidates)}"
            return ledger, [], report
        sell = journal_candidates.iloc[0]
        sell_date, sell_price, sell_value = sell["date"], number(sell["price"]), number(sell["value"])
        tx = matching_rows(transactions, ticker=ticker, action="SELL", shares=number(lot["shares"]), price=sell_price, value=sell_value, date=sell_date)
        snap = matching_rows(snapshots.rename(columns={"event": "action"}), ticker=ticker, action="SELL", shares=number(lot["shares"]), price=sell_price, value=sell_value, date=sell_date)
        if len(tx) != 1 or len(snap) != 1:
            report["reason"] = f"{ticker}: SELL corroboration is ambiguous (transactions={len(tx)}, snapshots={len(snap)})"
            return ledger, [], report
        snapshot = snap.iloc[0]
        timestamp = str(snapshot["timestamp"])
        event = build_trade_event(
            timestamp=timestamp, trade_date=pd.Timestamp(sell_date).strftime("%Y-%m-%d"),
            trade_time=pd.Timestamp(timestamp).strftime("%H:%M:%S"), ticker=ticker,
            action="SELL", shares=number(lot["shares"]), price=sell_price, value=sell_value,
            currency=lot.get("currency", "UNKNOWN"), reason=str(sell.get("reason", "RECONCILED EXIT")),
            legacy_trade_id=str(snapshot.get("trade_id", "")), run_id="missing_ledger_exit_reconciliation_v1",
            position_id=str(clean.loc[clean["event_id"].eq(lot["event_id"]), "position_id"].iloc[0]),
            pnl=number(sell.get("pnl")), pnl_percent=number(sell.get("pnl_percent")),
            source="ledger_exit_reconciliation", migration_status="RECONCILED_MISSING_LIVE_SELL",
            legacy_source_file="trade_journal_v3.csv", legacy_row_number=int(sell["_row_number"]),
        )
        repairs.append({"kind": "append_missing_sell", "event": event})
        report["repairs"].append({
            "ticker": ticker, "open_buy_event_id": lot["event_id"],
            "journal_row": int(sell["_row_number"]), "transaction_row": int(tx.iloc[0]["_row_number"]),
            "snapshot_row": int(snapshot["_row_number"]), "sell_event": event,
        })
    report["status"] = "repairable"
    return ledger, repairs, report


def run(base_dir, apply=False):
    base = Path(base_dir)
    lock_path = None if base.resolve() == ROOT.resolve() else base / ".reconciliation.lock"
    ledger, repairs, report = plan_reconciliation(base)
    if report["status"] == "refused":
        print(report.get("reason", "ambiguous mismatch"))
        return 2
    if repairs:
        if not apply:
            print(json.dumps(report, indent=2, default=str))
            print("dry-run only; repair required; rerun with --apply")
            return 1
        ledger_events = [repair["event"] for repair in repairs if repair["kind"] == "append_missing_sell"]
        updated = prepare_trade_ledger_append(ledger_events, path=base / "trade_ledger_v1.csv")
        frames = {base / "trade_ledger_v1.csv": updated[LEDGER_COLUMNS]}
        portfolio_repairs = [repair["row"] for repair in repairs if repair["kind"] == "restore_portfolio_open_lot"]
        if portfolio_repairs:
            portfolio_path = base / "paper_portfolio_v3.csv"
            portfolio = read_csv(portfolio_path)
            for row in portfolio_repairs:
                if norm(row["ticker"]) in set(portfolio.get("ticker", pd.Series(dtype=str)).map(norm)):
                    raise RuntimeError(f"Refusing duplicate portfolio repair for {row['ticker']}")
            portfolio = pd.concat([portfolio, pd.DataFrame(portfolio_repairs)], ignore_index=True)
            frames[portfolio_path] = portfolio
        atomic_write_csv_frames(frames, lock_path=lock_path)
        report["status"] = "repaired"
    if apply:
        report_path = base / "data" / "missing_ledger_exit_reconciliation.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(report, report_path, json_kwargs={"indent": 2, "default": str}, lock_path=lock_path)
        print(f"status={report['status']} repairs={len(repairs)} report={report_path}")
    else:
        print(json.dumps(report, indent=2, default=str))
        print("dry-run only; no files changed")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Reconcile a provably missing ledger SELL")
    parser.add_argument("--base-dir", default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(args.base_dir, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
