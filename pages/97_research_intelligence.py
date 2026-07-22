"""Operator presentation of validated published research."""
from pathlib import Path

import streamlit as st

from dashboard.operations_presentation import summary_cards_html
from dashboard.research_report_reader import ResearchReportError, ResearchReportReader
from dashboard.research_status_reader import research_report_overview
from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "data" / "scanner_research"

st.set_page_config(page_title="Research Intelligence", page_icon="🔬", layout="wide")
require_dashboard_login()
apply_responsive_styles()

st.title("Research Intelligence")
st.caption("Validated research findings and published opportunities.")

try:
    bundle = ResearchReportReader(REPORT_ROOT).load_latest()
except ResearchReportError as exc:
    st.error("Research Status: Published research could not be read safely.")
    st.caption(str(exc))
    st.info("Next step: review the research publication diagnostics before using this page.")
    st.stop()

if bundle is None:
    st.subheader("Research Status")
    st.markdown(summary_cards_html([
        {"label": "Published Research", "value": "Not available", "context": "Waiting for first report", "tone": "grey",
         "help": "No validated research report has been published yet."},
        {"label": "Status", "value": "Waiting", "context": "No action is available on this page", "tone": "amber",
         "help": "Research appears automatically after a validated publication is available."},
    ], aria_label="Research publication status"), unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("### No published research available")
        st.write("No validated research report has been published yet.")
        st.write("When research becomes available this page will display:")
        st.markdown("- Latest report\n- Publication date\n- Number of instruments analysed\n- Candidate opportunities\n- High-conviction ideas\n- Portfolio observations")
        st.caption("Next step: wait for the first validated research publication, then return here to review it.")
    st.stop()

overview = research_report_overview(bundle)
st.subheader("Latest Published Report")
st.markdown(summary_cards_html([
    {"label": "Publication Date", "value": overview["publication_date"], "tone": "blue"},
    {"label": "Report ID", "value": overview["report_id"], "tone": "blue"},
    {"label": "Universe Analysed", "value": overview["universe_analysed"], "tone": "blue"},
    {"label": "Candidate Opportunities", "value": overview["candidate_count"], "tone": "green"},
    {"label": "High-conviction Ideas", "value": overview["high_conviction_count"], "tone": "grey",
     "help": "Shown only when the validated report publishes this measure."},
], aria_label="Latest research report summary"), unsafe_allow_html=True)
st.subheader("Research Summary")
st.write(overview["summary"])
st.caption("Report integrity checks passed. Values shown above come from the validated published report.")

labels = {"factor_report.csv": "Factors", "sector_report.csv": "Sectors", "country_report.csv": "Countries",
          "bucket_report.csv": "Buckets", "regime_report.csv": "Regimes",
          "candidate_report.csv": "Candidates", "ranking_report.csv": "Rankings"}
st.subheader("View Full Report")
tabs = st.tabs(list(labels.values()))
for tab, (name, label) in zip(tabs, labels.items()):
    with tab:
        frame = bundle.table(name)
        if frame.empty:
            st.info(f"This report contains no {label.lower()} results.")
        else:
            st.dataframe(frame, width="stretch", hide_index=True)
