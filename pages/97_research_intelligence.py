import pandas as pd
import streamlit as st

from research.research_insights import generate_research_insights, save_insights
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)


st.set_page_config(
    page_title="Research Insights | Garner Quant",
    page_icon="🧠",
    layout="wide",
)

apply_responsive_styles()


def format_percent(value):
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "Not available"


def format_number(value):
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "Not available"


def display_table(df, percent_columns=None, number_columns=None):
    if df is None or df.empty:
        st.info("No data available yet.")
        return

    display = df.copy()

    for column in percent_columns or []:
        if column in display.columns:
            display[column] = display[column].apply(format_percent)

    for column in number_columns or []:
        if column in display.columns:
            display[column] = display[column].apply(format_number)

    responsive_table(display, hide_index=True)


insights = generate_research_insights()
summary = insights["summary"]
availability = insights["data_availability"]

st.title("🧠 Research Insights")
st.warning(
    "Research Insights: These observations are intended to generate research "
    "ideas. They do NOT modify the live strategy. Every suggested improvement "
    "must be validated through: Experiment → Parameter Sweep → Walk-Forward → "
    "Monte Carlo → Paper Trading → Production."
)
st.caption(f"Generated at: {insights['generated_at']}")

st.subheader("Overview")
metric_cols = responsive_columns(6)
metric_cols[0].metric("Completed trades", summary["completed_trades"])
metric_cols[1].metric("Win rate", format_percent(summary["win_rate"]))
metric_cols[2].metric("Average return", format_percent(summary["average_return"]))
metric_cols[3].metric("Realised PnL", format_number(summary["realised_pnl"]))
metric_cols[4].metric("Tested experiments", summary["tested_experiments"])
metric_cols[5].metric(
    "Technical score data",
    "Available" if availability["technical_score_available"] else "Unavailable",
)

st.divider()
st.subheader("Trade Analysis")

trade_columns = [
    "ticker",
    "entry_date",
    "exit_date",
    "holding_days",
    "return_pct",
    "realised_pnl",
    "exit_reason",
    "technical_score",
    "position_size",
    "sector",
    "volatility",
    "atr",
    "market_direction",
    "win_loss",
]
trade_table = insights["trades"]
trade_columns = [
    column for column in trade_columns if column in trade_table.columns
]
display_table(
    trade_table[trade_columns] if trade_columns else pd.DataFrame(),
    percent_columns=["return_pct"],
    number_columns=[
        "holding_days",
        "realised_pnl",
        "technical_score",
        "position_size",
        "volatility",
        "atr",
    ],
)

st.divider()
st.subheader("Insight Cards")

if not insights["insight_cards"]:
    st.info("No completed-trade insight cards are available yet.")
else:
    for index, card in enumerate(insights["insight_cards"]):
        with st.container(border=True):
            st.markdown(f"**Pattern worth investigating: {card['title']}**")
            st.write(card["observation"])
            cols = responsive_columns(2)
            cols[0].metric("Supporting metric", card["supporting_metric"])
            cols[1].metric("Sample size", card["sample_size"])

st.divider()
st.subheader("Winners vs Losers Comparison")
display_table(
    insights["winners_vs_losers"],
    percent_columns=["average_return", "average_volatility"],
    number_columns=[
        "average_technical_score",
        "average_holding_days",
        "average_position_size",
        "average_atr",
        "largest_winner",
        "largest_loser",
        "average_drawdown",
        "average_gain",
        "average_loss",
    ],
)

st.divider()
st.subheader("Pattern Detection")

if not insights["patterns"]:
    st.info(
        "No statistically meaningful patterns detected yet. This usually means "
        "the completed-trade sample is still small or optional fields are unavailable."
    )
