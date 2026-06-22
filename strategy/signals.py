import pandas as pd

from config import ASSETS
from data.fundamentals import fundamental_pass, get_fundamental_score
from indicators.technical import technical_score


def build_signals(prices, volumes=None):
    signals = pd.DataFrame(index=prices.index)
    fundamental_scores = {}

    for ticker in prices.columns:
        asset_type = ASSETS[ticker]["type"]

        fund_ok = fundamental_pass(ticker, asset_type)
        fundamental_scores[ticker] = get_fundamental_score(
            ticker,
            asset_type
        )

        volume = None

        if volumes is not None and ticker in volumes.columns:
            volume = volumes[ticker]

        score = technical_score(
            prices[ticker],
            volume
        )

        signals[ticker] = (
            (score >= 3) & fund_ok
        ).astype(int)

    fundamental_report = pd.DataFrame(
        list(fundamental_scores.items()),
        columns=["ticker", "fundamental_score"]
    )

    fundamental_report.to_csv(
        "fundamental_scores.csv",
        index=False
    )

    return signals