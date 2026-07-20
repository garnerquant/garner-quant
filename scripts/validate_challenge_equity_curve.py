from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.challenge_equity import prepare_challenge_equity_curve


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def main():
    issues = []
    tracker = pd.DataFrame([
        {"date": "2026-06-22 09:00:00", "portfolio_value": 9950.0},
        {"date": "2026-06-22 17:00:00", "portfolio_value": 9960.0},
        {"date": "2026-06-24 12:00:00", "portfolio_value": 9980.0},
        {"date": "2026-07-16 13:25:19", "portfolio_value": 10043.48},
    ])
    original = tracker.copy(deep=True)
    display, day = prepare_challenge_equity_curve(
        tracker, 10000.0, today="2026-07-16"
    )
    check(day == 25 and int(display.iloc[-1]["challenge_day"]) == 25, "final displayed day equals current challenge Day 25", issues)
    check(list(display["challenge_day"]) == [0, 1, 3, 25], "only Day 0 and recorded calendar days are retained", issues)
    day_one = display.loc[display["challenge_day"].eq(1)].iloc[0]
    check(float(day_one["portfolio_value"]) == 9960.0, "same-day duplicates use the latest timestamp", issues)
    check(bool(day_one["is_recorded"]), "actual tracker points remain marked as recorded", issues)
    check(not display["challenge_day"].eq(2).any(), "missing days are not fabricated or converted to zero", issues)
    day_three = display.loc[display["challenge_day"].eq(3)].iloc[0]
    check(float(day_three["portfolio_value"]) == 9980.0 and bool(day_three["is_recorded"]), "recorded values are preserved on their calendar dates", issues)
    check(float(day_three["recorded_point_value"]) == 9980.0 and pd.notna(day_three["recorded_run"]), "recorded observations retain an exact point marker and solid-line run", issues)
    check(float(display.iloc[0]["portfolio_value"]) == 10000.0 and display.iloc[0]["challenge_day_label"] == "Day 0", "Day 0 uses canonical starting capital", issues)
    expected_return = (10043.48 / 10000.0 - 1) * 100
    check(float(display.iloc[-1]["portfolio_value"]) == 10043.48 and bool(display.iloc[-1]["is_recorded"]), "final actual tracker value remains the final chart value", issues)
    check(abs(float(display.iloc[-1]["return_pct"]) - expected_return) <= 1e-12, "final return remains approximately positive 0.43 percent", issues)
    check(tracker.equals(original), "presentation reindexing does not mutate tracker input", issues)

    empty, empty_day = prepare_challenge_equity_curve(pd.DataFrame(), 10000.0, today="2026-07-16")
    check(empty.empty and empty_day == 0, "empty tracker remains safe", issues)
    single = pd.DataFrame([{"date": "2026-07-16 09:00:00", "portfolio_value": 10010.0}])
    single_display, single_day = prepare_challenge_equity_curve(single, 10000.0, today="2026-07-16")
    check(single_day == 1 and list(single_display["challenge_day"]) == [0, 1], "single-row tracker safely includes Day 0 and Day 1", issues)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
