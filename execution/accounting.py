from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

from config import STARTING_CASH
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import load_trade_ledger


LEDGER_FILE = "trade_ledger_v1.csv"
TRADE_JOURNAL_FILE = "trade_journal_v3.csv"


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric(value, default=0.0):
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return default
    return float(value)


def ledger_accounting(events):
    cashflows = []
    open_lots = defaultdict(deque)
    closed_rows = []
    orphan_sells = []

    for _, row in events.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        action = str(row["action"]).strip().upper()
        shares = numeric(row.get("shares"))
        price = numeric(row.get("price"))
        value = numeric(row.get("value"))
        fees = numeric(row.get("fees"))

        if action == "BUY":
            cashflow = -(value + fees)
            lot = row.copy()
            lot["remaining_shares"] = shares
            lot["remaining_value"] = value
            lot["remaining_fees"] = fees
            open_lots[ticker].append(lot)
        else:
            cashflow = value - fees
            remaining_sell_shares = shares
            while remaining_sell_shares > 1e-12 and open_lots[ticker]:
                lot = open_lots[ticker][0]
                lot_shares = numeric(lot.get("remaining_shares"))
                matched_shares = min(lot_shares, remaining_sell_shares)
                original_lot_shares = numeric(lot.get("shares"))
                original_sell_shares = shares
                buy_fee_share = (
                    numeric(lot.get("fees")) * matched_shares / original_lot_shares
                    if original_lot_shares
                    else 0.0
                )
                sell_fee_share = (
                    fees * matched_shares / original_sell_shares
                    if original_sell_shares
                    else 0.0
                )
                buy_cost = numeric(lot.get("price")) * matched_shares
                sell_proceeds = price * matched_shares
                closed_rows.append(
                    {
                        "ticker": ticker,
                        "entry_event_id": lot.get("event_id", ""),
                        "exit_event_id": row.get("event_id", ""),
                        "shares": matched_shares,
                        "buy_cost": buy_cost,
                        "sell_proceeds": sell_proceeds,
                        "buy_fees": buy_fee_share,
                        "sell_fees": sell_fee_share,
                        "realised_pnl": (
                            sell_proceeds
                            - buy_cost
                            - buy_fee_share
                            - sell_fee_share
                        ),
                    }
                )
                lot["remaining_shares"] = lot_shares - matched_shares
                lot["remaining_value"] = (
                    numeric(lot.get("price")) * numeric(lot.get("remaining_shares"))
                )
                lot["remaining_fees"] = (
                    numeric(lot.get("fees"))
                    * numeric(lot.get("remaining_shares"))
                    / original_lot_shares
                    if original_lot_shares
                    else 0.0
                )
                remaining_sell_shares -= matched_shares
                if numeric(lot.get("remaining_shares")) <= 1e-12:
                    open_lots[ticker].popleft()

            if remaining_sell_shares > 1e-12:
                orphan_sells.append(
                    {
                        "ticker": ticker,
                        "event_id": row.get("event_id", ""),
                        "legacy_row_number": row.get("legacy_row_number", ""),
                        "unmatched_shares": remaining_sell_shares,
                    }
                )

        cashflows.append(
            {
                "event_id": row.get("event_id", ""),
                "timestamp": row.get("timestamp", ""),
                "ticker": ticker,
                "action": action,
                "value": value,
                "fees": fees,
                "currency": row.get("currency", ""),
                "cashflow": cashflow,
            }
        )

    open_rows = []
    for ticker, lots in open_lots.items():
        for lot in lots:
            remaining_shares = numeric(lot.get("remaining_shares"))
            if remaining_shares <= 1e-12:
                continue
            open_rows.append(
                {
                    "ticker": ticker,
                    "event_id": lot.get("event_id", ""),
                    "timestamp": lot.get("timestamp", ""),
                    "shares": remaining_shares,
                    "entry_price": numeric(lot.get("price")),
                    "cost_basis": numeric(lot.get("remaining_value")),
                    "allocated_fees": numeric(lot.get("remaining_fees")),
                    "currency": lot.get("currency", ""),
                }
            )

    cashflow_frame = pd.DataFrame(cashflows)
    closed_frame = pd.DataFrame(closed_rows)
    open_frame = pd.DataFrame(open_rows)
    orphan_frame = pd.DataFrame(orphan_sells)

    expected_cash = float(STARTING_CASH)
    if not cashflow_frame.empty:
        expected_cash += float(cashflow_frame["cashflow"].sum())

    realised_pnl = (
        float(closed_frame["realised_pnl"].sum())
        if not closed_frame.empty
        else 0.0
    )
    open_cost = (
        float(open_frame["cost_basis"].sum())
        if not open_frame.empty
        else 0.0
    )

    return {
        "cashflows": cashflow_frame,
        "closed_trades": closed_frame,
        "open_lots": open_frame,
        "orphan_sells": orphan_frame,
        "expected_cash": expected_cash,
        "realised_pnl": realised_pnl,
        "open_cost_basis": open_cost,
    }


