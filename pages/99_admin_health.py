"""Read-only operational health presentation."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ui.auth import require_dashboard_login
from ui.responsive import apply_responsive_styles
from ui.runtime_status import load_runtime_status, runtime_freshness, runtime_state


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
