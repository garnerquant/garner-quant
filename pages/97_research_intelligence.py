"""Read-only presentation of published Scanner research reports."""

from pathlib import Path

import streamlit as st

from dashboard.research_report_reader import ResearchReportError, ResearchReportReader
from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "data" / "scanner_research"

st.set_page_config(page_title="Research Intelligence", page_icon="🔬", layout="wide")
require_dashboard_login()
apply_responsive_styles()

st.title("Research Intelligence")
st.caption("Read-only results published outside Streamlit from immutable Scanner generations.")

try:
    bundle = ResearchReportReader(REPORT_ROOT).load_latest()
except ResearchReportError as exc:
    st.error(str(exc))
    st.info("Run the Scanner research producer outside the dashboard, then reload this page.")
    st.stop()

if bundle is None:
    st.info("No completed immutable research report is currently published.")
    st.caption("Insufficient generation or outcome history is not converted into synthetic results.")
    st.stop()

manifest = bundle.manifest
cols = st.columns(4)
cols[0].metric("Report ID", bundle.report_id)
cols[1].metric("Scanner generations", len(manifest.get("source_scanner_generations", [])))
cols[2].metric("Outcome bars", str(manifest.get("outcome_bar_generation", "Unavailable")))
cols[3].metric("Status", str(manifest.get("status", "Unknown")).title())
st.caption(f"Created: {manifest.get('created_at', 'Unavailable')} · Hash validation: passed")

labels = {
    "factor_report.csv": "Factors",
    "sector_report.csv": "Sectors",
    "country_report.csv": "Countries",
    "bucket_report.csv": "Buckets",
    "regime_report.csv": "Regimes",
    "candidate_report.csv": "Candidates",
    "ranking_report.csv": "Rankings",
}
tabs = st.tabs(list(labels.values()))
for tab, (name, label) in zip(tabs, labels.items()):
    with tab:
        frame = bundle.table(name)
        if frame.empty:
            st.info(f"No {label.lower()} results are available for this report.")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)
