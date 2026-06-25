import pandas as pd


def build_trade_audit_trail(trade_journal):
    if trade_journal is None or trade_journal.empty:
        return pd.DataFrame()

    trades = trade_journal.copy()

    # Detect column names
    time_col = "timestamp" if "timestamp" in trades.columns else "date"
    symbol_col = "symbol" if "symbol" in trades.columns else "ticker"
    qty_col = "shares" if "shares" in trades.columns else "quantity"

    # Convert dates
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

                audit_rows.append({
                    "symbol": symbol,
                    "open_time": open_trade[time_col],
                    "close_time": row[time_col],
                    "holding_period": str(row[time_col] - open_trade[time_col]),
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "shares": shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "open_reason": open_trade["reason"],
                    "close_reason": row["reason"],
                })

                open_trade = None

    return pd.DataFrame(audit_rows)