import pandas as pd

from config import MAX_DRAWDOWN
from indicators.technical import atr


def build_risk_levels(prices, highs, lows):
    stop_losses = pd.DataFrame(
        index=prices.index,
        columns=prices.columns
    )

    take_profits = pd.DataFrame(
        index=prices.index,
        columns=prices.columns
    )

    for ticker in prices.columns:
        asset_atr = atr(
            highs[ticker],
            lows[ticker],
            prices[ticker]
        )

        stop_losses[ticker] = prices[ticker] - (2 * asset_atr)
        take_profits[ticker] = prices[ticker] + (3 * asset_atr)

    risk_levels = pd.concat(
        {
            "stop_loss": stop_losses,
            "take_profit": take_profits
        },
        axis=1
    )

    return risk_levels


def apply_drawdown_limit(portfolio):
    risk_off = False

    for i in range(1, len(portfolio)):
        drawdown = portfolio["drawdown"].iloc[i]

        if drawdown <= -MAX_DRAWDOWN:
            risk_off = True

        if risk_off:
            portfolio.loc[
                portfolio.index[i],
                "daily_return"
            ] = 0

            portfolio.loc[
                portfolio.index[i],
                "equity"
            ] = portfolio["equity"].iloc[i - 1]

            portfolio.loc[
                portfolio.index[i],
                "peak"
            ] = portfolio["equity"].iloc[:i + 1].max()

            portfolio.loc[
                portfolio.index[i],
                "drawdown"
            ] = (
                portfolio["equity"].iloc[i]
                / portfolio["peak"].iloc[i]
            ) - 1

    return portfolio