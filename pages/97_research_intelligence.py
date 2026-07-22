"""Operator presentation of validated published research."""
from pathlib import Path

import streamlit as st

from dashboard.operations_presentation import summary_cards_html
from dashboard.continuous_research_reader import continuous_research_status
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

continuous = continuous_research_status(ROOT / "data" / "continuous_research")
if continuous["report"] is not None:
    report = continuous["report"]
    st.subheader("Research Overview")
    st.markdown(summary_cards_html([
        {"label": "Latest Report", "value": report["created_at"], "tone": "blue"},
        {"label": "Evidence Cut-off", "value": report["evidence_cutoff"], "tone": "blue"},
        {"label": "New Observations", "value": len(report["observations"]), "tone": "blue"},
        {"label": "Open Hypotheses", "value": len(report["hypotheses"]), "tone": "amber"},
        {"label": "Suggested Tasks", "value": len(report["suggested_tasks"]), "tone": "amber"},
    ], aria_label="Continuous research overview"), unsafe_allow_html=True)
    st.subheader("Today's Analyst Brief")
    st.write(report["executive_summary"])
    if report["important_limitations"]:
        st.warning(report["important_limitations"][0])
    if report["observations"]:
        st.subheader("Observations")
        for observation in report["observations"]:
            with st.expander(observation["title"]):
                st.write(observation["description"])
                st.caption(f"Evidence quality: {observation['evidence_quality']} · Sample: {observation['sample_size']} · Status: {observation['status']}")
                st.write("Limitations: " + "; ".join(observation["limitations"]))
                st.code(f"Observation {observation['observation_id']}\nReport hash {report['content_hash']}")
    if report["hypotheses"]:
        st.subheader("Hypotheses")
        for hypothesis in report["hypotheses"]:
            with st.expander(hypothesis["title"]):
                st.write(hypothesis["hypothesis_statement"])
                st.caption(f"Priority: {hypothesis['priority_score']} · Evidence: {hypothesis['evidence_strength']} · Lifecycle: {hypothesis['lifecycle_status']}")
                st.write("Proposed experiment: " + hypothesis["proposed_experiment"])
                st.write("Falsification: " + hypothesis["falsification_condition"])
                st.code("Observation lineage: " + ", ".join(hypothesis["observation_ids"]))
    st.caption(f"Immutable report {report['report_id']} · Evidence snapshot {report['evidence_snapshot_id']} · Report hash {report['content_hash']}")
    st.stop()

try:
    bundle = ResearchReportReader(REPORT_ROOT).load_latest()
except ResearchReportError as exc:
    st.error("Research Status: Published research could not be read safely.")
    st.caption(str(exc))
    st.info("Next step: review the research publication diagnostics before using this page.")
    st.stop()

if bundle is None:
    with st.container(border=True):
        st.markdown("## No Published Research")
        st.write("No validated research report has been published yet.")
        st.write("When research becomes available this page will display:")
        st.markdown("- Latest report summary\n- Publication date\n- Instruments analysed\n- Candidate opportunities\n- Portfolio observations")
        st.markdown("**Next step**")
        st.write("Run the research pipeline to generate the first validated report.")
    st.stop()

overview = research_report_overview(bundle)
st.subheader("Latest Published Report")
report_cards = [
    {"label": "Publication Date", "value": overview["publication_date"], "tone": "blue"},
    {"label": "Report ID", "value": overview["report_id"], "tone": "blue"},
    {"label": "Universe Analysed", "value": overview["universe_analysed"], "tone": "blue"},
    {"label": "Candidate Opportunities", "value": overview["candidate_count"], "tone": "green"},
]
report_cards = [card for card in report_cards if card["value"] is not None]
st.markdown(summary_cards_html(report_cards, aria_label="Latest research report summary"), unsafe_allow_html=True)
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
