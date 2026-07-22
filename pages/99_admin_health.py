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
from dashboard.evidence_campaign_reader import evidence_campaign_status
from dashboard.migration_approval_reader import migration_approval_status
from dashboard.review_workflow_reader import review_workflow_status
from dashboard.operations_presentation import badge_color, detail_rows, status_meta


ROOT = Path(__file__).resolve().parents[1]


def render_status_badge(column, label, value, *, tone=None, help_text=None):
    display, inferred_tone, _ = status_meta(value)
    with column:
        st.caption(label)
        st.badge(display, color=badge_color(tone or inferred_tone), help=help_text)


def operations_table(data):
    return responsive_table(data, row_height=36)


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
    render_status_badge(cols[0], "Runtime", str(state.get("health", state.get("title", "Unknown"))), help_text="Runtime status shows whether the monitoring process is healthy.")
    render_status_badge(cols[1], "Freshness", str(freshness.get("label", "Unknown")), help_text="Data recency shows how recently runtime status was refreshed.")
    cols[2].metric("Last cycle", str(runtime.get("last_cycle_at") or "Not available"))
    cols[3].metric("Cycle count", runtime.get("cycle_count") if runtime.get("cycle_count") is not None else "Not available")
except Exception:
    st.error("Runtime status could not be read safely.")

st.subheader("Pre-trade risk")
risk = load_risk_diagnostics()
risk_cols = st.columns(4)
render_status_badge(risk_cols[0], "Risk", risk["engine_status"], tone="red" if risk["engine_status"] in {"BLOCKED", "ERROR"} else "green")
render_status_badge(risk_cols[1], "Kill switch", "ACTIVE" if risk["kill_switch_active"] else "INACTIVE", tone="red" if risk["kill_switch_active"] else "grey")
render_status_badge(risk_cols[2], "Trading", "ENABLED" if risk["trading_enabled"] else "DISABLED", tone="green" if risk["trading_enabled"] else "grey", help_text="Disabled trading is expected while monitor-only mode is active.")
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
    render_status_badge(producer_cols[0], "Framework", non_fill["status"])
    render_status_badge(producer_cols[1], "Validation", non_fill["validation_health"])
    producer_cols[2].metric("Production producers", len(non_fill["active_production_producers"]))
    producer_cols[3].metric("Duplicate conflicts", non_fill["duplicate_conflict_count"])
    non_fill_details = {**non_fill,
                        "latest_envelope": (non_fill.get("latest_non_fill") or {}).get("event_id"),
                        "latest_invalid_reason": (non_fill.get("latest_invalid") or {}).get("reason")}
    operations_table(pd.DataFrame(detail_rows(non_fill_details, (
        ("supported_event_types", "Supported event types"), ("unavailable_producers", "Unavailable producers"),
        ("counts_by_event_type", "Observations by type"), ("source_authority", "Source authority"),
        ("last_observation_timestamp", "Last observation"), ("latest_envelope", "Latest envelope"),
        ("latest_invalid_reason", "Latest invalid event"),
    ))))