def legacy_accounting_from_journal(portfolio=None, journal=None, base_dir="."):
    if journal is None:
        journal = read_csv(Path(base_dir) / TRADE_JOURNAL_FILE)
    if portfolio is None:
        portfolio = pd.DataFrame()

    realised_pnl = 0.0
    if not journal.empty and "pnl" in journal.columns:
        realised_pnl = float(
            pd.to_numeric(journal["pnl"], errors="coerce").fillna(0.0).sum()
        )

    invested = 0.0
    if not portfolio.empty and "position_value" in portfolio.columns:
        invested = float(
            pd.to_numeric(portfolio["position_value"], errors="coerce")
            .fillna(0.0)
            .sum()
        )

    return {
        "cash": float(STARTING_CASH) - invested + realised_pnl,
        "realised_pnl": realised_pnl,
        "open_cost_basis": invested,
        "source": "legacy_journal_fallback",
    }


def authoritative_ledger_accounting(base_dir="."):
    ledger = load_trade_ledger(Path(base_dir) / LEDGER_FILE)
    events = clean_ledger_events(ledger)
    if ledger.empty or events.empty:
        return None

    accounting = ledger_accounting(events)
    accounting["source"] = "trade_ledger_v1.csv"
    accounting["clean_ledger_events"] = int(len(events))
    return accounting


def market_value_from_holdings(holdings):
    if holdings is None or holdings.empty or "market_value" not in holdings.columns:
        return 0.0
    return float(
        pd.to_numeric(holdings["market_value"], errors="coerce")
        .fillna(0.0)
        .sum()
    )


def broker_values_from_ledger_and_holdings(
    *,
    holdings,
    portfolio=None,
    journal=None,
    base_dir=".",
):
    accounting = authoritative_ledger_accounting(base_dir=base_dir)
    if accounting is None:
        fallback = legacy_accounting_from_journal(
            portfolio=portfolio,
            journal=journal,
            base_dir=base_dir,
        )
        cash = fallback["cash"]
        realised_pnl = fallback["realised_pnl"]
        open_cost_basis = fallback["open_cost_basis"]
        source = fallback["source"]
        orphan_sell_count = 0
        clean_ledger_events = 0
    else:
        if not accounting["orphan_sells"].empty:
            raise ValueError("Clean trade ledger contains orphan SELL events.")
        cash = accounting["expected_cash"]
        realised_pnl = accounting["realised_pnl"]
        open_cost_basis = accounting["open_cost_basis"]
        source = accounting["source"]
        orphan_sell_count = int(len(accounting["orphan_sells"]))
        clean_ledger_events = int(accounting["clean_ledger_events"])

    positions_value = market_value_from_holdings(holdings)
    unrealised_pnl = positions_value - open_cost_basis

    return {
        "cash": float(cash),
        "buying_power": float(cash),
        "positions_value": float(positions_value),
        "portfolio_value": float(cash + positions_value),
        "realised_pnl": float(realised_pnl),
        "unrealised_pnl": float(unrealised_pnl),
        "open_cost_basis": float(open_cost_basis),
        "source": source,
        "clean_ledger_events": clean_ledger_events,
        "orphan_sell_count": orphan_sell_count,
    }


def broker_frame(values):
    return pd.DataFrame(
        [
            {
                "cash": float(values["cash"]),
                "buying_power": float(values["buying_power"]),
                "positions_value": float(values["positions_value"]),
                "portfolio_value": float(values["portfolio_value"]),
                "realised_pnl": float(values["realised_pnl"]),
                "unrealised_pnl": float(values["unrealised_pnl"]),
            }
        ]
    )


BROKER_COLUMNS = [
    "cash",
    "buying_power",
    "positions_value",
    "portfolio_value",
    "realised_pnl",
    "unrealised_pnl",
]


def broker_row(frame):
    if frame is None or frame.empty:
        return {column: 0.0 for column in BROKER_COLUMNS}

    row = frame.iloc[0].to_dict()
    return {column: numeric(row.get(column)) for column in BROKER_COLUMNS}


def broker_differences(before, target, tolerance=0.01):
    differences = {}
    for column in BROKER_COLUMNS:
        before_value = float(before.get(column, 0.0))
        target_value = float(target[column])
        difference = target_value - before_value
        if abs(difference) > tolerance:
            differences[column] = {
                "before": before_value,
                "after": target_value,
                "difference": difference,
            }
    return differences


def reconcile_broker_account_file(base_dir=".", tolerance=0.01):
    base_path = Path(base_dir)
    broker_path = base_path / "broker_account.csv"
    holdings = read_csv(base_path / "holdings_report.csv")
    existing = read_csv(broker_path)
    before = broker_row(existing)
    target = broker_values_from_ledger_and_holdings(
        holdings=holdings,
        base_dir=base_path,
    )
    differences = broker_differences(before, target, tolerance=tolerance)

    if differences:
        broker_frame(target).to_csv(broker_path, index=False)

    return {
        "changed": bool(differences),
        "differences": differences,
        "before": before,
        "after": {column: target[column] for column in BROKER_COLUMNS},
        "source": target.get("source"),
        "clean_ledger_events": target.get("clean_ledger_events", 0),
        "open_cost_basis": target.get("open_cost_basis", 0.0),
        "orphan_sell_count": target.get("orphan_sell_count", 0),
    }
