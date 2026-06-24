import pandas as pd
from pathlib import Path
from datetime import datetime


TRACKER_FILE = "paper_30_day_tracker.csv"


def update_30_day_tracker(broker, benchmark_stats=None):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")

    portfolio_value = broker["portfolio_value"]
    cash = broker["cash"]
    realised_pnl = broker["realised_pnl"]
    unrealised_pnl = broker["unrealised_pnl"]
    benchmark_return = 0 if benchmark_stats is None else benchmark_stats.get("benchmark_return", 0)
    alpha = 0 if benchmark_stats is None else benchmark_stats.get("alpha", 0)

    if Path(TRACKER_FILE).exists():
        tracker = pd.read_csv(TRACKER_FILE)

        if "benchmark_return" not in tracker.columns:
            tracker["benchmark_return"] = 0

    if "alpha" not in tracker.columns:
        tracker["alpha"] = 0
        
    else:
        tracker = pd.DataFrame(
            columns=[
                "date",
                "portfolio_value",
                "cash",
                "realised_pnl",
                "unrealised_pnl",
                "benchmark_return",
                "alpha"
            ]
        )

    tracker.loc[len(tracker)] = [
        timestamp,
        portfolio_value,
        cash,
        realised_pnl,
        unrealised_pnl,
        benchmark_return,
        alpha
    ]

    tracker["date"] = pd.to_datetime(tracker["date"])
    tracker = tracker.sort_values("date")

    tracker.to_csv(TRACKER_FILE, index=False)

    return tracker


def calculate_30_day_performance(tracker):
    if len(tracker) == 0:
        return {}

    tracker["date"] = pd.to_datetime(tracker["date"])
    tracker = tracker.sort_values("date")

    start_value = tracker["portfolio_value"].iloc[0]
    current_value = tracker["portfolio_value"].iloc[-1]

    total_return = (current_value / start_value) - 1
    days_tracked = tracker["date"].dt.date.nunique()

    days_remaining = max(30 - days_tracked, 0)

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

    print("\n===== 30 DAY PAPER TRADING PERFORMANCE =====")
    print(f"Start Date: {performance['start_date']}")
    print(f"Current Date: {performance['current_date']}")
    print(f"Days Tracked: {performance['days_tracked']}/30")
    print(f"Days Remaining: {performance['days_remaining']}")
    print(f"Start Value: £{performance['start_value']:,.2f}")
    print(f"Current Value: £{performance['current_value']:,.2f}")
    print(f"Return: {performance['total_return']:.2%}")
    print(f"Realised PnL: £{performance['realised_pnl']:,.2f}")
    print(f"Unrealised PnL: £{performance['unrealised_pnl']:,.2f}")