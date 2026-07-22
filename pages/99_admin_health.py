"""Read-only operational health presentation."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles
from ui.runtime_status import load_runtime_status, runtime_freshness, runtime_state
from risk_engine.diagnostics import load_risk_diagnostics
from risk_engine.operations import activation_readiness, configuration_health, decision_history, risk_metrics
from canonical_accounting.successor import accounting_transaction_status


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
    st.caption(
        f"Last evaluation: {metrics['last_evaluation_timestamp'] or 'None'} | "
        f"Average latency: {metrics['average_latency_ms'] or 'Unavailable'} ms | "
        f"Readiness: {'READY' if readiness['ready'] else 'NOT READY'}"
    )
    st.caption(
        "Latest proposal: "
        f"{latest_history.get('strategy', 'None')} / {latest_history.get('symbol', 'None')} "
        f"{latest_history.get('side', '')} {latest_history.get('quantity', '')} | "
        f"Decision: {latest_history.get('decision', 'None')} | "
        f"Reason: {latest_history.get('reason', 'None')}"
    )
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
st.caption(
    f"Parent: {accounting_transactions.get('parent_generation') or 'None'} | "
    f"Manifest: {accounting_transactions['manifest_validation']} | "
    f"Pending activation: {accounting_transactions['pending_activation']} | "
    f"Age: {accounting_transactions.get('generation_age_seconds') or 'Unavailable'} seconds | "
    f"Last event: {accounting_transactions.get('last_accounting_event') or 'None'} | "
    f"Strategies: {accounting_transactions.get('strategy_count', 0)}"
)

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
