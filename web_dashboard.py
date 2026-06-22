import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Garner Quant",
    layout="centered"
)

st.title("📈 Garner Quant")
st.caption("Personal investment research and paper trading dashboard.")
st.subheader(
    "🚀 30 Day Paper Trading Challenge"
)

st.metric(
    "Day",
    "1/30"
)

st.metric(
    "Starting Balance",
    f"£{start_balance:,.2f}"
)

st.metric(
    "Current Balance",
    f"£{current_balance:,.2f}"
)

st.metric(
    "Return",
    f"{return_pct:.2%}"
)

st.metric(
    "Realised PnL",
    f"£{paper_row['realised_pnl']:,.2f}"
)

st.metric(
    "Unrealised PnL",
    f"£{paper_row['unrealised_pnl']:,.2f}"
)

st.line_chart(
    paper_30["portfolio_value"]
)

st.divider()

# Load files
broker = pd.read_csv("broker_account.csv")
paper_30 = pd.read_csv(
    "paper_30_day_tracker.csv"
)
holdings = pd.read_csv("holdings_report.csv")
portfolio = pd.read_csv("portfolio_v2.csv")
signals = pd.read_csv("signal_report_v2.csv")
trades = pd.read_csv("trade_journal_v3.csv")
analytics = pd.read_csv("trade_analytics_v3.csv")

broker_row = broker.iloc[0]
paper_row = paper_30.iloc[-1]

start_balance = paper_30[
    "portfolio_value"
].iloc[0]

current_balance = paper_row[
    "portfolio_value"
]

return_pct = (
    current_balance /
    start_balance
    - 1
)

days_tracked = len(paper_30)

st.subheader("Portfolio")

st.metric(
    "Portfolio Value",
    f"£{broker_row['portfolio_value']:,.2f}"
)

st.metric(
    "Cash",
    f"£{broker_row['cash']:,.2f}"
)

st.metric(
    "Buying Power",
    f"£{broker_row['buying_power']:,.2f}"
)

st.metric(
    "Unrealised PnL",
    f"£{broker_row['unrealised_pnl']:,.2f}"
)

st.divider()

st.subheader("Current Holdings")

if len(holdings) == 0:
    st.info("No open holdings.")
else:
    for _, row in holdings.iterrows():
        pnl = row["unrealised_pnl"]
        pnl_pct = row["unrealised_pnl_percent"]

        if pnl >= 0:
            pnl_text = f"🟢 +£{pnl:,.2f} ({pnl_pct:.2%})"
        else:
            pnl_text = f"🔴 -£{abs(pnl):,.2f} ({pnl_pct:.2%})"

        st.markdown(
            f"""
            ### {row['ticker']}
            **Market Value:** £{row['market_value']:,.2f}  
            **Shares:** {row['shares']:.4f}  
            **Entry:** £{row['entry_price']:,.2f}  
            **Current:** £{row['current_price']:,.2f}  
            **PnL:** {pnl_text}
            """
        )

        st.divider()

st.subheader("Equity Curve")

if "equity" in portfolio.columns:
    st.line_chart(portfolio["equity"])

st.subheader("Drawdown")

if "drawdown" in portfolio.columns:
    st.line_chart(portfolio["drawdown"])

st.divider()

st.subheader("Current Signals")

st.dataframe(
    signals,
    use_container_width=True
)

st.divider()

st.subheader("Trade Analytics")

if len(analytics) > 0:
    analytics_row = analytics.iloc[0]

    st.metric("Total Trades", int(analytics_row["total_trades"]))
    st.metric("Win Rate", f"{analytics_row['win_rate']:.2%}")
    st.metric("Profit Factor", f"{analytics_row['profit_factor']:.2f}")
    st.metric("Realised PnL", f"£{analytics_row['realised_pnl']:,.2f}")

st.divider()

st.subheader("Trade Journal")

if len(trades) == 0:
    st.info("No closed trades yet.")
else:
    st.dataframe(
        trades,
        use_container_width=True
    )

st.caption("Garner Quant V2.1 | Paper Trading Only")