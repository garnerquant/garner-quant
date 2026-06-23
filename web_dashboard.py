import pandas as pd
import streamlit as st
import os
from dotenv import load_dotenv
from supabase import create_client


st.set_page_config(
    page_title="Garner Quant",
    layout="centered"
)

st.title("📈 Garner Quant")
st.caption("Personal investment research and paper trading dashboard.")
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

def load_csv(filename):
    try:
        return pd.read_csv(filename)
    except FileNotFoundError:
        return pd.DataFrame()


try:

    response = (
        supabase
        .table("broker_account")
        .select("*")
        .eq("id", 1)
        .execute()
    )

    broker = pd.DataFrame(response.data)

except:

    try:
        response = (
            supabase
            .table("broker_account")
            .select("*")
            .eq("id", 1)
            .execute()
        )

        broker = pd.DataFrame(response.data)

    except Exception as e:
        st.error(f"Supabase broker load failed: {e}")
        broker = load_csv("broker_account.csv")

    try:

        response = (
            supabase
            .table("broker_account")
            .select("*")
            .eq("id", 1)
            .execute()
        )

        broker = pd.DataFrame(response.data)

    except Exception:

        broker = load_csv(
            "broker_account.csv"
        )
try:
    response = (
        supabase
        .table("paper_30_day_tracker")
        .select("*")
        .order("date")
        .execute()
    )

    paper_30 = pd.DataFrame(response.data)

except Exception:
    paper_30 = load_csv("paper_30_day_tracker.csv")
holdings = load_csv("holdings_report.csv")
portfolio = load_csv("portfolio_v2.csv")
signals = load_csv("signal_report_v2.csv")
trades = load_csv("trade_journal_v3.csv")
analytics = load_csv("trade_analytics_v3.csv")


if broker.empty:
    st.error("broker_account.csv not found. Run main_v2.py first, then push the updated CSV files.")
    st.stop()


broker_row = broker.iloc[0]


st.subheader("🚀 30 Day Paper Trading Challenge")

if paper_30.empty:
    st.info("30 day tracker has not started yet.")
else:
    paper_row = paper_30.iloc[-1]

    start_balance = paper_30["portfolio_value"].iloc[0]
    current_balance = paper_row["portfolio_value"]
    return_pct = (current_balance / start_balance) - 1
    days_tracked = len(paper_30)

    st.metric("Day", f"{days_tracked}/30")
    st.metric("Starting Balance", f"£{start_balance:,.2f}")
    st.metric("Current Balance", f"£{current_balance:,.2f}")
    st.metric("Return", f"{return_pct:.2%}")
    st.metric("Realised PnL", f"£{paper_row['realised_pnl']:,.2f}")
    st.metric("Unrealised PnL", f"£{paper_row['unrealised_pnl']:,.2f}")

    st.line_chart(paper_30["portfolio_value"])

st.divider()


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

if holdings.empty:
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

if portfolio.empty or "equity" not in portfolio.columns:
    st.info("No equity curve data available.")
else:
    st.line_chart(portfolio["equity"])


st.subheader("Drawdown")

if portfolio.empty or "drawdown" not in portfolio.columns:
    st.info("No drawdown data available.")
else:
    st.line_chart(portfolio["drawdown"])

st.divider()


st.subheader("Current Signals")

if signals.empty:
    st.info("No signal report available.")
else:
    st.dataframe(
        signals,
        use_container_width=True
    )

st.divider()


st.subheader("Trade Analytics")

if analytics.empty:
    st.info("No trade analytics available.")
else:
    analytics_row = analytics.iloc[0]

    st.metric("Total Trades", int(analytics_row["total_trades"]))
    st.metric("Win Rate", f"{analytics_row['win_rate']:.2%}")
    st.metric("Profit Factor", f"{analytics_row['profit_factor']:.2f}")
    st.metric("Realised PnL", f"£{analytics_row['realised_pnl']:,.2f}")

st.divider()


st.subheader("Trade Journal")

if trades.empty:
    st.info("No closed trades yet.")
else:
    st.dataframe(
        trades,
        use_container_width=True
    )


st.caption("Garner Quant V2.1 | Paper Trading Only")