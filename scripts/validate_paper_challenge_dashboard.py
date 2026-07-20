from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PAPER_TRADING_CHALLENGE_DAYS  # noqa: E402
from dashboard.paper_challenge import (  # noqa: E402
    build_day_over_day_attribution,
    build_paper_challenge_series,
    build_realised_pnl_series,
)
from dashboard.equity_chart import build_realised_equity_chart  # noqa: E402


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def import_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(item.name.split(".")[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def main():
    issues = []
    check(PAPER_TRADING_CHALLENGE_DAYS == 60, "one canonical 60-day configuration", issues)
    tracker = pd.DataFrame([
        {"date": "2026-01-01 09:00", "portfolio_value": 100.0, "cash": 40.0},
        {"date": "2026-01-01 17:00", "portfolio_value": 101.0, "cash": 40.0},
        {"date": "bad", "portfolio_value": np.nan, "cash": np.nan},
        {"date": "2026-01-03 17:00", "portfolio_value": 110.0, "cash": 45.0},
    ])
    original = tracker.copy(deep=True)
    result = build_paper_challenge_series(
        tracker, 100.0, 60, today="2026-03-15", displayed_current_balance=110.0
    )
    check(result.current_day == 60 and result.completed, "Day display clamps at 60 and completes", issues)
    check(list(result.data["challenge_day"]) == [0, 1, 3], "missing days remain absent", issues)
    check(float(result.data.iloc[0]["total_equity"]) == 100.0, "equity starts at configured balance", issues)
    check(float(result.data.iloc[-1]["total_equity"]) == 110.0, "equity endpoint equals Current Balance", issues)
    check(abs(float(result.data.iloc[-1]["return_from_start_pct"]) - 10.0) < 1e-12,
          "return endpoint equals headline Return", issues)
    check(result.data["timestamp"].is_monotonic_increasing, "equity is chronological", issues)
    check(float(result.data.iloc[1]["total_equity"]) == 101.0, "same-day duplicates use latest timestamp", issues)
    check(result.malformed_observations == 1 and not result.data["total_equity"].eq(0).any(),
          "malformed data is excluded without conversion to zero", issues)
    check(tracker.equals(original), "equity preparation is read-only", issues)

    drawdown = build_paper_challenge_series(pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 100, "cash": 100},
        {"date": "2026-01-02", "portfolio_value": 110, "cash": 110},
        {"date": "2026-01-03", "portfolio_value": 99, "cash": 99},
        {"date": "2026-01-04", "portfolio_value": 111, "cash": 111},
    ]), 100, 60, today="2026-01-04")
    values = list(drawdown.data["drawdown_pct"])
    check(values[0] == 0 and values[1] == 0 and values[2] == 0, "drawdown is zero initially and at new highs", issues)
    check(abs(values[3] - (-10.0)) < 1e-12, "[100, 110, 99] produces -10 percent drawdown", issues)
    check(values[4] == 0 and max(values) <= 0, "recovery is zero and drawdown never positive", issues)
    check(drawdown.data.iloc[-1]["total_equity"] == 111, "drawdown has no artificial terminal collapse", issues)
    check({"timestamp", "challenge_day"}.issubset(drawdown.data), "drawdown exposes chronological x-axis fields", issues)

    audit = pd.DataFrame([
        {"close_time": "2026-01-05", "symbol": "AAA", "entry_event_id": "buy-1", "exit_event_id": "sell-1", "pnl": 7.0, "cumulative_pnl": 700},
        {"close_time": "2026-01-05", "symbol": "AAA", "entry_event_id": "buy-2", "exit_event_id": "sell-1", "pnl": 3.0, "cumulative_pnl": 700},
        {"close_time": "2026-01-05", "symbol": "AAA", "entry_event_id": "buy-2", "exit_event_id": "sell-1", "pnl": 999.0, "cumulative_pnl": 700},
        {"close_time": "2026-01-06", "symbol": "BBB", "entry_event_id": "buy-3", "exit_event_id": "sell-2", "pnl": -4.0, "cumulative_pnl": -999},
        {"close_time": "bad", "symbol": "BAD", "entry_event_id": "", "exit_event_id": "", "pnl": 500.0, "cumulative_pnl": 500},
    ])
    realised = build_realised_pnl_series(
        audit, 6.0, starting_balance=10000.0, challenge_start_date="2026-01-01"
    )
    check(float(realised.data.iloc[0]["realised_equity"]) == 10000.0, "realised equity begins at configured balance", issues)
    check(realised.event_count == 2 and list(realised.data["daily_realised_pnl"]) == [0.0, 10.0, -4.0],
          "partial closes aggregate and duplicate lots do not double count", issues)
    check(float(realised.data.iloc[-1]["realised_equity"]) == 10006.0 and realised.reconciliation_error is None,
          "winning/loss events reconcile to headline realised P&L", issues)
    check(realised.malformed_events == 1,
          "malformed realised events are excluded rather than counted", issues)
    check(float(realised.data.iloc[-1]["cumulative_realised_pnl"]) != audit["cumulative_pnl"].sum(),
          "already-cumulative fields are never cumulatively summed", issues)
    loss = build_realised_pnl_series(
        pd.DataFrame([{
            "close_time": "2026-01-05", "entry_event_id": "loss-buy",
            "exit_event_id": "loss-sell", "pnl": -36.34,
        }]),
        -36.34,
        starting_balance=10000.0,
        challenge_start_date="2026-01-01",
    )
    check(float(loss.data.iloc[-1]["realised_equity"]) == 9963.66,
          "10000 starting balance and -36.34 realised P&L end at 9963.66", issues)
    check(loss.data["date"].is_monotonic_increasing and not loss.data["date"].duplicated().any(),
          "realised-equity display dates are unique and chronological", issues)
    seven_rows = pd.concat(
        [loss.data.iloc[[0]]] + [
            loss.data.iloc[[-1]].assign(
                date=pd.Timestamp("2026-01-05") + pd.Timedelta(days=offset)
            )
            for offset in range(6)
        ],
        ignore_index=True,
    )
    chart_spec = build_realised_equity_chart(seven_rows).to_dict(validate=True)
    chart_dataset = next(iter(chart_spec["datasets"].values()))
    check(len(seven_rows) == len(chart_dataset) == 7,
          "all seven helper rows reach the Altair chart dataset", issues)
    check(
        chart_spec["encoding"]["x"]["field"] == "date"
        and chart_spec["encoding"]["y"]["field"] == "realised_equity"
        and {"date", "realised_equity"}.issubset(seven_rows.columns),
        "Altair x and y fields exist and exactly match the chart dataframe",
        issues,
    )
    encoded_fields = {
        chart_spec["encoding"]["x"]["field"],
        chart_spec["encoding"]["y"]["field"],
        *(item["field"] for item in chart_spec["encoding"]["tooltip"]),
    }
    check(encoded_fields.issubset(seven_rows.columns),
          "every Altair encoded field exists in the chart dataframe", issues)
    check("£,.2f" not in str(chart_spec) and "Â£" not in str(chart_spec),
          "Altair spec contains no invalid currency-prefixed number format", issues)

    holdings_history = pd.DataFrame([
        {"date": "2026-01-01", "ticker": "AAA", "market_value": 60.0},
        {"date": "2026-01-02", "ticker": "AAA", "market_value": 65.0},
        {"date": "2026-01-02", "ticker": "BBB", "market_value": 10.0},
    ])
    accounts = pd.DataFrame([
        {"date": "2026-01-01 17:00", "portfolio_value": 100.0, "cash": 40.0},
        {"date": "2026-01-02 17:00", "portfolio_value": 108.0, "cash": 33.0},
    ])
    attribution = build_day_over_day_attribution(holdings_history, accounts)
    check(attribution.status == "available" and abs(attribution.data["attribution"].sum() - 8.0) < 1e-12,
          "holdings plus cash attribution reconciles to equity change", issues)
    unavailable = build_day_over_day_attribution(pd.DataFrame(), accounts)
    check(unavailable.status == "unavailable" and unavailable.data.empty,
          "missing history is explicit and current holdings are not reconstructed", issues)

    source = (ROOT / "web_dashboard.py").read_text(encoding="utf-8")
    check("30 Day Paper Trading Challenge" not in source and "30 Day Equity Curve" not in source,
          "dashboard titles no longer contain 30 Day", issues)
    check(
        'st.subheader("📈 Realised Equity Curve")' in source
        and "build_realised_equity_chart(realised_series.data)" in source,
        "realised chart title and GBP equity-axis contract are explicit",
        issues,
    )
    helper = ROOT / "dashboard/paper_challenge.py"
    prohibited = {"scanner_v2", "yfinance", "execution", "streamlit", "runtime"}
    check(not (import_roots(helper) & prohibited), "analytics helper has no scanner, network, UI, execution, or runtime dependency", issues)
    check(all(text not in helper.read_text(encoding="utf-8") for text in ("to_csv(", "write_text(", "unlink(", "atomic_write")),
          "analytics helper performs no writes", issues)
    check(all(text not in helper.read_text(encoding="utf-8") for text in ("FIFO", "open_lots", "buy_cost", "sell_proceeds")),
          "chart helper contains no FIFO or trade-accounting logic", issues)
    if issues:
        raise AssertionError("; ".join(issues))
    print("\nPaper challenge dashboard validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
