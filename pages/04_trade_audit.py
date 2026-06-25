import streamlit as st
import pandas as pd

from dashboard.data_loader import load_csv
from dashboard.components import page_header
from dashboard.formatters import format_currency, format_percent


st.set_page_config(
    page_title="Trade Audit | Garner Quant",
    page_icon="🔍",
    layout="centered"
)

page_header(
    "🔍 Trade Audit",
    "Completed BUY → SELL trade reviews"
)

audit = load_csv("trade_audit_trail.csv")

if audit.empty:
    st.info("No completed trades audited yet.")
else:
    st.write(audit.tail(20).iloc[::-1])