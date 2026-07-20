"""Research Lab boundary page: immutable reports are rendered on page 97."""

import streamlit as st

from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles

st.set_page_config(page_title="Research Lab", page_icon="🧪", layout="wide")
require_dashboard_login()
apply_responsive_styles()

st.title("Research Lab")
st.info("Research runs are produced outside Streamlit. Open Research Intelligence to review the latest validated immutable report.")
st.caption("This page does not run experiments, parameter sweeps, backtests, or report publication.")
