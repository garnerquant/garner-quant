import pandas as pd

from config import STARTING_CASH
from backtest.costs import apply_trading_costs
from risk.risk_manager import apply_drawdown_limit


def apply_stops(prices, risk_levels, weights):
    stop_loss = risk_levels["stop_loss"]
    take_profit = risk_levels["take_profit"]

    trade_log = []

    weights = weights.copy()

    for ticker in prices.columns:
        for i in range(1, len(prices)):
            date = prices.index[i]
            price = prices[ticker].iloc[i]
            stop = stop_loss[ticker].iloc[i]
            target = take_profit[ticker].iloc[i]

            currently_in_position = weights[ticker].iloc[i] > 0

            if currently_in_position and price <= stop:
                weights.loc[date, ticker] = 0

                trade_log.append({
                    "date": date,
                    "ticker": ticker,
                    "action": "SELL",
                    "reason": "STOP LOSS",
                    "price": price
                })

            elif currently_in_position and price >= target:
                weights.loc[date, ticker] = 0

                trade_log.append({
                    "date": date,
                    "ticker": ticker,
                    "action": "SELL",
                    "reason": "TAKE PROFIT",
                    "price": price
                })

    return weights, pd.DataFrame(trade_log)


def run_backtest(prices, weights, risk_levels=None):
    if risk_levels is not None:
        weights, trade_log = apply_stops(
            prices,
            risk_levels,
            weights
        )

        trade_log.to_csv("trade_log.csv", index=False)

    returns = prices.pct_change().fillna(0)

    portfolio = pd.DataFrame(index=prices.index)

    portfolio["daily_return"] = (
        weights.shift(1).fillna(0) * returns
    ).sum(axis=1)

    portfolio["equity"] = STARTING_CASH * (
        1 + portfolio["daily_return"]
    ).cumprod()

    portfolio["peak"] = portfolio["equity"].cummax()

    portfolio["drawdown"] = (
        portfolio["equity"] / portfolio["peak"]
    ) - 1

    portfolio = apply_trading_costs(portfolio, weights)

    portfolio = apply_drawdown_limit(portfolio)

    return portfolio