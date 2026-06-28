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
st.caption("Completed BUY -> SELL pairs derived from the current trade journal")


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
    journal = load_supabase_trade_journal()

    if not journal.empty:
        return build_trade_audit_trail(journal)

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

    st.dataframe(
        audit.tail(20).iloc[::-1],
        use_container_width=True,
        hide_index=True,
    )
