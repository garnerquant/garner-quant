import streamlit as st
import pandas as pd

from dashboard.data_loader import load_csv


st.set_page_config(
    page_title="Trade Audit | Garner Quant",
    page_icon="🔍",
    layout="centered",
)

st.title("🔍 Trade Audit")
st.caption("Completed BUY → SELL trade reviews")

audit = load_csv("trade_audit_trail.csv")

if audit.empty:
    st.info("No completed trades audited yet.")
else:
    audit = audit.copy()

    st.metric("Completed Trades", len(audit))

    if "pnl" in audit.columns:
        total_pnl = audit["pnl"].sum()
        st.metric("Total PnL", f"£{total_pnl:,.2f}")

    st.dataframe(
        audit.tail(20).iloc[::-1],
        use_container_width=True,
        hide_index=True,
    )