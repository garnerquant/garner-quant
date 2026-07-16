from __future__ import annotations

import pandas as pd


def prepare_challenge_equity_curve(tracker, initial_capital, today=None):
    """Build display-only daily challenge continuity without changing tracker rows."""
    columns = [
        "date",
        "portfolio_value",
        "challenge_day",
        "challenge_day_label",
        "return_pct",
        "is_recorded",
    ]
    if tracker is None or tracker.empty or "date" not in tracker.columns:
        return pd.DataFrame(columns=columns), 0

    working = tracker.copy()
    working["_timestamp"] = pd.to_datetime(working["date"], errors="coerce")
    working["portfolio_value"] = pd.to_numeric(
        working.get("portfolio_value"), errors="coerce"
    )
    working = working.dropna(subset=["_timestamp", "portfolio_value"])
    if working.empty:
        return pd.DataFrame(columns=columns), 0

    working = working.sort_values("_timestamp")
    working["_calendar_date"] = working["_timestamp"].dt.normalize()
    daily = working.groupby("_calendar_date", as_index=False).tail(1).copy()
    daily = daily.sort_values("_calendar_date")

    first_recorded_date = daily["_calendar_date"].iloc[0]
    baseline_date = first_recorded_date - pd.Timedelta(days=1)
    today_value = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    if today_value < first_recorded_date:
        today_value = first_recorded_date
    current_challenge_day = int((today_value - baseline_date).days)

    full_dates = pd.date_range(baseline_date, today_value, freq="D")
    display = pd.DataFrame({"date": full_dates})
    recorded = daily[["_calendar_date", "portfolio_value"]].rename(
        columns={"_calendar_date": "date"}
    )
    recorded["is_recorded"] = True
    display = display.merge(recorded, on="date", how="left")
    display["is_recorded"] = display["is_recorded"].fillna(False).astype(bool)

    baseline = pd.to_numeric(initial_capital, errors="coerce")
    if pd.isna(baseline) or float(baseline) <= 0:
        baseline = float(daily["portfolio_value"].iloc[0])
    else:
        baseline = float(baseline)
    display.loc[display["date"].eq(baseline_date), "portfolio_value"] = baseline
    display["portfolio_value"] = display["portfolio_value"].ffill()
    display["challenge_day"] = (display["date"] - baseline_date).dt.days
    display["challenge_day_label"] = display["challenge_day"].map(
        lambda day: f"Day {day}"
    )
    display["return_pct"] = (
        display["portfolio_value"] / baseline - 1
    ) * 100
    return display[columns], current_challenge_day
