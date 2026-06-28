import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

from dashboard.data_loader import load_csv
from execution.trade_audit import build_trade_audit_trail


st.set_page_config(
    page_title="Trade Audit | Garner Quant",
    page_icon="🔍",
    layout="centered",
)

st.title("🔍 Trade Audit")
st.caption("Completed BUY → SELL trade reviews")


def load_supabase_trade_journal():
    try:
        load_dotenv()
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        response = supabase.table("trade_journal").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame()


def load_trade_audit():
    candidates = []

    journal = load_supabase_trade_journal()

    if not journal.empty:
        audit = build_trade_audit_trail(journal)

        if not audit.empty:
            candidates.append(audit)

    local_journal = load_csv("trade_journal_v3.csv")

    if not local_journal.empty:
        audit = build_trade_audit_trail(local_journal)

        if not audit.empty:
            candidates.append(audit)

    csv_audit = load_csv("trade_audit_trail.csv")

    if not csv_audit.empty:
        candidates.append(csv_audit)

    if candidates:
        return max(candidates, key=len)

    return pd.DataFrame()


audit = load_trade_audit()

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
