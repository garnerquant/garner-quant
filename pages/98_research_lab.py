"""Read-only operator presentation of research pipeline metadata."""
from pathlib import Path

import streamlit as st

from dashboard.operations_presentation import summary_cards_html
from dashboard.research_status_reader import read_research_pipeline_status
from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles

ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="Research Lab", page_icon="🧪", layout="wide")
require_dashboard_login()
apply_responsive_styles()

st.title("Research Lab")
st.caption("Research pipeline status and publication readiness.")

pipeline = read_research_pipeline_status(ROOT / "data" / "scanner_research")
tone = {"RUNNING": "blue", "PUBLISHING": "blue", "COMPLETED": "green", "FAILED": "red",
        "IDLE": "grey", "UNAVAILABLE": "grey"}[pipeline.status]
display_status = "Status unavailable" if pipeline.status == "UNAVAILABLE" else pipeline.status.title()

st.subheader("Research Pipeline")
st.markdown(summary_cards_html([
    {"label": "Current Pipeline Status", "value": display_status, "tone": tone,
     "help": "Status is shown only when explicit research metadata is available."},
    {"label": "Last Successful Run", "value": pipeline.last_successful_run, "tone": "green" if pipeline.last_successful_run else "grey"},
    {"label": "Last Failed Run", "value": pipeline.last_failed_run, "tone": "red" if pipeline.last_failed_run else "grey"},
    {"label": "Last Publication", "value": pipeline.last_publication, "tone": "blue" if pipeline.last_publication else "grey"},
], aria_label="Research pipeline status"), unsafe_allow_html=True)

with st.container(border=True):
    st.markdown("### Purpose")
    st.write("The Research Lab manages the research generation workflow.")
    st.write("Research is created by the existing pipeline and becomes available in Research Intelligence once validated.")
    if pipeline.status == "UNAVAILABLE":
        st.info("Status unavailable. No research runtime or publication metadata is currently available.")
        st.caption("Next step: wait for an authorised research run. This page will show its status when metadata becomes available.")
    elif pipeline.status == "FAILED":
        st.error("The latest recorded research run failed.")
        st.caption("Next step: review the pipeline logs, then rerun the existing research workflow outside this page.")
    elif pipeline.status in {"RUNNING", "PUBLISHING"}:
        st.info(f"Research is currently {pipeline.status.lower()}.")
        st.caption("Next step: no action is required unless the status stops progressing.")
    else:
        st.success("The latest recorded research run completed.")
        st.caption("Next step: open Research Intelligence to review the published report.")

if pipeline.report_id:
    st.subheader("Publication History")
    st.write(f"Latest published report: {pipeline.report_id}")
