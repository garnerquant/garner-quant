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
if pipeline.status == "UNAVAILABLE":
    with st.container(border=True):
        st.markdown("## Research pipeline not yet available")
        st.write("No research runtime metadata has been published.")
        st.write("When research becomes available this page will display:")
        st.markdown("- Pipeline status\n- Current progress\n- Last successful run\n- Last failed run\n- Publication history")
        st.markdown("**Next step**")
        st.write("Run the research pipeline to publish metadata.")
    st.stop()

tone = {"RUNNING": "blue", "PUBLISHING": "blue", "COMPLETED": "green", "FAILED": "red", "IDLE": "grey"}[pipeline.status]
pipeline_cards = [{"label": "Current Pipeline Status", "value": pipeline.status.title(), "tone": tone}]
for label, value, value_tone in (
    ("Last Successful Run", pipeline.last_successful_run, "green"),
    ("Last Failed Run", pipeline.last_failed_run, "red"),
    ("Last Publication", pipeline.last_publication, "blue"),
):
    if value is not None:
        pipeline_cards.append({"label": label, "value": value, "tone": value_tone})
st.subheader("Research Pipeline")
st.markdown(summary_cards_html(pipeline_cards, aria_label="Research pipeline status"), unsafe_allow_html=True)

with st.container(border=True):
    if pipeline.status == "FAILED":
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