with st.expander("Canonical opening snapshot", expanded=False):
    opening = opening_snapshot_status(ROOT / "data" / "opening_snapshot_candidates")
    st.caption("Read-only inactive candidate review. Validation and approval cannot activate accounting.")
    opening_cols=st.columns(4)
    render_status_badge(opening_cols[0], "Candidate", opening.get("status", "ERROR")); render_status_badge(opening_cols[1], "Readiness", opening.get("readiness", "NOT_READY"))
    render_status_badge(opening_cols[2], "Approval", opening.get("approval", "UNAPPROVED")); render_status_badge(opening_cols[3], "Pointer", opening.get("pointer", "UNKNOWN"))
    operations_table(pd.DataFrame(detail_rows(opening, (
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
    render_status_badge(evidence_cols[0], "Evidence Pack Status", evidence.get("status", "ERROR"), help_text="A Frozen Evidence Pack is the immutable evidence basis for migration review.")
    evidence_cols[1].metric("Gap Count", evidence.get("gap_count") if evidence.get("gap_count") is not None else "Not available")
    evidence_cols[2].metric("Critical Gaps", evidence.get("critical_gaps") if evidence.get("critical_gaps") is not None else "Not available")
    evidence_cols[3].metric("Coverage %", evidence.get("coverage") if evidence.get("coverage") is not None else "Not available", help="Evidence Coverage measures verified historical support without filling unknowns.")
    operations_table(pd.DataFrame(detail_rows(evidence, (
        ("pack_id", "Current Frozen Pack"), ("previous_pack_id", "Previous Frozen Pack"), ("pack_version", "Pack Version"),
        ("cutoff", "Cut-off Date"), ("coverage_metrics", "Coverage Metrics"), ("coverage_improvement", "Coverage Improvement"),
        ("resolved_gaps", "Resolved Gaps"), ("outstanding_gaps", "Outstanding Gaps"), ("conflict_count", "Conflict Count"),
        ("evidence_count", "Evidence Count"), ("verification", "Evidence Confidence"), ("import_history", "Import History"),
        ("replay_readiness", "Replay Readiness"), ("opening_snapshot_readiness", "Opening Snapshot Readiness"),
        ("pack_hash", "Evidence hash"), ("error", "Diagnostic"),
    ))))

with st.expander("Evidence Campaign", expanded=False):
    campaign = evidence_campaign_status(frozen_evidence_root)
    st.caption("Read-only campaign workspace. Unknown evidence stays unknown; no accounting artifacts can be created or changed here.")
    campaign_cols = st.columns(4)
    render_status_badge(campaign_cols[0], "Current Campaign", campaign.get("status", "NOT_AVAILABLE"))
    campaign_cols[1].metric("Completion %", campaign.get("coverage") if campaign.get("coverage") is not None else "Not available")
    campaign_cols[2].metric("Critical blockers", campaign.get("critical_blockers") if campaign.get("critical_blockers") is not None else "Not available")
    render_status_badge(campaign_cols[3], "Opening Snapshot", campaign.get("readiness", "NOT_READY"))
    operations_table(pd.DataFrame(detail_rows(campaign, (
        ("campaign_id", "Campaign ID"), ("title", "Title"), ("cutoff", "Cut-off Date"),
        ("owner", "Owner"), ("priority", "Priority"), ("coverage_trend", "Coverage Trend"),
        ("recently_imported", "Recently Imported Documents"), ("outstanding_conflicts", "Outstanding Conflicts"),
        ("resolved_this_campaign", "Resolved This Campaign"), ("estimated_remaining_work", "Estimated Remaining Work"),
        ("readiness_reasons", "Readiness Explanation"), ("bundle_hash", "Bundle Hash"), ("error", "Diagnostic"),
    ))))
    if campaign.get("requirements"):
        st.markdown("**Required evidence**")
        operations_table(pd.DataFrame(campaign["requirements"]))
    if campaign.get("positions"):
        st.markdown("**Open positions**")
        operations_table(pd.DataFrame(campaign["positions"]))
    if campaign.get("cash"):
        st.markdown("**Cash evidence**")
        operations_table(pd.DataFrame(campaign["cash"]))
    if campaign.get("priorities"):
        st.markdown("**Outstanding work, highest priority first**")
        operations_table(pd.DataFrame(campaign["priorities"]))

with st.expander("Migration allocation and approval", expanded=False):
    migration = migration_approval_status(frozen_evidence_root)
    st.caption("Read-only governance proposals. No proposal creates accounting state, lots, candidates, generations, or pointers.")
    migration_cols=st.columns(4)
    render_status_badge(migration_cols[0], "Migration Pack Status", migration.get("status", "ERROR"));migration_cols[1].metric("Pending Proposals",migration.get("pending"))
    migration_cols[2].metric("Approved",migration.get("approved"));migration_cols[3].metric("Rejected",migration.get("rejected"))
    operations_table(pd.DataFrame(detail_rows(migration, (("coverage", "Coverage %"), ("critical", "Critical Materiality"),
        ("readiness", "Readiness"), ("pack_id", "Pack ID"), ("error", "Diagnostic")))))

with st.expander("Operator migration review", expanded=False):
    review=review_workflow_status(frozen_evidence_root)
    st.caption("Authenticated read-only review. Decisions are created explicitly through the offline governance service; this dashboard has no approval controls.")
    review_cols=st.columns(4);render_status_badge(review_cols[0], "Review Status", review.get("status", "ERROR"));review_cols[1].metric("Outstanding Reviews",review.get("outstanding"));review_cols[2].metric("Critical Pending",review.get("critical_pending"));review_cols[3].metric("Approval Coverage",f"{review.get('coverage',0)}%")
    operations_table(pd.DataFrame(detail_rows(review, (("evidence_version", "Evidence Version"),
        ("pack_version", "Approval Pack Version"), ("error", "Diagnostic")))))
    proposals = review.get("proposals") or []
    if proposals:
        operations_table(pd.DataFrame(proposals))

st.subheader("Accounting observation envelopes")
envelopes = accounting_observation_status(ROOT / "data" / "accounting_observations" / "envelopes.jsonl",
                                          ROOT / "data" / "accounting_observations" / "validation_failures.jsonl")
envelope_cols = st.columns(4)
render_status_badge(envelope_cols[0], "Envelope health", envelopes["health"])
envelope_cols[1].metric("Envelope version", envelopes["version"])
render_status_badge(envelope_cols[2], "Validation", envelopes["validation"])
envelope_cols[3].metric("Observation count", envelopes["count"])
latest_envelope = envelopes.get("latest") or {}
operations_table(pd.DataFrame([
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
    render_status_badge(ops[0], "Accounting", accounting_label)
    ops[1].metric("Approvals today", metrics["APPROVED"])
    ops[2].metric("Rejections today", metrics["REJECTED"])
    ops[3].metric("Blocked / monitor", f"{metrics['BLOCKED']} / {metrics['MONITOR_ONLY']}")
    operations_table(pd.DataFrame([
        {"Item": "Last evaluation", "Value": metrics["last_evaluation_timestamp"] or "None"},
        {"Item": "Average latency", "Value": f"{metrics['average_latency_ms']} ms" if metrics["average_latency_ms"] is not None else "Not available"},
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
        operations_table(pd.DataFrame(filtered))
        st.markdown("**Rolling risk metrics**")
        st.json(metrics)
        st.markdown("**Activation readiness — paper execution must remain disabled**")
        operations_table(pd.DataFrame(readiness["blockers"]))
        config_health = configuration_health()
        st.markdown("**Configuration health**")
        operations_table(pd.DataFrame(config_health.get("fields", [])))
except Exception as exc:
    st.error(f"Risk operations history could not be read safely: {exc}")

st.subheader("Canonical accounting transactions")
accounting_transactions = accounting_transaction_status(ROOT / "data" / "accounting_generations")
accounting_cols = st.columns(4)
render_status_badge(accounting_cols[0], "Pointer", accounting_transactions["pointer_status"])
render_status_badge(accounting_cols[1], "Generation", accounting_transactions["current_generation"] or "INACTIVE")
render_status_badge(accounting_cols[2], "Lineage", accounting_transactions["lineage_health"])
render_status_badge(accounting_cols[3], "Snapshot", accounting_transactions["snapshot_health"])
operations_table(pd.DataFrame(detail_rows(accounting_transactions, (
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
    rows.append({"Artifact": relative, "Status": "Valid" if payload else error, "Timestamp": timestamp or "Not available"})
operations_table(pd.DataFrame(rows))

st.info("Use the command-line validation and monitoring tools for operational actions. No control on this page writes runtime or accounting state.")
