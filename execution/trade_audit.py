from collections import defaultdict, deque

import pandas as pd

from execution.trade_ledger import load_trade_ledger


VALID_LEDGER_STATUSES = {"RECORDED", "EXECUTED", "FILLED"}
INVALID_MIGRATION_STATUSES = {"QUARANTINED", "REJECTED", "INVALID"}


def safe_get(row, column, default=""):
    if column in row.index:
        value = row.get(column, default)

        if pd.isna(value):
            return default

        return value

    return default


def legacy_row_number_for_audit(row):
    source = str(safe_get(row, "source", "")).strip()
    if source != "legacy_migration":
        return ""
    return safe_get(row, "legacy_row_number", "")


def clean_ledger_events(ledger):
    if ledger is None or ledger.empty:
        return pd.DataFrame()

    events = ledger.copy().reset_index(drop=True)
    events["_ledger_order"] = range(len(events))
    for column in ["ticker", "action", "status", "migration_status"]:
        if column not in events.columns:
            events[column] = ""
        events[column] = events[column].fillna("").astype(str).str.strip()

    events["action"] = events["action"].str.upper()
    events["status"] = events["status"].str.upper()
    events["migration_status"] = events["migration_status"].str.upper()

    events = events[
        events["action"].isin(["BUY", "SELL"])
        & events["status"].isin(VALID_LEDGER_STATUSES)
        & ~events["migration_status"].isin(INVALID_MIGRATION_STATUSES)
        & ~events["migration_status"].str.contains("QUARANTIN", na=False)
    ].copy()

    for column in ["shares", "price", "value", "fees", "pnl", "pnl_percent"]:
        if column not in events.columns:
            events[column] = 0.0
        events[column] = pd.to_numeric(events[column], errors="coerce").fillna(0.0)

    events = events[
        (events["shares"] > 0)
        & (events["price"] > 0)
        & (events["value"] > 0)
    ].copy()

    if "timestamp" not in events.columns:
        events["timestamp"] = ""
    events["audit_time"] = pd.to_datetime(
        events["timestamp"],
        format="mixed",
        errors="coerce",
    )
    events = events.dropna(subset=["audit_time"])
    return events.sort_values(["ticker", "audit_time", "_ledger_order"])


def build_trade_audit_trail_from_ledger(ledger):
    events = clean_ledger_events(ledger)
    if events.empty:
        return pd.DataFrame()

    open_lots = defaultdict(deque)
    audit_rows = []

    for _, row in events.iterrows():
        ticker = row["ticker"]
        action = row["action"]

        if action == "BUY":
            lot = row.copy()
            lot["remaining_shares"] = float(row["shares"])
            open_lots[ticker].append(lot)
            continue

        remaining_sell_shares = float(row["shares"])
        while remaining_sell_shares > 1e-12 and open_lots[ticker]:
            open_trade = open_lots[ticker][0]
            matched_shares = min(
                float(open_trade["remaining_shares"]),
                remaining_sell_shares,
            )
            buy_price = float(open_trade["price"])
            sell_price = float(row["price"])
            entry_fees = float(open_trade.get("fees", 0.0) or 0.0)
            exit_fees = float(row.get("fees", 0.0) or 0.0)
            entry_fee_share = (
                entry_fees * matched_shares / float(open_trade["shares"])
                if float(open_trade["shares"])
                else 0.0
            )
            exit_fee_share = (
                exit_fees * matched_shares / float(row["shares"])
                if float(row["shares"])
                else 0.0
            )
            pnl = (
                (sell_price - buy_price) * matched_shares
                - entry_fee_share
                - exit_fee_share
            )
            pnl_pct = (
                pnl / (buy_price * matched_shares)
                if buy_price and matched_shares
                else 0.0
            )
            holding_period = row["audit_time"] - open_trade["audit_time"]

            audit_rows.append(
                {
                    "symbol": ticker,
                    "open_time": open_trade["audit_time"],
                    "close_time": row["audit_time"],
                    "holding_period": str(holding_period),
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "shares": matched_shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "open_reason": safe_get(open_trade, "reason", "SIGNAL ENTRY"),
                    "close_reason": safe_get(row, "reason", "SIGNAL EXIT"),
                    "entry_action": "BUY",
                    "entry_value": buy_price * matched_shares,
                    "entry_time": safe_get(open_trade, "trade_time", ""),
                    "entry_price": buy_price,
                    "entry_shares": matched_shares,
                    "exit_action": "SELL",
                    "exit_value": sell_price * matched_shares,
                    "exit_time": safe_get(row, "trade_time", ""),
                    "exit_price": sell_price,
                    "exit_shares": matched_shares,
                    "entry_rule": "BUY event recorded in trade ledger",
                    "exit_rule": safe_get(row, "reason", "SIGNAL EXIT"),
                    "trade_result": (
                        "WIN"
                        if pnl > 0
                        else "LOSS"
                        if pnl < 0
                        else "FLAT"
                    ),
                    "entry_signal": "",
                    "exit_signal": "",
                    "entry_weight": "",
                    "entry_stop_loss": "",
                    "entry_take_profit": "",
                    "entry_cash": "",
                    "entry_portfolio_value": "",
                    "exit_cash": "",
                    "exit_portfolio_value": "",
                    "asset_type": "",
                    "strategy": "Momentum",
                    "notes": "Source: trade_ledger_v1.csv",
                    "entry_event_id": safe_get(open_trade, "event_id", ""),
                    "exit_event_id": safe_get(row, "event_id", ""),
                    "entry_legacy_row_number": legacy_row_number_for_audit(open_trade),
                    "exit_legacy_row_number": legacy_row_number_for_audit(row),
                    "source": "trade_ledger_v1.csv",
                }
            )

            open_trade["remaining_shares"] = (
                float(open_trade["remaining_shares"]) - matched_shares
            )
            remaining_sell_shares -= matched_shares
            if float(open_trade["remaining_shares"]) <= 1e-12:
                open_lots[ticker].popleft()

    return pd.DataFrame(audit_rows)