else:
    for pattern in insights["patterns"]:
        with st.container(border=True):
            st.markdown(f"**Pattern worth investigating: {pattern['title']}**")
            st.write(pattern["pattern"])
            cols = responsive_columns(3)
            cols[0].metric("Evidence", pattern["evidence"])
            cols[1].metric("Sample size", pattern["sample_size"])
            cols[2].metric("Confidence", pattern["confidence"])

st.divider()
st.subheader("Group Breakdowns")

tabs = st.tabs(
    [
        "Ticker",
        "Exit Reason",
        "Holding Period",
        "Entry Weekday",
        "Sector",
        "Market Direction",
        "Technical Score",
    ]
)

breakdowns = insights["breakdowns"]

with tabs[0]:
    display_table(
        breakdowns["ticker"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[1]:
    display_table(
        breakdowns["exit_reason"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[2]:
    display_table(
        breakdowns["holding_bucket"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[3]:
    display_table(
        breakdowns["entry_weekday"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[4]:
    display_table(
        breakdowns["sector"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[5]:
    display_table(
        breakdowns["market_direction"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

with tabs[6]:
    display_table(
        breakdowns["technical_score_bucket"],
        percent_columns=["win_rate", "average_return"],
        number_columns=["average_pnl", "total_pnl", "average_holding_days"],
    )

st.divider()
st.subheader("Experiment Insights")

patterns = insights["experiment_patterns"]

pattern_tabs = st.tabs(
    [
        "Best Return",
        "Best Sharpe",
        "Best Drawdown",
        "Repeated Top Parameters",
        "Poor Parameter Values",
        "Successful Combos",
        "Unsuccessful Combos",
    ]
)

with pattern_tabs[0]:
    display_table(
        patterns["best_by_return"],
        percent_columns=["total_return", "max_drawdown"],
        number_columns=["sharpe_ratio", "profit_factor", "completed_trades"],
    )

with pattern_tabs[1]:
    display_table(
        patterns["best_by_sharpe"],
        percent_columns=["total_return", "max_drawdown"],
        number_columns=["sharpe_ratio", "profit_factor", "completed_trades"],
    )

with pattern_tabs[2]:
    display_table(
        patterns["best_by_drawdown"],
        percent_columns=["total_return", "max_drawdown"],
        number_columns=["sharpe_ratio", "profit_factor", "completed_trades"],
    )

with pattern_tabs[3]:
    display_table(
        patterns["repeated_top_parameters"],
        percent_columns=["top_share"],
        number_columns=["top_experiment_count"],
    )

with pattern_tabs[4]:
    display_table(
        patterns["poor_parameter_values"],
        percent_columns=["poor_share"],
        number_columns=["poor_experiment_count"],
    )

with pattern_tabs[5]:
    display_table(
        patterns["common_successful_combinations"],
        percent_columns=["share"],
        number_columns=["count"],
    )

with pattern_tabs[6]:
    display_table(
        patterns["common_unsuccessful_combinations"],
        percent_columns=["share"],
        number_columns=["count"],
    )

st.divider()
st.subheader("Research Suggestions")

if not insights["suggestions"]:
    st.info("No research suggestions are available yet.")
else:
    for suggestion in insights["suggestions"]:
        with st.container(border=True):
            st.markdown(f"**{suggestion['title']}**")
            st.write(suggestion["why"])
            cols = responsive_columns(4)
            cols[0].metric("Evidence", suggestion["evidence"])
            cols[1].metric("Sample size", suggestion["sample_size"])
            cols[2].metric("Confidence", suggestion["confidence"])
            cols[3].metric("Suggested Experiment", suggestion["suggested_experiment"])
            st.caption("Pattern worth investigating. This is not a production change.")

st.divider()
st.subheader("Data Availability")

availability_df = pd.DataFrame(
    [
        {"Source": key, "Value": value}
        for key, value in availability.items()
    ]
)
responsive_table(availability_df, hide_index=True)

if st.button("Save Insights Snapshot"):
    path = save_insights(insights)
    st.success(f"Saved research insight snapshot to {path}")
