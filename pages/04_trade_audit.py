import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

from dashboard.data_loader import load_csv
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


def load_supabase_trade_journal():
    try:
        load_dotenv()
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY"),
        )
        response = supabase.table("trade_journal").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame()


def load_trade_audit():
    local_audit = load_csv("trade_audit_trail.csv")
    if not local_audit.empty:
        return local_audit

    journal = load_supabase_trade_journal()
    if not journal.empty:
        from execution.trade_audit import build_authoritative_trade_audit

        return build_authoritative_trade_audit(journal)

    return pd.DataFrame()


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