def ledger_open_positions(ledger):
    events = clean_ledger_events(ledger)
    if events.empty:
        return pd.DataFrame(columns=["ticker", "open_shares", "open_lots"])

    open_lots = defaultdict(deque)
    for _, row in events.iterrows():
        ticker = row["ticker"]
        if row["action"] == "BUY":
            lot = row.copy()
            lot["remaining_shares"] = float(row["shares"])
            open_lots[ticker].append(lot)
            continue

        remaining_sell_shares = float(row["shares"])
        while remaining_sell_shares > 1e-12 and open_lots[ticker]:
            open_trade = open_lots[ticker][0]
            matched = min(float(open_trade["remaining_shares"]), remaining_sell_shares)
            open_trade["remaining_shares"] = float(open_trade["remaining_shares"]) - matched
            remaining_sell_shares -= matched
            if float(open_trade["remaining_shares"]) <= 1e-12:
                open_lots[ticker].popleft()

    rows = []
    for ticker, lots in open_lots.items():
        open_shares = sum(float(lot["remaining_shares"]) for lot in lots)
        if open_shares > 1e-12:
            rows.append(
                {
                    "ticker": ticker,
                    "open_shares": open_shares,
                    "open_lots": len(lots),
                }
            )
    return pd.DataFrame(rows)


def build_authoritative_trade_audit(legacy_journal=None, ledger_path="trade_ledger_v1.csv"):
    ledger = load_trade_ledger(ledger_path)
    audit = build_trade_audit_trail_from_ledger(ledger)
    if not audit.empty or not ledger.empty:
        return audit
    return build_trade_audit_trail(legacy_journal)


def build_trade_audit_trail(trade_journal):
    if trade_journal is None or trade_journal.empty:
        return pd.DataFrame()

    trades = trade_journal.copy()

    # Detect column names
    symbol_col = "symbol" if "symbol" in trades.columns else "ticker"
    qty_col = "shares" if "shares" in trades.columns else "quantity"

    # Build a datetime from date plus time when time exists.
    if "timestamp" in trades.columns:
        trades["audit_time"] = pd.to_datetime(
            trades["timestamp"],
            format="mixed",
            errors="coerce"
        )
    else:
        date_text = trades["date"].astype(str).str.strip()

        if "time" in trades.columns:
            time_text = trades["time"].fillna("").astype(str).str.strip()
            missing_time = time_text.str.lower().isin(["", "nan", "nat", "none"])
            datetime_text = date_text.where(missing_time, date_text + " " + time_text)
        else:
            datetime_text = date_text

        trades["audit_time"] = pd.to_datetime(
            datetime_text,
            format="mixed",
            errors="coerce"
        )

    trades = trades.dropna(subset=["audit_time"])
    trades = trades.sort_values([symbol_col, "audit_time"])

    audit_rows = []

    for symbol, group in trades.groupby(symbol_col):

        open_trade = None

        for _, row in group.iterrows():

            action = str(row["action"]).upper()

            if action == "BUY":
                open_trade = row

            elif action == "SELL" and open_trade is not None:

                buy_price = float(open_trade["price"])
                sell_price = float(row["price"])
                shares = float(open_trade[qty_col])

                pnl = (sell_price - buy_price) * shares
                pnl_pct = ((sell_price - buy_price) / buy_price) * 100

                audit_rows.append({
                    # Core trade details
                    "symbol": symbol,
                    "open_time": open_trade["audit_time"],
                    "close_time": row["audit_time"],
                    "holding_period": str(
                        row["audit_time"] - open_trade["audit_time"]
                    ),
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "shares": shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "open_reason": safe_get(open_trade, "reason", "SIGNAL ENTRY"),
                    "close_reason": safe_get(row, "reason", "SIGNAL EXIT"),

                    # Entry snapshot from journal if available
                    "entry_action": safe_get(open_trade, "action", "BUY"),
                    "entry_value": safe_get(open_trade, "value", buy_price * shares),
                    "entry_time": safe_get(open_trade, "time", ""),
                    "entry_price": buy_price,
                    "entry_shares": shares,

                    # Exit snapshot from journal if available
                    "exit_action": safe_get(row, "action", "SELL"),
                    "exit_value": safe_get(row, "value", sell_price * shares),
                    "exit_time": safe_get(row, "time", ""),
                    "exit_price": sell_price,
                    "exit_shares": safe_get(row, qty_col, shares),

                    # Replay labels
                    "entry_rule": "BUY signal generated",
                    "exit_rule": safe_get(row, "reason", "SIGNAL EXIT"),
                    "trade_result": (
                        "WIN"
                        if pnl > 0
                        else "LOSS"
                        if pnl < 0
                        else "FLAT"
                    ),

                    # Future AI/research fields
                    "entry_signal": "",
                    "exit_signal": "",
                    "entry_weight": "",
                    "entry_stop_loss": "",
                    "entry_take_profit": "",
                    "entry_cash": "",
                    "entry_portfolio_value": "",
                    "exit_cash": "",
                    "exit_portfolio_value": "",
                    "asset_type": "",
                    "strategy": "Momentum",
                    "notes": "",
                })

                open_trade = None

    return pd.DataFrame(audit_rows)
