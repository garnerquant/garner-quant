import pandas as pd
import streamlit as st

from execution.trade_audit import build_authoritative_trade_audit
from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles, responsive_table


st.set_page_config(
    page_title="Trade Audit | Garner Quant",
    page_icon="🔍",
    layout="wide",
)

require_dashboard_login()
apply_responsive_styles()

st.title("🔍 Trade Audit")
st.caption("Completed BUY -> SELL pairs derived from the authoritative trade audit")


def load_trade_audit():
    return build_authoritative_trade_audit(ledger_path="trade_ledger_v1.csv")


audit = load_trade_audit()

if audit.empty:
    st.info("No completed trades audited yet.")
else:
    audit = audit.copy()

    st.metric("Completed BUY -> SELL Pairs", len(audit))

    if "pnl" in audit.columns:
        total_pnl = audit["pnl"].sum()
        st.metric("Total PnL", f"£{total_pnl:,.2f}")

    responsive_table(
        audit.tail(20).iloc[::-1],
        hide_index=True,
    )
