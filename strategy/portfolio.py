import pandas as pd

from config import ASSETS, TOTAL_CRYPTO_LIMIT, STARTING_CASH, RISK_PER_TRADE


def build_weights(signals, prices=None, risk_levels=None):
    weights = pd.DataFrame(
        0.0,
        index=signals.index,
        columns=signals.columns
    )

    for date in signals.index:
        active = signals.loc[date][
            signals.loc[date] == 1
        ].index.tolist()

        if not active:
            continue

        if prices is None or risk_levels is None:
            base_weight = 1 / len(active)

            for ticker in active:
                max_weight = ASSETS[ticker]["max_weight"]
                weights.loc[date, ticker] = min(base_weight, max_weight)

        else:
            for ticker in active:
                price = prices.loc[date, ticker]
                stop = risk_levels["stop_loss"].loc[date, ticker]

                stop_distance = price - stop

                if stop_distance <= 0:
                    continue

                cash_risk = STARTING_CASH * RISK_PER_TRADE

                position_value = cash_risk / (stop_distance / price)

                weight = position_value / STARTING_CASH

                max_weight = ASSETS[ticker]["max_weight"]

                weights.loc[date, ticker] = min(weight, max_weight)

        crypto_tickers = [
            ticker for ticker in active
            if ASSETS[ticker]["type"] == "crypto"
        ]

        crypto_weight = weights.loc[
            date,
            crypto_tickers
        ].sum()

        if crypto_weight > TOTAL_CRYPTO_LIMIT:
            scale = TOTAL_CRYPTO_LIMIT / crypto_weight
            weights.loc[date, crypto_tickers] *= scale

        total_weight = weights.loc[date].sum()

        if total_weight > 1:
            weights.loc[date] = weights.loc[date] / total_weight

    return weights