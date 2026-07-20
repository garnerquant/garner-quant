from __future__ import annotations

import pandas as pd

from config import PAPER_TRADING_CHALLENGE_DAYS
from dashboard.paper_challenge import build_paper_challenge_series


def prepare_challenge_equity_curve(
    tracker,
    initial_capital,
    today=None,
    challenge_days=PAPER_TRADING_CHALLENGE_DAYS,
):
    """Return genuine challenge observations without fabricating missing days."""
    columns = [
        "date",
        "portfolio_value",
        "challenge_day",
        "challenge_day_label",
        "return_pct",
        "is_recorded",
        "recorded_point_value",
        "recorded_run",
    ]
    result = build_paper_challenge_series(
        tracker, initial_capital, challenge_days, today=today
    )
    if result.data.empty:
        return pd.DataFrame(columns=columns), result.current_day
    return result.data[columns].copy(deep=True), result.current_day
