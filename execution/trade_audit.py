import pandas as pd


def safe_get(row, column, default=""):
    if column in row.index:
        value = row.get(column, default)

        if pd.isna(value):
            return default

        return value

    return default


def build_trade_audit_trail(trade_journal):
    if trade_journal is None or trade_journal.empty:
        return pd.DataFrame()

    trades = trade_journal.copy()

    time_col = "timestamp" if "timestamp" in trades.columns else "date"
    symbol_col = "symbol" if "symbol" in trades.columns else "ticker"
    qty_col = "shares" if "shares" in trades.columns else "quantity"

    trades[time_col] = pd.to_datetime(
        trades[time_col],
        format="mixed",
        errors="coerce"
    )

    trades = trades.dropna(subset=[time_col])
    trades = trades.sort_values([symbol_col, time_col])

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

                open_time = open_trade[time_col]
                close_time = row[time_col]

                audit_rows.append({
                    # Core trade details
                    "symbol": symbol,
                    "open_time": open_time,
                    "close_time": close_time,
                    "holding_period": str(close_time - open_time),
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