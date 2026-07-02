import pandas as pd
import streamlit as st

from research.backtest_analytics import load_backtest_analytics
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)


st.set_page_config(
    page_title="Backtest Analytics | Garner Quant",
    page_icon=":bar_chart:",
    layout="wide",
)
apply_responsive_styles()


def format_percent(value):
    if value is None or pd.isna(value):
        return "Not available"

    try:
        return f"{float(value):.2%}"
    except Exception:
        return "Not available"


def format_number(value):
    if value is None or pd.isna(value):
        return "Not available"

    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "Not available"


def format_currency(value):
    if value is None or pd.isna(value):
        return "Not available"

    try:
        return f"GBP {float(value):,.2f}"
    except Exception:
        return "Not available"


def format_days(value):
    if value is None or pd.isna(value):
        return "Not available"

    try:
        return f"{float(value):,.2f} days"
    except Exception:
        return "Not available"


def format_metric(value, value_format):
    if value_format == "percent":
        return format_percent(value)
    if value_format == "currency":
        return format_currency(value)
    if value_format == "days":
        return format_days(value)
    return format_number(value)


def display_metric_table(metric_table):
    if metric_table.empty:
        st.info("No backtest analytics are available yet.")
        return

    display = metric_table.copy()
    display["value"] = display.apply(
        lambda row: format_metric(row["value"], row["format"]),
        axis=1,
    )
    display = display.rename(
        columns={
            "metric": "Metric",
            "value": "Value",
        }
    )
    responsive_table(display[["Metric", "Value"]], hide_index=True)


analytics = load_backtest_analytics()
summary = analytics["summary"]
availability = analytics["availability"]
trades = analytics["trades"]

st.title("Backtest Analytics")
st.warning(
    "Research-only analytics. This page reads saved CSV outputs and does not "
    "modify live runtime, paper execution, scheduler, Supabase, or notifications."
)

cols = responsive_columns(5)
cols[0].metric("Total Return", format_percent(summary["total_return"]))
cols[1].metric("CAGR", format_percent(summary["cagr"]))
cols[2].metric("Sharpe", format_number(summary["sharpe_ratio"]))
cols[3].metric("Max Drawdown", format_percent(summary["max_drawdown"]))
cols[4].metric("Trades", format_number(summary["trade_count"]))

cols = responsive_columns(5)
cols[0].metric("Volatility", format_percent(summary["annualised_volatility"]))
cols[1].metric("Sortino", format_number(summary["sortino_ratio"]))
cols[2].metric("Win Rate", format_percent(summary["win_rate"]))
cols[3].metric("Profit Factor", format_number(summary["profit_factor"]))
cols[4].metric("Alpha", format_percent(summary.get("alpha")))

st.divider()
st.subheader("Institutional Metric Pack")
display_metric_table(analytics["metric_table"])

st.divider()
st.subheader("Benchmark")
benchmark_return = summary.get("benchmark_return")
benchmark_label = summary.get("benchmark_ticker") or "Benchmark"

if benchmark_return is None:
    st.info("No benchmark series was available in saved files.")
else:
    bench_cols = responsive_columns(3)
    bench_cols[0].metric("Benchmark", benchmark_label)
    bench_cols[1].metric("Benchmark Return", format_percent(benchmark_return))
    bench_cols[2].metric("Source", availability["benchmark_source"] or "Unknown")

st.divider()
st.subheader("Trade Distribution")

if trades.empty:
    st.info("No completed trade data was available.")
else:
    trade_display = trades.copy()
    columns = [
        column
        for column in [
            "ticker",
            "entry_date",
            "exit_date",
            "pnl",
            "pnl_percent",
            "holding_days",
            "is_winner",
        ]
        if column in trade_display.columns
    ]

    if "pnl" in trade_display.columns:
        trade_display["pnl"] = trade_display["pnl"].apply(format_currency)
    if "pnl_percent" in trade_display.columns:
        trade_display["pnl_percent"] = trade_display["pnl_percent"].apply(
            format_percent,
        )
    if "holding_days" in trade_display.columns:
        trade_display["holding_days"] = trade_display["holding_days"].apply(
            format_days,
        )

    responsive_table(
        trade_display[columns],
        hide_index=True,
        mobile_columns=["ticker", "pnl", "pnl_percent", "is_winner"],
    )

st.divider()
st.subheader("Data Availability")
responsive_table(
    pd.DataFrame(
        [
            {"File": "portfolio_v2.csv", "Rows": availability["portfolio_rows"]},
            {
                "File": "trade_journal_v3.csv",
                "Rows": availability["trade_journal_rows"],
            },
            {
                "File": "trade_audit_trail.csv",
                "Rows": availability["trade_audit_rows"],
            },
            {"File": "prices_v2.csv", "Rows": availability["prices_rows"]},
        ]
    ),
    hide_index=True,
)
