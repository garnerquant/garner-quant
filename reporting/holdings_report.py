import pandas as pd


def create_holdings_report(portfolio, prices):
    latest_date = prices.index[-1]
    latest_prices = prices.loc[latest_date]

    rows = []

    for _, position in portfolio.iterrows():
        ticker = position["ticker"]
        shares = position["shares"]
        entry_price = position["entry_price"]
        current_price = latest_prices[ticker]

        market_value = shares * current_price
        cost_basis = shares * entry_price
        unrealised_pnl = market_value - cost_basis
        unrealised_pnl_percent = (current_price / entry_price) - 1

        rows.append({
            "date": latest_date,
            "ticker": ticker,
            "shares": shares,
            "entry_price": entry_price,
            "current_price": current_price,
            "market_value": market_value,
            "unrealised_pnl": unrealised_pnl,
            "unrealised_pnl_percent": unrealised_pnl_percent
        })

    return pd.DataFrame(rows)


def print_holdings_report(holdings):
    print("\n===== HOLDINGS REPORT =====")

    if len(holdings) == 0:
        print("No open positions.")
        return

    for _, row in holdings.iterrows():
        print(
            f"{row['ticker']} | "
            f"Shares: {row['shares']:.4f} | "
            f"Market Value: £{row['market_value']:,.2f} | "
            f"PnL: £{row['unrealised_pnl']:,.2f} "
            f"({row['unrealised_pnl_percent']:.2%})"
        )