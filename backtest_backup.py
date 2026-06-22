from costs import apply_trading_costs
import pandas as pd

from config import STARTING_CASH
from risk import apply_drawdown_limit
from costs import apply_trading_costs

def run_backtest(prices, weights):
    returns = prices.pct_change().fillna(0)

    portfolio = pd.DataFrame(index=prices.index)

    portfolio["daily_return"] = (
        weights.shift(1).fillna(0) * returns
    ).sum(axis=1)

    portfolio["equity"] = STARTING_CASH * (1 + portfolio["daily_return"]).cumprod()
    portfolio["peak"] = portfolio["equity"].cummax()
    portfolio["drawdown"] = (portfolio["equity"] / portfolio["peak"]) - 1

    portfolio = apply_trading_costs(portfolio, weights)
    portfolio = apply_trading_costs(
        portfolio,
        weights
    )

    portfolio = apply_drawdown_limit(
        portfolio
    ) 

    return portfolio


def print_report(portfolio):
    final_value = portfolio["equity"].iloc[-1]
    total_return = (final_value / STARTING_CASH) - 1
    max_drawdown = portfolio["drawdown"].min()

    print("\n===== BOT PERFORMANCE =====")
    print(f"Starting cash: £{STARTING_CASH:,.2f}")
    print(f"Final value:   £{final_value:,.2f}")
    print(f"Total return:  {total_return:.2%}")
    print(f"Max drawdown:  {max_drawdown:.2%}")