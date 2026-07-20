import pandas as pd
from pathlib import Path
from datetime import datetime

from config import PAPER_TRADING_CHALLENGE_DAYS, STARTING_CASH
from execution.atomic_io import atomic_write_csv_frames


TRACKER_FILE = "paper_30_day_tracker.csv"


def challenge_initial_capital(tracker=None):
    try:
        configured_cash = float(STARTING_CASH)
        if configured_cash > 0:
            return configured_cash
    except Exception:
        pass

    if tracker is not None and len(tracker) > 0 and "portfolio_value" in tracker.columns:
        values = pd.to_numeric(tracker["portfolio_value"], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[0])

    return 0.0


def update_30_day_tracker(broker, benchmark_stats=None):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    portfolio_value = broker["portfolio_value"]
    cash = broker["cash"]
    realised_pnl = broker["realised_pnl"]
    unrealised_pnl = broker["unrealised_pnl"]

    benchmark_return = 0 if benchmark_stats is None else benchmark_stats.get("benchmark_return", 0)
    alpha = 0 if benchmark_stats is None else benchmark_stats.get("alpha", 0)

    if Path(TRACKER_FILE).exists():
        tracker = pd.read_csv(TRACKER_FILE)
    else:
        tracker = pd.DataFrame()

    if "date" not in tracker.columns:
        tracker["date"] = []

    if "portfolio_value" not in tracker.columns:
        tracker["portfolio_value"] = []

    if "cash" not in tracker.columns:
        tracker["cash"] = []

    if "realised_pnl" not in tracker.columns:
        tracker["realised_pnl"] = []

    if "unrealised_pnl" not in tracker.columns:
        tracker["unrealised_pnl"] = []

    if "benchmark_return" not in tracker.columns:
        tracker["benchmark_return"] = 0

    if "alpha" not in tracker.columns:
        tracker["alpha"] = 0

    new_row = {
        "date": timestamp,
        "portfolio_value": portfolio_value,
        "cash": cash,
        "realised_pnl": realised_pnl,
        "unrealised_pnl": unrealised_pnl,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
    }

    tracker = pd.concat([tracker, pd.DataFrame([new_row])], ignore_index=True)

    tracker["date"] = pd.to_datetime(tracker["date"])
    tracker = tracker.sort_values("date")

    atomic_write_csv_frames({Path(TRACKER_FILE): tracker})

    return tracker


def calculate_30_day_performance(tracker):
    if len(tracker) == 0:
        return {}

    tracker = tracker.copy(deep=True)
    tracker["date"] = pd.to_datetime(tracker["date"], errors="coerce")
    tracker = tracker.dropna(subset=["date"]).sort_values("date", kind="stable")
    if tracker.empty:
        return {}

    start_value = challenge_initial_capital(tracker)
    current_value = tracker["portfolio_value"].iloc[-1]

    total_return = (current_value / start_value) - 1 if start_value > 0 else 0
    baseline_date = tracker["date"].iloc[0].normalize() - pd.Timedelta(days=1)
    elapsed_days = int((tracker["date"].iloc[-1].normalize() - baseline_date).days)
    days_tracked = min(max(elapsed_days, 0), PAPER_TRADING_CHALLENGE_DAYS)
    days_remaining = max(PAPER_TRADING_CHALLENGE_DAYS - days_tracked, 0)

    return {
        "start_date": tracker["date"].iloc[0].date(),
        "current_date": tracker["date"].iloc[-1].date(),
        "days_tracked": days_tracked,
        "days_remaining": days_remaining,
        "start_value": start_value,
        "current_value": current_value,
        "total_return": total_return,
        "realised_pnl": tracker["realised_pnl"].iloc[-1],
        "unrealised_pnl": tracker["unrealised_pnl"].iloc[-1]
    }


def print_30_day_performance(performance):
    if not performance:
        return

    print(f"\n===== {PAPER_TRADING_CHALLENGE_DAYS} DAY PAPER TRADING PERFORMANCE =====")
    print(f"Start Date: {performance['start_date']}")
    print(f"Current Date: {performance['current_date']}")
    print(f"Days Tracked: {performance['days_tracked']}/{PAPER_TRADING_CHALLENGE_DAYS}")
    print(f"Days Remaining: {performance['days_remaining']}")
    print(f"Start Value: £{performance['start_value']:,.2f}")
    print(f"Current Value: £{performance['current_value']:,.2f}")
    print(f"Return: {performance['total_return']:.2%}")
    print(f"Realised PnL: £{performance['realised_pnl']:,.2f}")
    print(f"Unrealised PnL: £{performance['unrealised_pnl']:,.2f}")
