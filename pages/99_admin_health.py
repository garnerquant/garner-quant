"""Read-only operational health presentation."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles, responsive_table
from ui.runtime_status import load_runtime_status, runtime_freshness, runtime_state
from risk_engine.diagnostics import load_risk_diagnostics
from risk_engine.operations import activation_readiness, configuration_health, decision_history, risk_metrics
from canonical_accounting.successor import accounting_transaction_status
from dashboard.accounting_observation_reader import accounting_observation_status, non_fill_observation_status
from dashboard.opening_snapshot_reader import opening_snapshot_status
from dashboard.opening_evidence_reader import opening_evidence_status
from dashboard.migration_approval_reader import migration_approval_status
from dashboard.review_workflow_reader import review_workflow_status
from dashboard.operations_presentation import detail_rows


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return (value, None) if isinstance(value, dict) else (None, "Unexpected JSON shape")
    except FileNotFoundError:
        return None, "Not published"
    except (OSError, ValueError, TypeError):
        return None, "Unreadable or malformed"


st.set_page_config(page_title="Admin Health", page_icon="🩺", layout="wide")
require_dashboard_login()
apply_responsive_styles()

st.title("System Health")
st.caption("Read-only operational status. Validations, monitoring, notifications, and repairs run outside the dashboard.")

try:
    runtime = load_runtime_status()
    state = runtime_state(runtime)
    freshness = runtime_freshness(runtime)
    cols = st.columns(4)
    cols[0].metric("Runtime", str(state.get("health", state.get("title", "Unknown"))))
    cols[1].metric("Freshness", str(freshness.get("label", "Unknown")))
    cols[2].metric("Last cycle", str(runtime.get("last_cycle_at", "Unavailable")))
    cols[3].metric("Cycle count", runtime.get("cycle_count", "Unavailable"))
except Exception:
    st.error("Runtime status could not be read safely.")

st.subheader("Pre-trade risk")
risk = load_risk_diagnostics()
risk_cols = st.columns(4)
risk_cols[0].metric("Risk", risk["engine_status"])
risk_cols[1].metric("Kill switch", "ACTIVE" if risk["kill_switch_active"] else "INACTIVE")
risk_cols[2].metric("Trading", "ENABLED" if risk["trading_enabled"] else "DISABLED")
risk_cols[3].metric("Configuration", risk.get("configuration_version") or "ERROR")
latest_risk = risk.get("latest_decision") or {}
st.caption(
    "Latest decision: "
    f"{latest_risk.get('status', 'None')} | "
    f"{latest_risk.get('primary_reason_code', 'No evaluations recorded')}"
)
with st.expander("Non-fill accounting observation producers", expanded=False):
    non_fill = non_fill_observation_status(ROOT / "data" / "accounting_observations" / "envelopes.jsonl",
                                           ROOT / "data" / "accounting_observations" / "validation_failures.jsonl")
    st.caption("Read-only. This page has no event creation controls.")
    producer_cols = st.columns(4)
    producer_cols[0].metric("Framework", non_fill["status"])
    producer_cols[1].metric("Validation", non_fill["validation_health"])
    producer_cols[2].metric("Production producers", len(non_fill["active_production_producers"]))
    producer_cols[3].metric("Duplicate conflicts", non_fill["duplicate_conflict_count"])
    non_fill_details = {**non_fill,
                        "latest_envelope": (non_fill.get("latest_non_fill") or {}).get("event_id"),
                        "latest_invalid_reason": (non_fill.get("latest_invalid") or {}).get("reason")}
    responsive_table(pd.DataFrame(detail_rows(non_fill_details, (
        ("supported_event_types", "Supported event types"), ("unavailable_producers", "Unavailable producers"),
        ("counts_by_event_type", "Observations by type"), ("source_authority", "Source authority"),
        ("last_observation_timestamp", "Last observation"), ("latest_envelope", "Latest envelope"),
        ("latest_invalid_reason", "Latest invalid event"),
    ))))

with st.expander("Canonical opening snapshot", expanded=False):
    opening = opening_snapshot_status(ROOT / "data" / "opening_snapshot_candidates")
    st.caption("Read-only inactive candidate review. Validation and approval cannot activate accounting.")
    opening_cols=st.columns(4)
    opening_cols[0].metric("Candidate",opening.get("status","ERROR"));opening_cols[1].metric("Readiness",opening.get("readiness","NOT_READY"))
    opening_cols[2].metric("Approval",opening.get("approval","UNAPPROVED"));opening_cols[3].metric("Pointer",opening.get("pointer","UNKNOWN"))
    responsive_table(pd.DataFrame(detail_rows(opening, (
        ("candidate_id", "Candidate ID"), ("candidate_hash", "Candidate hash"), ("cut_off", "Cut-off"),
        ("manifest", "Source manifest"), ("completeness", "Completeness"), ("cash", "Cash"),
        ("positions", "Positions"), ("lots", "Lots"), ("attribution", "Strategy attribution %"),
        ("fx", "FX evidence %"), ("exceptions", "Unresolved exceptions"),
        ("largest_difference", "Largest difference"), ("inactive", "Inactive"), ("validated_at", "Latest validation"),
    ))))

with st.expander("Opening snapshot evidence", expanded=False):
    frozen_evidence_root = ROOT / "data" / "frozen_evidence_packs"
    evidence = opening_evidence_status(frozen_evidence_root)
    st.caption("Read-only frozen evidence inventory and gap analysis. Dashboard reads never regenerate evidence.")
    evidence_cols = st.columns(4)
    evidence_cols[0].metric("Evidence Pack Status", evidence.get("status", "ERROR"), help="A Frozen Evidence Pack is the immutable evidence basis for migration review.")
    evidence_cols[1].metric("Gap Count", evidence.get("gap_count", "Unavailable"))
    evidence_cols[2].metric("Critical Gaps", evidence.get("critical_gaps", "Unavailable"))
    evidence_cols[3].metric("Coverage %", evidence.get("coverage", "Unavailable"), help="Evidence Coverage measures verified historical support without filling unknowns.")
    responsive_table(pd.DataFrame(detail_rows(evidence, (
        ("pack_id", "Current Frozen Pack"), ("previous_pack_id", "Previous Frozen Pack"), ("pack_version", "Pack Version"),
        ("cutoff", "Cut-off Date"), ("coverage_metrics", "Coverage Metrics"), ("coverage_improvement", "Coverage Improvement"),
        ("resolved_gaps", "Resolved Gaps"), ("outstanding_gaps", "Outstanding Gaps"), ("conflict_count", "Conflict Count"),
        ("evidence_count", "Evidence Count"), ("verification", "Evidence Confidence"), ("import_history", "Import History"),
        ("replay_readiness", "Replay Readiness"), ("opening_snapshot_readiness", "Opening Snapshot Readiness"),
        ("pack_hash", "Evidence hash"), ("error", "Diagnostic"),
    ))))

with st.expander("Migration allocation and approval", expanded=False):
    migration = migration_approval_status(frozen_evidence_root)
    st.caption("Read-only governance proposals. No proposal creates accounting state, lots, candidates, generations, or pointers.")
    migration_cols=st.columns(4)
    migration_cols[0].metric("Migration Pack Status",migration.get("status","ERROR"));migration_cols[1].metric("Pending Proposals",migration.get("pending"))
    migration_cols[2].metric("Approved",migration.get("approved"));migration_cols[3].metric("Rejected",migration.get("rejected"))
    responsive_table(pd.DataFrame(detail_rows(migration, (("coverage", "Coverage %"), ("critical", "Critical Materiality"),
        ("readiness", "Readiness"), ("pack_id", "Pack ID"), ("error", "Diagnostic")))))

with st.expander("Operator migration review", expanded=False):
    review=review_workflow_status(frozen_evidence_root)
    st.caption("Authenticated read-only review. Decisions are created explicitly through the offline governance service; this dashboard has no approval controls.")
    review_cols=st.columns(4);review_cols[0].metric("Review Status",review.get("status","ERROR"));review_cols[1].metric("Outstanding Reviews",review.get("outstanding"));review_cols[2].metric("Critical Pending",review.get("critical_pending"));review_cols[3].metric("Approval Coverage",f"{review.get('coverage',0)}%")
    responsive_table(pd.DataFrame(detail_rows(review, (("evidence_version", "Evidence Version"),
        ("pack_version", "Approval Pack Version"), ("error", "Diagnostic")))))
    proposals = review.get("proposals") or []
    if proposals:
        responsive_table(pd.DataFrame(proposals))

st.subheader("Accounting observation envelopes")
envelopes = accounting_observation_status(ROOT / "data" / "accounting_observations" / "envelopes.jsonl",
                                          ROOT / "data" / "accounting_observations" / "validation_failures.jsonl")
envelope_cols = st.columns(4)
envelope_cols[0].metric("Envelope health", envelopes["health"])
envelope_cols[1].metric("Envelope version", envelopes["version"])
envelope_cols[2].metric("Validation", envelopes["validation"])
envelope_cols[3].metric("Observation count", envelopes["count"])
latest_envelope = envelopes.get("latest") or {}
responsive_table(pd.DataFrame([
    {"Item": "Latest envelope", "Value": latest_envelope.get("event_id", "None")},
    {"Item": "Missing fields", "Value": envelopes["missing_fields"]},
    {"Item": "Effect", "Value": "Observational only — no accounting or execution action"},
]))

try:
    metrics = risk_metrics()
    history = decision_history()
    readiness = activation_readiness()
    latest_history = history[-1] if history else {}
    accounting_label = "ACTIVE" if not any(item["description"] == "Accounting inactive" for item in readiness["blockers"]) else "PENDING"
    ops = st.columns(4)
    ops[0].metric("Accounting", accounting_label)
    ops[1].metric("Approvals today", metrics["APPROVED"])
    ops[2].metric("Rejections today", metrics["REJECTED"])
    ops[3].metric("Blocked / monitor", f"{metrics['BLOCKED']} / {metrics['MONITOR_ONLY']}")
    responsive_table(pd.DataFrame([
        {"Item": "Last evaluation", "Value": metrics["last_evaluation_timestamp"] or "None"},
        {"Item": "Average latency", "Value": f"{metrics['average_latency_ms']} ms" if metrics["average_latency_ms"] is not None else "Unavailable"},
        {"Item": "Readiness", "Value": "Ready" if readiness["ready"] else "Not Ready"},
        {"Item": "Latest proposal", "Value": f"{latest_history.get('strategy', 'None')} / {latest_history.get('symbol', 'None')} {latest_history.get('side', '')} {latest_history.get('quantity', '')}"},
        {"Item": "Latest decision", "Value": latest_history.get("decision", "None")},
        {"Item": "Decision reason", "Value": latest_history.get("reason", "None")},
    ]))
    with st.expander("Risk decision history and readiness", expanded=False):
        filter_cols = st.columns(5)
        strategies = sorted({row["strategy"] for row in history if row["strategy"]})
        symbols = sorted({row["symbol"] for row in history if row["symbol"]})
        decisions = sorted({row["decision"] for row in history if row["decision"]})
        reasons = sorted({row["reason"] for row in history if row["reason"]})
        strategy_filter = filter_cols[0].selectbox("Strategy", ["All", *strategies])
        symbol_filter = filter_cols[1].selectbox("Symbol", ["All", *symbols])
        decision_filter = filter_cols[2].selectbox("Decision", ["All", *decisions])
        reason_filter = filter_cols[3].selectbox("Reason", ["All", *reasons])
        date_filter = filter_cols[4].text_input("UTC date", placeholder="YYYY-MM-DD")
        filtered = decision_history(
            strategy=None if strategy_filter == "All" else strategy_filter,
            symbol=None if symbol_filter == "All" else symbol_filter,
            decision=None if decision_filter == "All" else decision_filter,
            reason=None if reason_filter == "All" else reason_filter,
            date=date_filter or None,
        )
        st.dataframe(pd.DataFrame(filtered), width="stretch", hide_index=True)
        st.markdown("**Rolling risk metrics**")
        st.json(metrics)
        st.markdown("**Activation readiness — paper execution must remain disabled**")
        st.dataframe(pd.DataFrame(readiness["blockers"]), width="stretch", hide_index=True)
        config_health = configuration_health()
        st.markdown("**Configuration health**")
        st.dataframe(pd.DataFrame(config_health.get("fields", [])), width="stretch", hide_index=True)
except Exception as exc:
    st.error(f"Risk operations history could not be read safely: {exc}")

st.subheader("Canonical accounting transactions")
accounting_transactions = accounting_transaction_status(ROOT / "data" / "accounting_generations")
accounting_cols = st.columns(4)
accounting_cols[0].metric("Pointer", accounting_transactions["pointer_status"])
accounting_cols[1].metric("Generation", accounting_transactions["current_generation"] or "INACTIVE")
accounting_cols[2].metric("Lineage", accounting_transactions["lineage_health"])
accounting_cols[3].metric("Snapshot", accounting_transactions["snapshot_health"])
responsive_table(pd.DataFrame(detail_rows(accounting_transactions, (
    ("parent_generation", "Parent generation"), ("manifest_validation", "Manifest validation"),
    ("pending_activation", "Pending activation"), ("generation_age_seconds", "Generation age (seconds)"),
    ("last_accounting_event", "Last accounting event"), ("strategy_count", "Strategies"),
))))

st.subheader("Published health artifacts")
rows = []
for relative in (
    "data/live_runtime_status.json",
    "data/portfolio_projection_rebuild_report.json",
    "data/derived_portfolio_state_refresh_report.json",
    "data/paper_tracker_projection_repair_report.json",
):
    path = ROOT / relative
    payload, error = read_json(path)
    timestamp = None
    if payload:
        for key in ("updated_at", "refreshed_at", "repaired_at", "rebuilt_at"):
            if payload.get(key):
                timestamp = payload[key]
                break
    rows.append({"Artifact": relative, "Status": "Valid" if payload else error, "Timestamp": timestamp or "Unavailable"})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.info("Use the command-line validation and monitoring tools for operational actions. No control on this page writes runtime or accounting state.")
