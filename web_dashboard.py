import html
import json
import os
from pathlib import Path
from urllib.parse import quote

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

from dashboard.data_loader import load_csv
from dashboard.metrics import unrealised_pnl_from_holdings
from execution.trade_audit import build_trade_audit_trail
from reporting.paper_performance import challenge_initial_capital
from ui.auth import require_dashboard_login
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)
from ui.runtime_status import load_runtime_status, runtime_freshness, runtime_state

PROJECT_ROOT = Path(__file__).resolve().parent
SCANNER_OUTPUT_DIR = PROJECT_ROOT / "data" / "global_scanner"
SCANNER_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universes"
SCANNER_HISTORY_DIR = SCANNER_OUTPUT_DIR / "history"
SCANNER_REQUIRED_OUTPUTS = [
    "universe_validated.csv",
    "latest_rankings.csv",
    "selected_candidates.csv",
]
SCANNER_STALE_AFTER = pd.Timedelta(hours=6)
SCANNER_DISPLAY_TIMEZONE = "Europe/London"
SCANNER_TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M %Z"

try:
    from ui.auto_refresh import (
        fragment_runner as _shared_fragment_runner,
        live_mode_controls as _shared_live_mode_controls,
    )
except ImportError:
    _shared_fragment_runner = None
    _shared_live_mode_controls = None


def fragment_runner():
    if _shared_fragment_runner is not None:
        return _shared_fragment_runner()
    if hasattr(st, "fragment"):
        return st.fragment
    if hasattr(st, "experimental_fragment"):
        return st.experimental_fragment
    return None


def live_mode_controls(interval_seconds=60, key="dashboard_live_mode", default_enabled=False):
    if _shared_live_mode_controls is not None:
        return _shared_live_mode_controls(
            interval_seconds=interval_seconds,
            key=key,
            default_enabled=default_enabled,
        )

    enabled_key = f"{key}_enabled"
    control_key = f"{enabled_key}_control"
    if enabled_key not in st.session_state:
        st.session_state[enabled_key] = bool(default_enabled)
    if control_key not in st.session_state:
        st.session_state[control_key] = bool(st.session_state[enabled_key])

    enabled = st.checkbox(
        "Live mode",
        key=control_key,
        help="Updates key cards without forcing full-page navigation where possible.",
    )
    st.caption(
        "Updates key cards without forcing full-page navigation where possible."
    )

    fragments_available = fragment_runner() is not None
    if enabled and not fragments_available:
        st.caption("Live mode unavailable in this Streamlit version.")
        enabled = False

    st.session_state[enabled_key] = bool(enabled)
    return {
        "enabled": bool(enabled),
        "interval_seconds": int(interval_seconds),
        "fragments_available": fragments_available,
        "method": "streamlit_fragment" if enabled and fragments_available else "manual",
    }


def inject_mobile_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 3rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 1280px;
        }

        .status-card {
            background: linear-gradient(135deg, #114f2f, #0d3823);
            border: 1px solid #2f9d5c;
            border-radius: 18px;
            padding: 16px 22px;
            margin-bottom: 24px;
            min-height: 70px;
        }

        .metric-card {
            background:#111827;
            border:1px solid #30363d;
            border-radius:18px;
            padding:16px;
            margin-bottom:16px;
            min-height:90px;
            box-shadow:0 4px 18px rgba(0,0,0,.25);
        }

        .metric-label {
            color:#9ca3af;
            font-size:14px;
            margin-bottom:6px;
        }

        .metric-value {
            color:white;
            font-size:24px;
            font-weight:700;
            line-height:1.2;
        }

        .metric-value-green {
            color:#68ff8b;
            font-size:24px;
            font-weight:700;
            line-height:1.2;
        }

        .signal-panel {
            background:#0b1220;
            border:1px solid rgba(148,163,184,0.22);
            border-radius:8px;
            padding:12px;
            margin:6px 0 14px 0;
        }

        .signal-row {
            display:grid;
            grid-template-columns:82px 1fr 76px;
            gap:10px;
            align-items:center;
            border-top:1px solid rgba(148,163,184,0.14);
            padding:8px 0;
        }

        .signal-row:first-child {
            border-top:0;
            padding-top:0;
        }

        .signal-ticker {
            color:#f8fafc;
            font-weight:700;
            font-size:15px;
        }

        .signal-detail {
            color:#cbd5e1;
            font-size:13px;
            overflow-wrap:anywhere;
        }

        .signal-weight {
            color:#94a3b8;
            font-size:13px;
            text-align:right;
        }

        .scanner-card {
            background:#0b1220;
            border:1px solid rgba(148,163,184,0.24);
            border-radius:8px;
            padding:16px;
            margin-bottom:14px;
            min-height:310px;
        }

        .scanner-card-head {
            display:flex;
            justify-content:space-between;
            gap:12px;
            align-items:flex-start;
            margin-bottom:8px;
        }

        .scanner-rank {
            color:#93c5fd;
            font-size:13px;
            font-weight:700;
        }

        .scanner-ticker {
            color:#f8fafc;
            font-size:20px;
            font-weight:760;
            line-height:1.15;
            overflow-wrap:anywhere;
        }

        .scanner-name {
            color:#cbd5e1;
            font-size:13px;
            margin-top:2px;
            overflow-wrap:anywhere;
        }

        .scanner-score {
            color:#68ff8b;
            font-size:16px;
            font-weight:760;
            text-align:right;
            white-space:nowrap;
        }

        .scanner-score-label {
            color:#94a3b8;
            font-size:11px;
            font-weight:500;
        }

        .scanner-summary {
            color:#e5e7eb;
            font-size:14px;
            line-height:1.35;
            margin:10px 0;
        }

        .scanner-badges {
            display:flex;
            flex-wrap:wrap;
            gap:6px;
            margin:8px 0;
        }

        .scanner-badge {
            color:#dbeafe;
            background:rgba(37,99,235,0.18);
            border:1px solid rgba(96,165,250,0.28);
            border-radius:999px;
            padding:2px 8px;
            font-size:12px;
            line-height:1.5;
        }

        .scanner-move {
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:2px 8px;
            font-size:12px;
            font-weight:700;
            margin-top:5px;
        }

        .scanner-move-up {
            color:#bbf7d0;
            background:rgba(22,101,52,0.22);
            border:1px solid rgba(74,222,128,0.28);
        }

        .scanner-move-down {
            color:#fecaca;
            background:rgba(153,27,27,0.22);
            border:1px solid rgba(248,113,113,0.28);
        }

        .scanner-move-new {
            color:#dbeafe;
            background:rgba(37,99,235,0.20);
            border:1px solid rgba(96,165,250,0.34);
        }

        .scanner-move-flat {
            color:#d1d5db;
            background:rgba(107,114,128,0.18);
            border:1px solid rgba(156,163,175,0.24);
        }

        .scanner-change-grid {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
            margin:10px 0 18px 0;
        }

        .scanner-change-card {
            background:#0b1220;
            border:1px solid rgba(148,163,184,0.22);
            border-radius:8px;
            padding:12px;
            min-height:116px;
        }

        .scanner-change-label {
            color:#94a3b8;
            font-size:12px;
            margin-bottom:6px;
        }

        .scanner-change-main {
            color:#f8fafc;
            font-size:17px;
            font-weight:760;
            overflow-wrap:anywhere;
        }

        .scanner-change-detail {
            color:#cbd5e1;
            font-size:13px;
            margin-top:5px;
        }

        @media (max-width: 768px) {
            .scanner-change-grid {
                grid-template-columns:1fr;
            }
        }

        .scanner-region-us {
            color:#dbeafe;
            background:rgba(37,99,235,0.20);
            border-color:rgba(96,165,250,0.34);
        }

        .scanner-region-europe {
            color:#ddd6fe;
            background:rgba(109,40,217,0.20);
            border-color:rgba(167,139,250,0.34);
        }

        .scanner-region-uk {
            color:#bae6fd;
            background:rgba(3,105,161,0.20);
            border-color:rgba(56,189,248,0.34);
        }

        .scanner-region-japan {
            color:#fecaca;
            background:rgba(185,28,28,0.18);
            border-color:rgba(248,113,113,0.30);
        }

        .scanner-region-asia {
            color:#fde68a;
            background:rgba(180,83,9,0.18);
            border-color:rgba(251,191,36,0.30);
        }

        .scanner-region-australia {
            color:#bbf7d0;
            background:rgba(21,128,61,0.18);
            border-color:rgba(74,222,128,0.30);
        }

        .scanner-region-global {
            color:#cffafe;
            background:rgba(14,116,144,0.18);
            border-color:rgba(34,211,238,0.30);
        }

        .scanner-region-crypto {
            color:#fed7aa;
            background:rgba(194,65,12,0.18);
            border-color:rgba(251,146,60,0.30);
        }

        .scanner-quality-pass {
            color:#bbf7d0;
            background:rgba(22,101,52,0.22);
            border-color:rgba(74,222,128,0.28);
        }

        .scanner-quality-fail {
            color:#fecaca;
            background:rgba(153,27,27,0.22);
            border-color:rgba(248,113,113,0.28);
        }

        .scanner-facts {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:6px 10px;
            color:#cbd5e1;
            font-size:12px;
            margin:8px 0;
        }

        .scanner-fact-label {
            color:#94a3b8;
        }

        .scanner-risk-profile {
            border:1px solid rgba(148,163,184,0.18);
            border-radius:8px;
            padding:10px;
            margin:10px 0;
            background:rgba(15,23,42,0.58);
        }

        .scanner-risk-title {
            color:#e5e7eb;
            font-size:12px;
            font-weight:760;
            margin-bottom:8px;
        }

        .scanner-risk-grid {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:8px;
            color:#cbd5e1;
            font-size:12px;
        }

        .scanner-risk-value {
            color:#f8fafc;
            font-size:14px;
            font-weight:720;
        }

        .scanner-compare-wrap {
            overflow-x:auto;
            margin-top:12px;
        }

        .scanner-compare-table {
            min-width:720px;
            border:1px solid rgba(148,163,184,0.18);
            border-radius:8px;
            overflow:hidden;
            background:rgba(15,23,42,0.46);
        }

        .scanner-compare-row {
            display:grid;
            grid-template-columns:minmax(140px,0.85fr) repeat(var(--compare-cols), minmax(132px,1fr));
            border-bottom:1px solid rgba(148,163,184,0.12);
        }

        .scanner-compare-row:last-child {
            border-bottom:0;
        }

        .scanner-compare-cell {
            padding:10px;
            color:#cbd5e1;
            font-size:12px;
            border-right:1px solid rgba(148,163,184,0.10);
            min-width:0;
            white-space:normal;
            overflow-wrap:anywhere;
            word-break:normal;
        }

        .scanner-compare-cell:last-child {
            border-right:0;
        }

        .scanner-compare-head {
            color:#f8fafc;
            font-weight:760;
            background:rgba(30,41,59,0.78);
            line-height:1.25;
        }

        .scanner-compare-label {
            color:#94a3b8;
            font-weight:720;
        }

        .scanner-compare-value {
            color:#f8fafc;
            font-weight:720;
            overflow-wrap:anywhere;
        }

        .scanner-compare-indicator {
            display:inline-flex;
            align-items:center;
            gap:4px;
            margin-top:4px;
            padding:2px 6px;
            border-radius:999px;
            font-size:11px;
            border:1px solid rgba(148,163,184,0.20);
        }

        .scanner-compare-strong {
            color:#bbf7d0;
            background:rgba(22,101,52,0.20);
            border-color:rgba(74,222,128,0.28);
        }

        .scanner-compare-high {
            color:#bfdbfe;
            background:rgba(37,99,235,0.16);
            border-color:rgba(96,165,250,0.24);
        }

        .scanner-compare-low {
            color:#fef3c7;
            background:rgba(180,83,9,0.16);
            border-color:rgba(251,191,36,0.24);
        }

        .scanner-compare-elevated {
            color:#fed7aa;
            background:rgba(194,65,12,0.18);
            border-color:rgba(251,146,60,0.28);
        }

        .scanner-bars {
            display:grid;
            gap:8px;
            margin:12px 0 10px 0;
        }

        .scanner-bar-row {
            display:grid;
            grid-template-columns:92px 1fr 48px;
            gap:8px;
            align-items:center;
            color:#cbd5e1;
            font-size:12px;
        }

        .scanner-bar-track {
            display:block;
            height:7px;
            border-radius:999px;
            background:rgba(148,163,184,0.16);
            overflow:hidden;
        }

        .scanner-bar-fill {
            display:block;
            height:100%;
            border-radius:999px;
            background:linear-gradient(90deg,#38bdf8,#68ff8b);
        }

        .scanner-card ul {
            margin:8px 0 0 18px;
            padding:0;
            color:#d1d5db;
            font-size:13px;
        }

        .scanner-card li {
            margin-bottom:4px;
        }

        .scanner-bullet-list {
            display:grid;
            gap:4px;
            margin-top:8px;
            color:#d1d5db;
            font-size:13px;
        }

        .scanner-bullet-item {
            display:grid;
            grid-template-columns:12px 1fr;
            gap:6px;
            line-height:1.35;
            min-width:0;
        }

        .scanner-bullet-item::before {
            content:"";
            width:5px;
            height:5px;
            border-radius:999px;
            background:#94a3b8;
            margin-top:7px;
        }

        .scanner-bullet-text {
            overflow-wrap:anywhere;
        }

        .signal-badge {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-width:52px;
            border-radius:999px;
            padding:3px 8px;
            font-size:11px;
            font-weight:750;
            letter-spacing:.04em;
            border:1px solid transparent;
        }

        .signal-buy {
            color:#dcfce7;
            background:rgba(22,163,74,0.22);
            border-color:rgba(34,197,94,0.38);
        }

        .signal-hold {
            color:#dbeafe;
            background:rgba(37,99,235,0.20);
            border-color:rgba(96,165,250,0.34);
        }

        .signal-sell {
            color:#fee2e2;
            background:rgba(220,38,38,0.20);
            border-color:rgba(248,113,113,0.34);
        }

        .signal-neutral {
            color:#e5e7eb;
            background:rgba(107,114,128,0.22);
            border-color:rgba(156,163,175,0.34);
        }

        .brief-card {
            background:#0f172a;
            border:1px solid rgba(148,163,184,0.28);
            border-radius:10px;
            padding:20px;
            margin:10px 0 18px 0;
            box-shadow:0 8px 24px rgba(0,0,0,.22);
        }

        .brief-kicker {
            color:#94a3b8;
            font-size:13px;
            text-transform:uppercase;
            letter-spacing:.08em;
            margin-bottom:8px;
        }

        .brief-title {
            color:#f8fafc;
            font-size:28px;
            font-weight:750;
            line-height:1.15;
            margin-bottom:8px;
        }

        .brief-copy {
            color:#cbd5e1;
            font-size:15px;
            line-height:1.45;
            margin-bottom:14px;
        }

        .brief-grid {
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:10px;
        }

        .brief-item {
            border:1px solid rgba(148,163,184,0.20);
            border-radius:8px;
            padding:10px 12px;
            background:rgba(15,23,42,0.72);
        }

        .brief-label {
            color:#94a3b8;
            font-size:12px;
            margin-bottom:4px;
        }

        .brief-value {
            color:#f8fafc;
            font-size:15px;
            font-weight:650;
            overflow-wrap:anywhere;
        }

        .activity-row {
            border-left:2px solid rgba(148,163,184,0.35);
            padding:0 0 10px 12px;
            margin-bottom:8px;
        }

        .activity-title {
            color:#f8fafc;
            font-weight:650;
            margin-bottom:2px;
        }

        .activity-detail {
            color:#cbd5e1;
            font-size:14px;
        }

        .portfolio-hero {
            background:#0b1220;
            border:1px solid rgba(148,163,184,0.22);
            border-radius:8px;
            padding:14px;
            margin:6px 0 10px 0;
        }

        .portfolio-hero-grid {
            display:grid;
            grid-template-columns:minmax(260px,1.6fr) minmax(260px,1.2fr) minmax(240px,1fr);
            gap:10px;
            align-items:stretch;
        }

        .portfolio-panel {
            border:1px solid rgba(148,163,184,0.18);
            border-radius:6px;
            background:rgba(15,23,42,0.70);
            padding:10px 12px;
        }

        .portfolio-kpi-grid {
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:8px;
        }

        .portfolio-kpi {
            border-bottom:1px solid rgba(148,163,184,0.13);
            padding:0 0 7px 0;
        }

        .portfolio-main-value {
            color:#f8fafc;
            font-size:40px;
            font-weight:760;
            line-height:1.1;
            margin-top:4px;
        }

        .portfolio-small-value {
            color:#f8fafc;
            font-size:17px;
            font-weight:680;
            line-height:1.25;
            overflow-wrap:anywhere;
        }

        .status-strip {
            display:flex;
            flex-wrap:wrap;
            gap:8px;
            align-items:center;
            color:#94a3b8;
            font-size:12px;
            margin-bottom:8px;
        }

        .runtime-badge {
            display:inline-block;
            border:1px solid rgba(104,255,139,0.35);
            border-radius:999px;
            padding:3px 9px;
            color:#b7f7c8;
            font-size:12px;
        }

        .research-note {
            border:1px solid rgba(148,163,184,0.18);
            border-radius:6px;
            background:rgba(15,23,42,0.50);
            color:#cbd5e1;
            font-size:13px;
            padding:8px 10px;
            margin:8px 0 10px 0;
        }

        @media (max-width: 768px) {
            .brief-title {
                font-size:23px;
            }

            .brief-grid {
                grid-template-columns:1fr;
            }

            .portfolio-hero-grid {
                grid-template-columns:1fr;
            }

            .portfolio-kpi-grid {
                grid-template-columns:1fr;
            }

            .portfolio-main-value {
                font-size:30px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_card(last_updated):
    st.markdown(
        f"""
        <div class="status-card">
            <div style="font-size:17px;font-weight:700;color:white;">
                🟢 Live Data Connected
            </div>
            <div style="margin-top:6px;font-size:15px;color:#b7f7c8;">
                Updated: {last_updated}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label, value, green=False):
    value_class = "metric-value-green" if green else "metric-value"

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="{value_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_json_file(path):
    path = Path(path)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_scanner_csv(filename):
    return load_csv(SCANNER_OUTPUT_DIR / filename)


def scanner_utc_timestamp(value):
    if value is None or value == "":
        return None

    try:
        timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None

    if pd.isna(timestamp):
        return None

    return timestamp


def scanner_file_modified_timestamp(filename):
    path = SCANNER_OUTPUT_DIR / filename
    if not path.exists():
        return None

    try:
        return pd.to_datetime(path.stat().st_mtime, unit="s", utc=True)
    except Exception:
        return None


def format_scanner_timestamp(value, fallback="Unknown"):
    timestamp = scanner_utc_timestamp(value)
    if timestamp is None:
        return fallback

    try:
        return timestamp.tz_convert(SCANNER_DISPLAY_TIMEZONE).strftime(
            SCANNER_TIMESTAMP_FORMAT
        )
    except Exception:
        return fallback


def scanner_file_modified_label(filename):
    path = SCANNER_OUTPUT_DIR / filename
    if not path.exists():
        return "Missing"

    return format_scanner_timestamp(
        scanner_file_modified_timestamp(filename),
        "Unknown",
    )


def scanner_history_timestamp_value(path, frame):
    if "scanner_run_timestamp" in frame.columns and not frame.empty:
        value = frame["scanner_run_timestamp"].dropna()
        if not value.empty:
            timestamp = scanner_utc_timestamp(value.iloc[0])
            if timestamp is not None:
                return timestamp

    stem = path.name.replace("_rankings.csv", "")
    parsed = scanner_utc_timestamp(stem.replace("_", " ", 1))
    if parsed is None:
        parsed = scanner_utc_timestamp(
            pd.to_datetime(stem, format="%Y-%m-%d_%H%M%S_%f", errors="coerce")
        )
    if parsed is not None:
        return parsed

    try:
        return pd.to_datetime(path.stat().st_mtime, unit="s", utc=True)
    except Exception:
        return None


def scanner_output_state():
    files = {
        filename: SCANNER_OUTPUT_DIR / filename
        for filename in SCANNER_REQUIRED_OUTPUTS
    }
    missing = [
        filename
        for filename, path in files.items()
        if not path.exists()
    ]
    latest_rankings = files["latest_rankings.csv"]
    modified = None
    age = None
    stale = False

    if latest_rankings.exists():
        try:
            modified = scanner_file_modified_timestamp("latest_rankings.csv")
            age = pd.Timestamp.now(tz="UTC") - modified
            stale = bool(age > SCANNER_STALE_AFTER)
        except Exception:
            stale = True

    return {
        "missing": missing,
        "modified": modified,
        "age": age,
        "stale": stale if not missing else False,
        "fresh": not missing and not stale,
    }


def scanner_state_label(state):
    if state["missing"]:
        return "missing"
    if state["stale"]:
        return "stale"
    return "fresh"


def render_scanner_auto_refresh_status(show_messages=True):
    state = scanner_output_state()
    label = scanner_state_label(state)

    if label == "fresh":
        modified = state.get("modified")
        if show_messages:
            if modified is not None:
                st.success(
                    "Scanner output is fresh. "
                    f"Last refreshed {format_scanner_timestamp(modified)}."
                )
            else:
                st.success("Scanner output is fresh.")
        return scanner_output_state()

    session_key = f"global_scanner_auto_refresh_attempted_{label}"
    if st.session_state.get(session_key):
        if show_messages:
            if label == "missing":
                st.warning(
                    "Scanner outputs are missing. Automatic refresh was already "
                    "attempted in this session."
                )
            else:
                st.warning(
                    "Scanner outputs are stale. Automatic refresh was already "
                    "attempted in this session."
                )
        return scanner_output_state()

    st.session_state[session_key] = True
    reason = "missing" if label == "missing" else "older than 6 hours"

    try:
        if show_messages:
            with st.spinner(f"Refreshing research scanner because outputs are {reason}..."):
                result = run_research_scanner_from_dashboard()
        else:
            result = run_research_scanner_from_dashboard()
        if show_messages:
            st.success(
                "Scanner refreshed automatically: "
                f"{result.get('validated_rows', 0)} validated, "
                f"{result.get('selected_rows', 0)} selected, "
                f"{result.get('quality_failures', 0)} failed."
            )
    except Exception as exc:
        if show_messages:
            st.error(f"Scanner refresh failed: {exc}")

    return scanner_output_state()


def scanner_bool_series(frame, column):
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=bool)

    return frame[column].astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y"}
    )


def load_scanner_history():
    if not SCANNER_HISTORY_DIR.exists():
        return []

    snapshots = []
    for path in sorted(SCANNER_HISTORY_DIR.glob("*_rankings.csv")):
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue

        timestamp_value = scanner_history_timestamp_value(path, frame)
        timestamp = format_scanner_timestamp(timestamp_value)
        snapshots.append(
            {
                "path": path,
                "timestamp": timestamp,
                "sort_timestamp": timestamp_value,
                "frame": frame,
            }
        )

    return sorted(
        snapshots,
        key=lambda snapshot: snapshot["sort_timestamp"] or pd.Timestamp.min.tz_localize("UTC"),
    )


def scanner_history_timestamp(path, frame):
    return format_scanner_timestamp(scanner_history_timestamp_value(path, frame))


def scanner_selected_rows(frame):
    if frame.empty:
        return frame.copy()

    if "selected_for_research" not in frame.columns:
        return frame.head(15).copy()

    selected_mask = scanner_bool_series(frame, "selected_for_research")
    return frame.loc[selected_mask].copy()


def run_research_scanner_from_dashboard():
    from research.global_scanner import run_global_scanner

    return run_global_scanner(
        universe_dir=SCANNER_UNIVERSE_DIR,
        output_dir=SCANNER_OUTPUT_DIR,
    )


def format_london_time(value, fallback="Unknown"):
    if not value:
        return fallback

    try:
        timestamp = pd.to_datetime(value, utc=True)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        timestamp = timestamp.tz_convert("Europe/London")
        today = pd.Timestamp.now(tz="Europe/London")

        if timestamp.date() == today.date():
            return timestamp.strftime("Today at %H:%M")

        return timestamp.strftime("%d %b at %H:%M")
    except Exception:
        return fallback


def money_label(value):
    try:
        return f"£{float(value):,.2f}"
    except Exception:
        return "Unavailable"


def percent_label(value):
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "Unavailable"


def numeric_value(value, fallback=0.0):
    try:
        value = float(value)
    except Exception:
        return fallback

    if pd.isna(value):
        return fallback

    return value


def latest_trade_details(trades):
    if trades is None or trades.empty:
        return {
            "label": "No trade recorded",
            "detail": "Trade journal is empty.",
            "time": "",
            "action": "",
            "ticker": "",
        }

    latest = trades.iloc[-1]
    action = str(latest.get("action", "TRADE")).upper()
    ticker = str(latest.get("ticker", "UNKNOWN")).upper()
    date_value = latest.get("date", "")
    time_value = latest.get("time", "")
    timestamp_text = " ".join(
        str(part)
        for part in [date_value, time_value]
        if part is not None and str(part).strip() and str(part) != "nan"
    )
    label = f"{action} {ticker}".strip()
    detail = format_london_time(timestamp_text, "Time unavailable")

    return {
        "label": label,
        "detail": detail,
        "time": detail,
        "action": action,
        "ticker": ticker,
    }


def latest_notification_details():
    state = load_json_file("data/notification_state.json")
    sent_log = state.get("sent_log") or []

    if not sent_log:
        return {
            "label": "No notification recorded",
            "detail": "Notification log is empty.",
        }

    latest = sent_log[-1]
    event_type = str(latest.get("type", "notification")).replace("_", " ").title()
    ticker = latest.get("ticker")
    detail = format_london_time(latest.get("timestamp"), "Time unavailable")
    if ticker:
        detail = f"{ticker} | {detail}"

    return {
        "label": event_type,
        "detail": detail,
    }


def latest_research_details():
    reports = sorted(
        Path("research/report_exports/campaign_reports").glob("campaign_001*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not reports:
        return {
            "label": "No research report found",
            "detail": "Campaign reports are not available yet.",
        }

    report = reports[0]
    detail = format_london_time(
        pd.Timestamp.fromtimestamp(report.stat().st_mtime),
        "Time unavailable",
    )
    return {
        "label": "Campaign 001 recommends keeping the current exit strategy",
        "detail": detail,
    }


def runtime_brief_details(status):
    state = runtime_state(status)
    freshness = runtime_freshness(status)
    latest_event = status.get("latest_runtime_event") or {}
    last_scan = (
        latest_event.get("timestamp")
        or status.get("last_cycle_at")
        or status.get("updated_at")
    )

    return {
        "state": state,
        "freshness": freshness,
        "last_scan": format_london_time(last_scan, "No completed scan found"),
        "latest_event": latest_event,
        "next_scan": state.get("next_scan_display", "Not scheduled"),
        "next_cycle_at": state.get("next_cycle_at"),
    }


def home_recommendation(runtime_details, latest_trade):
    state = runtime_details["state"]
    freshness = runtime_details["freshness"]

    if not state.get("running") or not state.get("healthy"):
        return "Check runtime before the next scan."

    if freshness.get("level") in {"stale", "very-stale", "missing"}:
        return "Check runtime freshness before relying on the latest figures."

    if latest_trade.get("action") in {"BUY", "SELL"}:
        return "No action required before next scheduled scan."

    return "No action required."


def render_activity_item(title, detail):
    st.markdown(
        f"""
        <div class="activity-row">
            <div class="activity-title">{html.escape(str(title))}</div>
            <div class="activity-detail">{html.escape(str(detail))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def investor_cycle_message(runtime_event, state):
    raw_message = str((runtime_event or {}).get("message") or "").strip()
    raw_type = str((runtime_event or {}).get("type") or "").strip()
    details = (runtime_event or {}).get("details") or {}
    combined = f"{raw_type} {raw_message}".lower()
    paper_trades = int(details.get("paper_trades") or details.get("trade_count") or 0)

    if "safety" in combined and ("blocked" in combined or "prevented" in combined):
        return (
            "No strategy scan was performed because a safety check prevented execution. "
            "Your portfolio was unchanged."
        )

    if paper_trades > 0 or (
        "trade" in combined
        and any(word in combined for word in ["executed", "recorded", "placed"])
        and "no trade" not in combined
    ):
        return "Strategy completed and executed new trades."

    if any(phrase in combined for phrase in ["no trade", "0 trades", "no new paper trades"]):
        return "Strategy completed. No new trading opportunities were found."

    if "paper strategy pipeline completed" in combined or "strategy completed" in combined:
        return "Strategy scan completed successfully."

    if raw_message:
        return raw_message

    return state.get("activity", "Runtime status unavailable.")


def render_live_status_strip(runtime_label, freshness_label, last_scan, next_cycle_at, fallback_next):
    target_timestamp = ""
    try:
        if next_cycle_at:
            target_timestamp = pd.to_datetime(next_cycle_at, utc=True).isoformat()
    except Exception:
        target_timestamp = ""

    payload = {
        "runtime": str(runtime_label),
        "freshness": str(freshness_label),
        "lastScan": str(last_scan),
        "nextTarget": target_timestamp,
        "fallbackNext": str(fallback_next),
    }

    countdown_html = f"""
        <div class="status-strip">
            <span class="status-pill" id="runtime-badge"></span>
            <span class="status-pill" id="freshness-badge"></span>
            <span class="status-text" id="last-scan-label"></span>
            <span class="status-text">Next <span id="next-countdown"></span></span>
        </div>
        <style>
            body {{
                margin:0;
                background:transparent;
                font-family: "Source Sans Pro", sans-serif;
            }}
            .status-strip {{
                display:flex;
                flex-wrap:wrap;
                gap:8px;
                align-items:center;
                color:#94a3b8;
                font-size:12px;
                line-height:1.4;
                margin:0;
            }}
            .status-pill {{
                display:inline-block;
                border-radius:999px;
                padding:3px 10px;
                font-size:12px;
                font-weight:650;
                letter-spacing:.02em;
                border:1px solid rgba(148,163,184,0.28);
            }}
            .status-text {{
                color:#94a3b8;
                white-space:nowrap;
            }}
            .status-green {{
                color:#b7f7c8;
                background:rgba(34,197,94,0.10);
                border-color:rgba(34,197,94,0.42);
            }}
            .status-blue {{
                color:#bfdbfe;
                background:rgba(59,130,246,0.10);
                border-color:rgba(59,130,246,0.42);
            }}
            .status-amber {{
                color:#fde68a;
                background:rgba(245,158,11,0.10);
                border-color:rgba(245,158,11,0.45);
            }}
            .status-red {{
                color:#fecaca;
                background:rgba(239,68,68,0.10);
                border-color:rgba(239,68,68,0.45);
            }}
            .status-grey {{
                color:#cbd5e1;
                background:rgba(148,163,184,0.08);
                border-color:rgba(148,163,184,0.28);
            }}
        </style>
        <script>
            const data = {json.dumps(payload)};

            function addStatusClass(element, level) {{
                element.classList.remove("status-green", "status-blue", "status-amber", "status-red", "status-grey");
                element.classList.add(level);
            }}

            function freshnessClass(label) {{
                const value = String(label || "").toLowerCase();
                if (value.includes("live")) return "status-green";
                if (value.includes("recent")) return "status-blue";
                if (value.includes("slightly")) return "status-amber";
                if (value.includes("stale")) return "status-red";
                return "status-grey";
            }}

            const runtimeBadge = document.getElementById("runtime-badge");
            const freshnessBadge = document.getElementById("freshness-badge");
            runtimeBadge.textContent = `🟢 Runtime ${{String(data.runtime).toUpperCase()}}`;
            freshnessBadge.textContent = `Data ${{String(data.freshness).toUpperCase()}}`;
            addStatusClass(runtimeBadge, String(data.runtime).toLowerCase().includes("live") ? "status-green" : "status-grey");
            addStatusClass(freshnessBadge, freshnessClass(data.freshness));
            document.getElementById("last-scan-label").textContent = `Last Scan ${{data.lastScan}}`;

            const target = data.nextTarget ? new Date(data.nextTarget).getTime() : null;
            const countdown = document.getElementById("next-countdown");

            function formatRemaining(seconds) {{
                const safeSeconds = Math.max(0, Math.floor(seconds));
                const hours = Math.floor(safeSeconds / 3600);
                const minutes = Math.floor((safeSeconds % 3600) / 60);
                const secs = safeSeconds % 60;
                if (hours > 0) {{
                    return `${{hours}}h ${{String(minutes).padStart(2, "0")}}m`;
                }}
                return `${{String(minutes).padStart(2, "0")}}m ${{String(secs).padStart(2, "0")}}s`;
            }}

            function tick() {{
                if (!target || Number.isNaN(target)) {{
                    countdown.textContent = data.fallbackNext || "Waiting for next scan";
                    return;
                }}

                const remaining = Math.floor((target - Date.now()) / 1000);
                if (remaining <= -60) {{
                    countdown.textContent = "Waiting for next scan";
                }} else if (remaining <= 0) {{
                    countdown.textContent = "Due now";
                }} else {{
                    countdown.textContent = formatRemaining(remaining);
                }}
            }}

            tick();
            setInterval(tick, 1000);
        </script>
        """
    st.iframe(
        "data:text/html;charset=utf-8," + quote(countdown_html),
        height=30,
    )


def render_investment_brief(
    runtime_details,
    latest_trade,
    portfolio_value,
    total_return,
    cash,
    buying_power,
    open_positions,
    win_rate,
):
    state = runtime_details["state"]
    freshness = runtime_details["freshness"]
    research = latest_research_details()
    runtime_label = (
        "Live"
        if state.get("running") and state.get("healthy")
        else state.get("health", "Check")
    )
    return_label = "UP" if numeric_value(total_return) >= 0 else "DOWN"
    notification = latest_notification_details()

    render_live_status_strip(
        runtime_label,
        freshness.get("label", "Unknown"),
        runtime_details["last_scan"],
        runtime_details.get("next_cycle_at"),
        runtime_details["next_scan"],
    )

    st.markdown(
        f"""
        <div class="portfolio-hero">
            <div class="portfolio-hero-grid">
                <div class="portfolio-panel">
                    <div class="brief-label">Portfolio Value</div>
                    <div class="portfolio-main-value">{html.escape(money_label(portfolio_value))}</div>
                    <div class="activity-detail">{html.escape(return_label)} {html.escape(percent_label(total_return))}</div>
                </div>
                <div class="portfolio-panel">
                    <div class="portfolio-kpi-grid">
                        <div class="portfolio-kpi">
                            <div class="brief-label">Cash</div>
                            <div class="portfolio-small-value">{html.escape(money_label(cash))}</div>
                        </div>
                        <div class="portfolio-kpi">
                            <div class="brief-label">Buying Power</div>
                            <div class="portfolio-small-value">{html.escape(money_label(buying_power))}</div>
                        </div>
                        <div class="portfolio-kpi">
                            <div class="brief-label">Open Positions</div>
                            <div class="portfolio-small-value">{html.escape(str(open_positions))}</div>
                        </div>
                        <div class="portfolio-kpi">
                            <div class="brief-label">Win Rate</div>
                            <div class="portfolio-small-value">{html.escape(percent_label(win_rate))}</div>
                        </div>
                    </div>
                </div>
                <div class="portfolio-panel">
                    <div class="brief-label">Latest Trade</div>
                    <div class="portfolio-small-value">{html.escape(latest_trade["label"])}</div>
                    <div class="activity-detail">{html.escape(latest_trade["detail"])}</div>
                    <div class="brief-label" style="margin-top:8px;">Notification</div>
                    <div class="activity-detail">{html.escape(notification["label"])} | {html.escape(notification["detail"])}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("Latest Activity")
    runtime_event = runtime_details["latest_event"]
    activity_cols = responsive_columns(3)
    with activity_cols[0]:
        render_activity_item("Trade", f"{latest_trade['label']} | {latest_trade['detail']}")
    with activity_cols[1]:
        render_activity_item(
            "Cycle",
            investor_cycle_message(runtime_event, state),
        )
    with activity_cols[2]:
        render_activity_item(
            "Research",
            f"{research['label']} | {research['detail']}",
        )


def format_last_updated():
    now = pd.Timestamp.now(tz="Europe/London")
    timezone_label = now.tzname()
    return f"Today \u2022 {now:%H:%M} {timezone_label}"

    if not value:
        return "Unknown"

    try:
        dt = pd.to_datetime(value, utc=True).tz_convert("Europe/London")
        today = pd.Timestamp.now(tz="Europe/London")

        if dt.date() == today.date():
            return dt.strftime("Today • %H:%M BST")

        return dt.strftime("%d %b %Y • %H:%M BST")

    except Exception:
        return "Unknown"


def latest_trade_label():
    journal = load_csv("trade_journal_v3.csv")
    if journal.empty:
        return "None today"

    latest = journal.iloc[-1]
    action = latest.get("action", "TRADE")
    ticker = latest.get("ticker", "UNKNOWN")
    time_value = latest.get("time", "")
    if pd.isna(time_value):
        time_value = ""
    return f"{action} {ticker} {time_value}".strip()


def holdings_count_label():
    current_holdings = load_csv("holdings_report.csv")
    if current_holdings.empty:
        return "0"

    ticker_column = None
    for column in current_holdings.columns:
        if column.lower() == "ticker":
            ticker_column = column
            break

    if ticker_column is None:
        return str(len(current_holdings))

    tickers = current_holdings[ticker_column].astype(str).str.upper()
    return str(int((tickers != "CASH").sum()))


def open_positions_count(holdings_frame):
    if holdings_frame is None or holdings_frame.empty:
        return 0

    ticker_column = None
    for column in holdings_frame.columns:
        if column.lower() == "ticker":
            ticker_column = column
            break

    if ticker_column is None:
        return int(len(holdings_frame))

    tickers = holdings_frame[ticker_column].astype(str).str.upper()
    return int((tickers != "CASH").sum())


def render_holdings_exposure(holdings_frame, broker_row):
    st.subheader("Holdings & Exposure")

    if holdings_frame.empty:
        st.info("No open holdings.")
        return

    display_source = holdings_frame.copy()
    display_source.columns = [
        col.lower().replace(" ", "_")
        for col in display_source.columns
    ]

    portfolio_value = broker_row["portfolio_value"]

    display_source["portfolio_weight"] = (
        display_source["market_value"] / portfolio_value * 100
    ).round(2)

    cash_row = pd.DataFrame(
        [
            {
                "ticker": "CASH",
                "shares": 0,
                "entry_price": 0,
                "current_price": 0,
                "market_value": broker_row["cash"],
                "portfolio_weight": round(
                    broker_row["cash"] / broker_row["portfolio_value"] * 100,
                    2,
                ),
                "unrealised_pnl": 0,
            }
        ]
    )

    display_source = pd.concat(
        [display_source, cash_row],
        ignore_index=True,
    )

    display_source = display_source.sort_values(
        "market_value",
        ascending=False,
    )

    display_holdings = display_source[
        [
            "ticker",
            "shares",
            "entry_price",
            "current_price",
            "market_value",
            "portfolio_weight",
            "unrealised_pnl",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "shares": "Shares",
            "entry_price": "Entry Price",
            "current_price": "Current Price",
            "market_value": "Market Value",
            "portfolio_weight": "Weight %",
            "unrealised_pnl": "PnL",
        }
    )

    responsive_table(
        display_holdings.style.format(
            {
                "Shares": "{:.2f}",
                "Entry Price": "£{:,.2f}",
                "Current Price": "£{:,.2f}",
                "Market Value": "£{:,.2f}",
                "Weight %": "{:.2f}%",
                "PnL": "£{:,.2f}",
            }
        ),
        hide_index=True,
    )


def normalise_signals(signals_frame):
    if signals_frame is None or signals_frame.empty:
        return pd.DataFrame()

    display_source = signals_frame.copy()
    display_source.columns = [
        col.lower().replace(" ", "_")
        for col in display_source.columns
    ]

    required_signal_cols = [
        "date",
        "ticker",
        "signal",
        "weight",
        "status",
    ]

    for col in required_signal_cols:
        if col not in display_source.columns:
            display_source[col] = ""

    display_source["_action"] = display_source.apply(signal_action_label, axis=1)
    display_source["_weight_numeric"] = pd.to_numeric(
        display_source["weight"],
        errors="coerce",
    ).fillna(0)

    return display_source


def signal_action_label(row):
    status_text = str(row.get("status", "")).upper()
    signal_text = str(row.get("signal", "")).upper()

    if "SELL" in status_text or "AVOID" in status_text:
        return "SELL"
    if "BUY" in status_text:
        return "BUY"
    if "HOLD" in status_text:
        return "HOLD"

    try:
        signal_value = float(signal_text)
    except Exception:
        signal_value = None

    if signal_value is not None:
        if signal_value > 0:
            return "BUY"
        if signal_value < 0:
            return "SELL"
        return "HOLD"

    if "SELL" in signal_text:
        return "SELL"
    if "BUY" in signal_text:
        return "BUY"
    if "HOLD" in signal_text:
        return "HOLD"

    return "UNKNOWN"


def signal_badge(action):
    action = str(action or "UNKNOWN").upper()
    badge_class = {
        "BUY": "signal-buy",
        "HOLD": "signal-hold",
        "SELL": "signal-sell",
    }.get(action, "signal-neutral")
    return f'<span class="signal-badge {badge_class}">{html.escape(action)}</span>'


def render_opportunity_rows(display_source):
    priority = {
        "BUY": 0,
        "HOLD": 1,
        "SELL": 2,
        "UNKNOWN": 3,
    }
    ranked = display_source.copy()
    ranked["_priority"] = ranked["_action"].map(priority).fillna(3)
    ranked = ranked.sort_values(
        ["_priority", "_weight_numeric", "ticker"],
        ascending=[True, False, True],
    )

    rows = ranked[ranked["_action"].isin(["BUY", "HOLD"])].head(4)
    if rows.empty:
        st.caption("No active BUY or HOLD opportunities in the latest signal report.")
        return

    row_html = []
    for _, row in rows.iterrows():
        ticker = html.escape(str(row.get("ticker", "")).upper() or "UNKNOWN")
        status = html.escape(str(row.get("status", "")).strip() or "No status")
        weight = numeric_value(row.get("_weight_numeric", 0))
        row_html.append(
            (
                '<div class="signal-row">'
                "<div>"
                f'<div class="signal-ticker">{ticker}</div>'
                f"{signal_badge(row.get('_action'))}"
                "</div>"
                f'<div class="signal-detail">{status}</div>'
                f'<div class="signal-weight">{weight:.1%}</div>'
                "</div>"
            )
        )

    st.markdown(
        f'<div class="signal-panel">{"".join(row_html)}</div>',
        unsafe_allow_html=True,
    )


def render_signals_summary(signals_frame):
    st.subheader("Current Opportunities")

    display_source = normalise_signals(signals_frame)
    if display_source.empty:
        st.info("No signals available yet.")
        return

    action_values = display_source["_action"].astype(str).str.upper()
    buy_count = int((action_values == "BUY").sum())
    hold_count = int((action_values == "HOLD").sum())
    sell_count = int((action_values == "SELL").sum())
    top_rows = display_source[display_source["_action"].isin(["BUY", "HOLD"])].copy()
    if top_rows.empty:
        top_opportunity = "None"
    else:
        top_rows["_priority"] = top_rows["_action"].map({"BUY": 0, "HOLD": 1})
        top_rows = top_rows.sort_values(
            ["_priority", "_weight_numeric", "ticker"],
            ascending=[True, False, True],
        )
        top = top_rows.iloc[0]
        top_opportunity = f"{str(top.get('ticker', 'None')).upper()} {top['_action']}"

    c1, c2, c3, c4 = responsive_columns(4)
    with c1:
        metric_card("BUY", buy_count, buy_count > 0)
    with c2:
        metric_card("HOLD", hold_count)
    with c3:
        metric_card("SELL", sell_count)
    with c4:
        metric_card("Top Opportunity", top_opportunity, top_opportunity != "None")

    render_opportunity_rows(display_source)


def render_signal_tables(signals_frame):
    display_source = normalise_signals(signals_frame)
    if display_source.empty:
        st.info("No signal report available.")
        return

    display_signals = display_source[
        [
            "date",
            "ticker",
            "_action",
            "weight",
            "status",
        ]
    ].rename(
        columns={
            "date": "Date",
            "ticker": "Ticker",
            "_action": "Action",
            "weight": "Weight",
            "status": "Status",
        }
    )

    responsive_table(
        display_signals,
        hide_index=True,
    )

    with st.expander("Open raw signal report", expanded=False):
        responsive_table(
            signals_frame,
            hide_index=False,
        )


def runtime_status_label():
    status = load_runtime_status()
    return str(status.get("status") or "Unknown").title()


def runtime_freshness_label():
    status = load_runtime_status()
    return runtime_freshness(status)["label"]


def render_live_operational_cards():
    status_card(format_last_updated())

    cols = responsive_columns(4)
    with cols[0]:
        metric_card(
            "Data Freshness",
            runtime_freshness_label(),
            True,
        )
    with cols[1]:
        metric_card("Runtime Status", runtime_status_label(), True)
    with cols[2]:
        metric_card("Latest Paper Trade", latest_trade_label(), True)
    with cols[3]:
        metric_card("Current Holdings", holdings_count_label(), True)


def render_live_panel(live_mode):
    # Full-page auto-refresh is deliberately avoided because Streamlit reruns can
    # return the browser to the top of the page. Fragments refresh this small
    # operational panel every 60 seconds without rebuilding the whole dashboard.
    fragment = fragment_runner()
    if live_mode["enabled"] and fragment is not None:
        live_fragment = fragment(run_every="60s")(render_live_operational_cards)
        live_fragment()
        return

    render_live_operational_cards()


def render_scanner_table(frame, columns):
    if frame.empty:
        st.info("No scanner rows available.")
        return

    display_columns = [column for column in columns if column in frame.columns]
    if not display_columns:
        responsive_table(frame, hide_index=True)
        return

    responsive_table(frame[display_columns], hide_index=True)


def scanner_display_value(row, column, fallback="Unavailable"):
    if column not in row.index:
        return fallback

    value = row.get(column)
    if pd.isna(value):
        return fallback

    text = str(value).strip()
    return text if text else fallback


def scanner_number(row, column, fallback=None):
    if column not in row.index:
        return fallback

    try:
        value = float(row.get(column))
    except Exception:
        return fallback

    if pd.isna(value):
        return fallback

    return value


def scanner_yes(row, column):
    if column not in row.index:
        return False

    return str(row.get(column)).strip().lower() in {"1", "true", "yes", "y"}


def scanner_compact_number(value):
    if value is None or pd.isna(value):
        return "Unavailable"

    abs_value = abs(float(value))
    if abs_value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.1f}T"
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def scanner_quality_label(row):
    return "Pass" if scanner_yes(row, "data_quality_pass") else "Fail"


def scanner_region_class(region):
    key = str(region or "").strip().lower().replace(" ", "-")
    aliases = {
        "us": "us",
        "united-states": "us",
        "europe": "europe",
        "uk": "uk",
        "united-kingdom": "uk",
        "japan": "japan",
        "asia": "asia",
        "australia": "australia",
        "global": "global",
        "crypto": "crypto",
    }
    return f"scanner-region-{aliases.get(key, 'global')}"


def scanner_sector_label(sector):
    text = str(sector or "").strip()
    lower = text.lower()
    icon = ""

    if "technology" in lower:
        icon = "💻 "
    elif "financial" in lower or "bank" in lower:
        icon = "🏦 "
    elif "health" in lower:
        icon = "🏥 "
    elif "energy" in lower:
        icon = "⚡ "
    elif "industrial" in lower or "material" in lower:
        icon = "🏭 "
    elif "consumer" in lower:
        icon = "🛍 "
    elif "crypto" in lower:
        icon = "🪙 "

    return f"{icon}{text}" if text else "Unknown sector"


def scanner_bar_pct(value, max_value):
    if value is None or max_value <= 0:
        return 0

    pct = max(0.0, min(float(value) / max_value, 1.0))
    return int(round(pct * 100))


def scanner_rank_movement(row):
    if scanner_yes(row, "new_entry"):
        return "NEW", "scanner-move-new"

    change = scanner_number(row, "rank_change")
    if change is None:
        return "UNCHANGED", "scanner-move-flat"

    if change > 0:
        return f"▲ +{int(change)}", "scanner-move-up"
    if change < 0:
        return f"▼ {int(change)}", "scanner-move-down"

    return "UNCHANGED", "scanner-move-flat"


def scanner_research_summary(row):
    region = scanner_display_value(row, "region", "")
    sector = scanner_display_value(row, "sector", "")
    technical_score = scanner_number(row, "technical_score")
    liquidity = scanner_number(row, "avg_traded_value_60d")
    scanner_score = scanner_number(row, "scanner_score")

    strong_score = scanner_score is not None and scanner_score >= 140
    strong_technical = technical_score is not None and technical_score >= 4
    positive_technical = technical_score is not None and technical_score >= 3
    liquid = liquidity is not None and liquidity > 0

    if region and sector and strong_score:
        return f"High-ranking {region} candidate in the {sector} sector."
    if region and strong_technical:
        return f"Leading {region} opportunity with strong technical momentum."
    if region and positive_technical:
        return f"Leading {region} opportunity with a positive technical profile."
    if sector and liquid:
        return f"Ranks well with available liquidity data in the {sector} sector."
    if strong_score:
        return "Ranks highly due to scanner score and clean available data."

    return "Selected by the scanner from the validated research universe."


def scanner_rank_label(value):
    try:
        numeric = int(float(value))
    except Exception:
        return "?"
    return f"#{numeric}"


SCANNER_SCORE_COMPONENTS = [
    "freshness_component",
    "history_component",
    "missing_data_component",
    "volume_component",
    "technical_component",
    "liquidity_component",
]


def scanner_has_score_components(row):
    return all(column in row.index for column in SCANNER_SCORE_COMPONENTS)


def scanner_component_number(row, column):
    return scanner_number(row, column)


SCANNER_RISK_COLUMNS = [
    "volatility_20d",
    "volatility_60d",
    "atr_percent",
    "max_drawdown_1y",
    "trend_stability_score",
    "risk_level",
]


SCANNER_PERSISTENCE_COLUMNS = [
    "days_in_top_list",
    "consecutive_days_seen",
    "highest_rank_seen",
    "average_rank",
    "rank_volatility",
    "persistence_score",
    "persistence_level",
]


PORTFOLIO_FIT_COLUMNS = [
    "portfolio_fit",
    "portfolio_fit_score",
    "diversification_impact",
    "exposure_impact",
]


def scanner_has_risk_profile(row):
    return all(column in row.index for column in SCANNER_RISK_COLUMNS)


def scanner_has_persistence_profile(row):
    return all(column in row.index for column in SCANNER_PERSISTENCE_COLUMNS)


def scanner_has_portfolio_fit(row):
    return all(column in row.index for column in PORTFOLIO_FIT_COLUMNS)


def scanner_percent_label(value):
    numeric = scanner_number(pd.Series({"value": value}), "value")
    if numeric is None:
        return "Unavailable"
    return f"{numeric:.1f}%"


def scanner_risk_bullets(row):
    if not scanner_has_risk_profile(row):
        return []

    bullets = []
    stability = scanner_number(row, "trend_stability_score")
    volatility = scanner_number(row, "volatility_60d")
    drawdown = scanner_number(row, "max_drawdown_1y")
    atr_pct = scanner_number(row, "atr_percent")

    if stability is not None:
        if stability >= 80:
            bullets.append("Stable long-term trend")
        elif stability >= 60:
            bullets.append("Moderately stable trend")
        else:
            bullets.append("Caution: trend stability is weak")

    if volatility is not None:
        if volatility < 20:
            bullets.append("Low volatility profile")
        elif volatility < 45:
            bullets.append("Moderate volatility")
        else:
            bullets.append("High volatility")

    if drawdown is not None:
        if drawdown < 15:
            bullets.append("Limited historical drawdowns")
        elif drawdown < 35:
            bullets.append("Moderate historical drawdowns")
        else:
            bullets.append("Large historical drawdowns")

    if atr_pct is not None:
        if atr_pct < 2:
            bullets.append("Tight recent price ranges")
        elif atr_pct < 5:
            bullets.append("Normal recent price ranges")
        else:
            bullets.append("Expect wider price swings")

    return bullets


def scanner_integer_label(value):
    numeric = scanner_number(pd.Series({"value": value}), "value")
    if numeric is None:
        return "Unavailable"
    return f"{numeric:.0f}"


def scanner_decimal_label(value):
    numeric = scanner_number(pd.Series({"value": value}), "value")
    if numeric is None:
        return "Unavailable"
    return f"{numeric:.1f}"


def scanner_persistence_bullets(row):
    if not scanner_has_persistence_profile(row):
        return []

    bullets = []
    level = scanner_display_value(row, "persistence_level", "")
    score = scanner_number(row, "persistence_score")
    days = scanner_number(row, "days_in_top_list")
    consecutive = scanner_number(row, "consecutive_days_seen")
    volatility = scanner_number(row, "rank_volatility")

    if level == "New" or (days is not None and days <= 1):
        bullets.append("Recently entered the research shortlist")
    elif days is not None and days >= 10:
        bullets.append("Consistently ranked over multiple scans")

    if consecutive is not None and consecutive >= 7:
        bullets.append("Long-term research candidate")
    elif consecutive is not None and consecutive >= 3:
        bullets.append("Building consecutive shortlist history")

    if volatility is not None:
        if volatility <= 2:
            bullets.append("Stable ranking history")
        elif volatility >= 6:
            bullets.append("Rank fluctuates significantly")

    if score is not None and score >= 85:
        bullets.append("Core candidate by persistence profile")

    return bullets


def portfolio_fit_metadata():
    frames = []
    for path in sorted(SCANNER_UNIVERSE_DIR.glob("*.csv")):
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if "yahoo_ticker" in frame.columns:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    metadata = pd.concat(frames, ignore_index=True)
    metadata["yahoo_ticker"] = metadata["yahoo_ticker"].astype(str)
    return metadata.drop_duplicates("yahoo_ticker", keep="first")


def load_portfolio_fit_context(holdings_frame=None):
    holdings_frame = (
        load_csv("holdings_report.csv")
        if holdings_frame is None
        else holdings_frame.copy()
    )
    if holdings_frame.empty or "ticker" not in holdings_frame.columns:
        return None

    holdings = holdings_frame.copy()
    holdings["ticker"] = holdings["ticker"].astype(str)
    value_column = "market_value" if "market_value" in holdings.columns else None
    if value_column is None:
        return None

    holdings["_market_value"] = pd.to_numeric(
        holdings[value_column],
        errors="coerce",
    ).fillna(0.0)
    holdings = holdings[holdings["_market_value"] > 0].copy()
    if holdings.empty:
        return None

    metadata = portfolio_fit_metadata()
    if not metadata.empty:
        metadata_columns = [
            column
            for column in [
                "yahoo_ticker",
                "sector",
                "country",
                "region",
                "currency",
                "asset_class",
            ]
            if column in metadata.columns
        ]
        holdings = holdings.merge(
            metadata[metadata_columns],
            left_on="ticker",
            right_on="yahoo_ticker",
            how="left",
        )

    total_value = float(holdings["_market_value"].sum())
    if total_value <= 0:
        return None
    holdings["_weight"] = holdings["_market_value"] / total_value

    dimensions = ["sector", "country", "region", "currency", "asset_class"]
    exposure = {}
    for dimension in dimensions:
        if dimension not in holdings.columns:
            exposure[dimension] = pd.Series(dtype=float)
            continue
        values = holdings[dimension].fillna("").astype(str).str.strip()
        known = holdings.loc[values != ""].copy()
        if known.empty:
            exposure[dimension] = pd.Series(dtype=float)
            continue
        exposure[dimension] = known.groupby(dimension)["_weight"].sum()

    return {
        "holdings": holdings,
        "tickers": set(holdings["ticker"].astype(str)),
        "exposure": exposure,
        "total_value": total_value,
    }


def portfolio_fit_level(score):
    if score >= 4.5:
        return "Excellent"
    if score >= 3.5:
        return "Good"
    if score >= 2.5:
        return "Neutral"
    if score >= 1.5:
        return "Weak"
    return "Poor"


def portfolio_fit_stars(score):
    rounded = max(1, min(5, int(round(score))))
    return "★" * rounded


def portfolio_fit_dimension_label(dimension):
    labels = {
        "sector": "Sector",
        "country": "Country",
        "region": "Region",
        "currency": "Currency",
        "asset_class": "Asset class",
    }
    return labels.get(dimension, dimension.title())


def portfolio_fit_bullet_text(dimension, value, exposure_value):
    if dimension == "region":
        return f"Improves {value} exposure"
    if dimension == "currency":
        return f"Adds {value} diversification"
    if dimension == "sector":
        return f"Expands {value} exposure"
    if dimension == "asset_class":
        return "Broadens asset allocation"
    if dimension == "country":
        return f"Adds {value} country diversification"
    return f"Adds {value} diversification"


def portfolio_concentration_text(dimension, value):
    if dimension == "sector":
        return f"Increases {value} concentration"
    if dimension == "currency":
        return f"Adds another {value} holding"
    if dimension == "region":
        return f"Adds to existing {value} exposure"
    if dimension == "country":
        return f"Adds to existing {value} country exposure"
    if dimension == "asset_class":
        return f"Adds to existing {value} allocation"
    return f"Adds to existing {value} exposure"


def portfolio_fit_for_row(row, context):
    if context is None:
        return None

    ticker = scanner_display_value(row, "yahoo_ticker", "")
    score = 3.0
    positive = []
    cautions = []
    overlap = ticker in context["tickers"]
    if overlap:
        score -= 1.2
        cautions.append("Similar exposure to existing holdings")

    same_dimension_count = 0
    dominant_dimension_count = 0
    dimensions = ["sector", "country", "region", "currency", "asset_class"]
    for dimension in dimensions:
        value = scanner_display_value(row, dimension, "")
        if not value:
            continue
        exposure = context["exposure"].get(dimension, pd.Series(dtype=float))
        exposure_value = float(exposure.get(value, 0.0)) if not exposure.empty else 0.0

        if exposure_value <= 0:
            score += 0.35
            positive.append(portfolio_fit_bullet_text(dimension, value, exposure_value))
            continue

        same_dimension_count += 1
        if exposure_value >= 0.35:
            score -= 0.35
            dominant_dimension_count += 1
            cautions.append(portfolio_concentration_text(dimension, value))
        elif exposure_value <= 0.15:
            score += 0.10

    score = max(1.0, min(5.0, score))
    if overlap or dominant_dimension_count >= 3:
        diversification_impact = "Negative"
    elif len(positive) >= 2 and dominant_dimension_count == 0:
        diversification_impact = "Positive"
    else:
        diversification_impact = "Neutral"

    if overlap or dominant_dimension_count >= 3:
        exposure_impact = "High"
    elif same_dimension_count >= 3 or dominant_dimension_count >= 1:
        exposure_impact = "Moderate"
    else:
        exposure_impact = "Low"

    bullets = positive[:3] + cautions[:3]
    if not bullets and same_dimension_count:
        bullets.append("Similar exposure to existing holdings")

    level = portfolio_fit_level(score)
    return {
        "portfolio_fit": f"{portfolio_fit_stars(score)} {level}",
        "portfolio_fit_score": score,
        "portfolio_fit_level": level,
        "diversification_impact": diversification_impact,
        "exposure_impact": exposure_impact,
        "portfolio_fit_bullets": bullets,
    }


def apply_portfolio_fit(frame, context):
    if context is None or frame.empty:
        return frame

    enriched = frame.copy()
    results = [portfolio_fit_for_row(row, context) for _, row in enriched.iterrows()]
    if not any(results):
        return frame

    for column in [
        "portfolio_fit",
        "portfolio_fit_score",
        "portfolio_fit_level",
        "diversification_impact",
        "exposure_impact",
        "portfolio_fit_bullets",
    ]:
        enriched[column] = [
            result.get(column) if result else pd.NA
            for result in results
        ]
    return enriched


def scanner_portfolio_fit_bullets(row):
    if "portfolio_fit_bullets" not in row.index:
        return []

    bullets = row.get("portfolio_fit_bullets")
    if isinstance(bullets, list):
        return bullets
    return []


def scanner_risk_profile_html(row):
    if not scanner_has_risk_profile(row):
        return ""

    risk = html.escape(scanner_display_value(row, "risk_level", "Unavailable"))
    stability = scanner_number(row, "trend_stability_score")
    stability_label = (
        "Unavailable"
        if stability is None
        else f"{stability:.0f} / 100"
    )
    volatility = scanner_percent_label(row.get("volatility_20d"))
    drawdown = scanner_percent_label(row.get("max_drawdown_1y"))
    atr_pct = scanner_percent_label(row.get("atr_percent"))

    return f"""
        <div class="scanner-risk-profile">
            <div class="scanner-risk-title">Risk Profile</div>
            <div class="scanner-risk-grid">
                <div><span class="scanner-fact-label">Risk</span><br><span class="scanner-risk-value">{risk}</span></div>
                <div><span class="scanner-fact-label">Trend Stability</span><br><span class="scanner-risk-value">{html.escape(stability_label)}</span></div>
                <div><span class="scanner-fact-label">20d Volatility</span><br><span class="scanner-risk-value">{html.escape(volatility)}</span></div>
                <div><span class="scanner-fact-label">1Y Max Drawdown</span><br><span class="scanner-risk-value">{html.escape(drawdown)}</span></div>
                <div><span class="scanner-fact-label">ATR</span><br><span class="scanner-risk-value">{html.escape(atr_pct)}</span></div>
            </div>
        </div>
    """


def scanner_persistence_profile_html(row):
    if not scanner_has_persistence_profile(row):
        return ""

    level = html.escape(scanner_display_value(row, "persistence_level", "Unavailable"))
    score = scanner_number(row, "persistence_score")
    score_label = "Unavailable" if score is None else f"{score:.0f} / 100"
    days = scanner_integer_label(row.get("days_in_top_list"))
    highest_rank = scanner_integer_label(row.get("highest_rank_seen"))
    average_rank = scanner_decimal_label(row.get("average_rank"))

    return f"""
        <div class="scanner-risk-profile">
            <div class="scanner-risk-title">Persistence</div>
            <div class="scanner-risk-grid">
                <div><span class="scanner-fact-label">Level</span><br><span class="scanner-risk-value">{level}</span></div>
                <div><span class="scanner-fact-label">Score</span><br><span class="scanner-risk-value">{html.escape(score_label)}</span></div>
                <div><span class="scanner-fact-label">Days tracked</span><br><span class="scanner-risk-value">{html.escape(days)}</span></div>
                <div><span class="scanner-fact-label">Highest rank</span><br><span class="scanner-risk-value">{html.escape(highest_rank)}</span></div>
                <div><span class="scanner-fact-label">Average rank</span><br><span class="scanner-risk-value">{html.escape(average_rank)}</span></div>
            </div>
        </div>
    """


def scanner_portfolio_fit_html(row):
    if not scanner_has_portfolio_fit(row):
        return ""

    fit = html.escape(scanner_display_value(row, "portfolio_fit", "Unavailable"))
    diversification = html.escape(
        scanner_display_value(row, "diversification_impact", "Unavailable")
    )
    exposure = html.escape(
        scanner_display_value(row, "exposure_impact", "Unavailable")
    )

    return f"""
        <div class="scanner-risk-profile">
            <div class="scanner-risk-title">Portfolio Fit</div>
            <div class="scanner-risk-grid">
                <div><span class="scanner-fact-label">Fit</span><br><span class="scanner-risk-value">{fit}</span></div>
                <div><span class="scanner-fact-label">Diversification Impact</span><br><span class="scanner-risk-value">{diversification}</span></div>
                <div><span class="scanner-fact-label">Exposure Impact</span><br><span class="scanner-risk-value">{exposure}</span></div>
            </div>
        </div>
    """


def scanner_bullet_list_html(bullets):
    if not bullets:
        return ""

    items = "".join(
        '<div class="scanner-bullet-item">'
        f'<span class="scanner-bullet-text">{html.escape(str(bullet))}</span>'
        "</div>"
        for bullet in bullets
    )
    return f'<div class="scanner-bullet-list">{items}</div>'


def scanner_first_available_column(frame, columns):
    for column in columns:
        if column in frame.columns:
            return column
    return None


def scanner_compare_label(row):
    ticker = scanner_display_value(row, "yahoo_ticker", "")
    if not ticker:
        ticker = scanner_display_value(row, "ticker", "")
    if not ticker:
        ticker = scanner_display_value(row, "symbol", "Unknown")

    name = scanner_display_value(row, "name", "")
    if name and name != ticker:
        return f"{ticker} - {name}"
    return ticker


def scanner_metric_value(row, metric):
    column = metric["column"]
    if column not in row.index:
        return None

    if metric["kind"] == "text":
        value = scanner_display_value(row, column, "")
        return value or None

    return scanner_number(row, column)


def scanner_metric_display(value, metric):
    if value is None:
        return "Unavailable"

    kind = metric["kind"]
    if kind == "percent":
        return f"{float(value):.1f}%"
    if kind == "score":
        return f"{float(value):.1f}"
    if kind == "stability":
        return f"{float(value):.0f} / 100"
    if kind == "liquidity":
        return f"{scanner_compact_number(value)} - {scanner_liquidity_label(value)}"
    return str(value)


def scanner_liquidity_label(value):
    try:
        numeric = float(value)
    except Exception:
        return "Unavailable"

    if pd.isna(numeric) or numeric <= 0:
        return "Unavailable"
    if numeric >= 1_000_000_000:
        return "Excellent"
    if numeric >= 100_000_000:
        return "Good"
    if numeric >= 10_000_000:
        return "Moderate"
    return "Limited"


def scanner_risk_rank(value):
    order = {
        "Very Low": 1,
        "Low": 2,
        "Medium": 3,
        "High": 4,
        "Very High": 5,
    }
    return order.get(str(value).strip(), None)


def scanner_compare_indicator(value, metric, values):
    if value is None or metric.get("compare") == "none":
        return ""

    valid_values = [v for v in values if v is not None]
    if len(valid_values) < 2:
        return ""

    compare = metric.get("compare")
    css = "scanner-compare-high"
    text = "&#9650; Higher"

    if compare == "higher":
        if value == max(valid_values):
            css = "scanner-compare-strong"
            text = "&#10003; Strong"
        elif value == min(valid_values):
            css = "scanner-compare-low"
            text = "&#9660; Lower"
    elif compare == "lower":
        if value == min(valid_values):
            css = "scanner-compare-strong"
            text = "&#10003; Strong"
        elif value == max(valid_values):
            css = "scanner-compare-elevated"
            text = "&#9888; Elevated"
        else:
            css = "scanner-compare-low"
            text = "&#9660; Lower"
    elif compare == "risk":
        ranked_values = [
            scanner_risk_rank(v)
            for v in valid_values
            if scanner_risk_rank(v) is not None
        ]
        rank = scanner_risk_rank(value)
        if rank is None or len(ranked_values) < 2:
            return ""
        if rank == min(ranked_values):
            css = "scanner-compare-strong"
            text = "&#10003; Strong"
        elif rank == max(ranked_values):
            css = "scanner-compare-elevated"
            text = "&#9888; Elevated"
        else:
            css = "scanner-compare-low"
            text = "&#9660; Lower"

    return f'<div class="scanner-compare-indicator {css}">{text}</div>'


def scanner_comparison_metrics(frame):
    confidence_column = scanner_first_available_column(
        frame,
        ["confidence", "confidence_score", "scanner_confidence"],
    )
    metrics = [
        {
            "label": "Opportunity Score",
            "column": "scanner_score",
            "kind": "score",
            "compare": "higher",
        },
        {
            "label": "Portfolio Fit",
            "column": "portfolio_fit",
            "kind": "text",
            "compare": "none",
        },
        {
            "label": "Diversification Impact",
            "column": "diversification_impact",
            "kind": "text",
            "compare": "none",
        },
        {
            "label": "Exposure Impact",
            "column": "exposure_impact",
            "kind": "text",
            "compare": "none",
        },
        {
            "label": "Persistence Level",
            "column": "persistence_level",
            "kind": "text",
            "compare": "none",
        },
        {
            "label": "Persistence Score",
            "column": "persistence_score",
            "kind": "stability",
            "compare": "higher",
        },
        {
            "label": "Risk Level",
            "column": "risk_level",
            "kind": "text",
            "compare": "risk",
        },
        {
            "label": "Trend Stability",
            "column": "trend_stability_score",
            "kind": "stability",
            "compare": "higher",
        },
        {
            "label": "20d Volatility",
            "column": "volatility_20d",
            "kind": "percent",
            "compare": "lower",
        },
        {
            "label": "60d Volatility",
            "column": "volatility_60d",
            "kind": "percent",
            "compare": "lower",
        },
        {
            "label": "ATR %",
            "column": "atr_percent",
            "kind": "percent",
            "compare": "lower",
        },
        {
            "label": "1Y Max Drawdown",
            "column": "max_drawdown_1y",
            "kind": "percent",
            "compare": "lower",
        },
        {
            "label": "Liquidity",
            "column": "avg_traded_value_60d",
            "kind": "liquidity",
            "compare": "higher",
        },
        {
            "label": "Technical Score",
            "column": "technical_score",
            "kind": "score",
            "compare": "higher",
        },
        {"label": "Region", "column": "region", "kind": "text", "compare": "none"},
        {"label": "Country", "column": "country", "kind": "text", "compare": "none"},
        {"label": "Sector", "column": "sector", "kind": "text", "compare": "none"},
        {"label": "Currency", "column": "currency", "kind": "text", "compare": "none"},
    ]

    if confidence_column:
        metrics.insert(
            1,
            {
                "label": "Confidence",
                "column": confidence_column,
                "kind": "score",
                "compare": "higher",
            },
        )

    return [
        metric
        for metric in metrics
        if metric["column"] in frame.columns
    ]


def scanner_metric_leader(frame, column, mode="max"):
    if column not in frame.columns:
        return None, None

    values = pd.to_numeric(frame[column], errors="coerce")
    if values.dropna().empty:
        return None, None

    idx = values.idxmax() if mode == "max" else values.idxmin()
    return frame.loc[idx], float(values.loc[idx])


def scanner_distinct_values(frame, column):
    if column not in frame.columns:
        return pd.Series(dtype=str)

    values = frame[column].fillna("").astype(str).str.strip()
    return values[values != ""]


def scanner_comparison_summary(frame):
    observations = []
    if frame.empty:
        return observations

    score_leader, _ = scanner_metric_leader(frame, "scanner_score")
    if score_leader is not None:
        scores = pd.to_numeric(frame["scanner_score"], errors="coerce").dropna()
        if len(scores) >= 2:
            sorted_scores = scores.sort_values(ascending=False)
            gap = sorted_scores.iloc[0] - sorted_scores.iloc[1]
            leader = frame.loc[sorted_scores.index[0]]
            runner_up = frame.loc[sorted_scores.index[1]]
            if gap > 0:
                observations.append(
                    f"{scanner_compare_label(leader)} leads the comparison by scanner score, ahead of {scanner_compare_label(runner_up)} by {gap:.1f} points."
                )
            else:
                observations.append(
                    f"{scanner_compare_label(leader)} and {scanner_compare_label(runner_up)} are closely matched on scanner score."
                )
        else:
            observations.append(
                f"{scanner_compare_label(score_leader)} has the strongest scanner score in this comparison."
            )

    technical_leader, _ = scanner_metric_leader(frame, "technical_score")
    stable_leader, _ = scanner_metric_leader(frame, "trend_stability_score")
    drawdown_leader, _ = scanner_metric_leader(frame, "max_drawdown_1y", mode="min")
    volatility_leader, _ = scanner_metric_leader(frame, "volatility_60d", mode="min")
    risk_leaders = [
        ("trend stability", stable_leader),
        ("drawdown", drawdown_leader),
        ("volatility", volatility_leader),
    ]
    risk_by_asset = {}
    for metric_label, row in risk_leaders:
        if row is None:
            continue
        asset_label = scanner_compare_label(row)
        risk_by_asset.setdefault(asset_label, []).append(metric_label)

    if risk_by_asset:
        asset_label, metric_labels = max(
            risk_by_asset.items(),
            key=lambda item: len(item[1]),
        )
        if len(metric_labels) >= 2:
            observations.append(
                f"{asset_label} has the strongest risk/stability profile across {', '.join(metric_labels)}."
            )
        else:
            risk_notes = []
            if stable_leader is not None:
                risk_notes.append(
                    f"{scanner_compare_label(stable_leader)} has the steadier trend"
                )
            if drawdown_leader is not None:
                risk_notes.append(
                    f"{scanner_compare_label(drawdown_leader)} shows the lowest drawdown"
                )
            if volatility_leader is not None:
                risk_notes.append(
                    f"{scanner_compare_label(volatility_leader)} has the lower 60d volatility"
                )
            observations.append(
                "Risk and stability balance: " + "; ".join(risk_notes[:3]) + "."
            )

    persistence_leader, _ = scanner_metric_leader(frame, "persistence_score")
    if persistence_leader is not None:
        observations.append(
            f"{scanner_compare_label(persistence_leader)} has the strongest persistence profile across recent scanner history."
        )

    liquidity_leader, _ = scanner_metric_leader(frame, "avg_traded_value_60d")
    if liquidity_leader is not None or technical_leader is not None:
        parts = []
        if technical_leader is not None:
            parts.append(
                f"{scanner_compare_label(technical_leader)} has the strongest momentum signal"
            )
        if liquidity_leader is not None:
            liquidity = scanner_metric_display(
                scanner_number(liquidity_leader, "avg_traded_value_60d"),
                {"kind": "liquidity"},
            )
            parts.append(
                f"{scanner_compare_label(liquidity_leader)} has the highest liquidity proxy ({liquidity})"
            )
        observations.append(
            "Momentum and liquidity: " + "; ".join(parts) + "."
        )

    exposure_notes = []
    for column, label, plural in [
        ("sector", "sector", "sectors"),
        ("currency", "currency", "currencies"),
        ("region", "region", "regions"),
    ]:
        values = scanner_distinct_values(frame, column)
        if values.empty:
            continue
        distinct_count = values.nunique()
        if distinct_count == 1 and len(values) > 1:
            exposure_notes.append(f"same {label} ({values.iloc[0]})")
        elif distinct_count > 1:
            repeated = values.value_counts()
            repeated = repeated[repeated > 1]
            if not repeated.empty:
                shared_value = repeated.index[0]
                shared_rows = frame.loc[values[values == shared_value].index]
                shared_labels = [
                    scanner_compare_label(row)
                    for _, row in shared_rows.iterrows()
                ]
                exposure_notes.append(
                    f"{' and '.join(shared_labels)} share {label} exposure ({shared_value})"
                )
            exposure_notes.append(f"{distinct_count} {plural}")

    if exposure_notes:
        observations.append(
            "Exposure mix: " + "; ".join(exposure_notes[:4]) + "."
        )

    return observations[:5]


def scanner_comparison_html(frame):
    metrics = scanner_comparison_metrics(frame)
    if not metrics:
        return ""

    header_cells = [
        '<div class="scanner-compare-cell scanner-compare-head">Metric</div>'
    ]
    for _, row in frame.iterrows():
        header_cells.append(
            '<div class="scanner-compare-cell scanner-compare-head">'
            f"{html.escape(scanner_compare_label(row))}"
            "</div>"
        )

    rows = [
        f'<div class="scanner-compare-row">{"".join(header_cells)}</div>'
    ]

    for metric in metrics:
        values = [scanner_metric_value(row, metric) for _, row in frame.iterrows()]
        cells = [
            '<div class="scanner-compare-cell scanner-compare-label">'
            f"{html.escape(metric['label'])}"
            "</div>"
        ]
        for value in values:
            display = html.escape(scanner_metric_display(value, metric))
            indicator = scanner_compare_indicator(value, metric, values)
            cells.append(
                '<div class="scanner-compare-cell">'
                f'<div class="scanner-compare-value">{display}</div>'
                f"{indicator}"
                "</div>"
            )
        rows.append(f'<div class="scanner-compare-row">{"".join(cells)}</div>')

    return (
        f'<div class="scanner-compare-wrap">'
        f'<div class="scanner-compare-table" style="--compare-cols:{len(frame)};">'
        f'{"".join(rows)}'
        "</div></div>"
    )


def render_opportunity_comparison(selected):
    st.subheader("Opportunity Comparison")
    st.caption("Research-only comparison of selected scanner opportunities.")

    if selected.empty:
        st.info("No selected scanner opportunities are available to compare.")
        return

    if len(selected) < 2:
        st.info("At least two scanner opportunities are needed for comparison.")
        return

    labels = []
    used = set()
    for index, row in selected.iterrows():
        label = scanner_compare_label(row)
        if label in used:
            label = f"{label} ({index})"
        used.add(label)
        labels.append(label)

    label_to_index = dict(zip(labels, selected.index))
    default_labels = labels[: min(2, len(labels))]
    chosen_labels = st.multiselect(
        "Compare opportunities",
        labels,
        default=default_labels,
        max_selections=4,
        help="Select 2 to 4 research candidates for side-by-side comparison.",
    )

    if len(chosen_labels) < 2:
        st.info("Select at least two opportunities to compare.")
        return

    comparison = selected.loc[
        [label_to_index[label] for label in chosen_labels]
    ].copy()

    summary = scanner_comparison_summary(comparison)
    if summary:
        st.markdown("**Research Summary**")
        st.markdown(
            "<ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in summary)
            + "</ul>",
            unsafe_allow_html=True,
        )

    table_html = scanner_comparison_html(comparison)
    if table_html:
        st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.info("No comparable scanner fields are available in this output.")


def scanner_change_cards(selected, history):
    if len(history) < 2 or selected.empty:
        return None

    previous_selected = scanner_selected_rows(history[-2]["frame"])
    if previous_selected.empty:
        return None

    current = selected.copy()
    if "rank_change" not in current.columns:
        return None

    current["rank_change_numeric"] = pd.to_numeric(
        current["rank_change"],
        errors="coerce",
    )
    current_new = scanner_bool_series(current, "new_entry")
    previous_tickers = set(previous_selected["yahoo_ticker"].astype(str))
    current_tickers = set(current["yahoo_ticker"].astype(str))
    dropped = previous_selected[
        ~previous_selected["yahoo_ticker"].astype(str).isin(current_tickers)
    ].copy()

    risers = current[current["rank_change_numeric"] > 0].sort_values(
        "rank_change_numeric",
        ascending=False,
    )
    fallers = current[current["rank_change_numeric"] < 0].sort_values(
        "rank_change_numeric",
        ascending=True,
    )
    new_entries = current[current_new].copy()

    cards = []
    if not risers.empty:
        row = risers.iloc[0]
        cards.append(
            {
                "label": "▲ Biggest Risers",
                "main": scanner_display_value(row, "yahoo_ticker", "Unknown"),
                "detail": (
                    f"{scanner_rank_label(row.get('previous_rank'))} → "
                    f"{scanner_rank_label(row.get('current_rank'))} | "
                    f"▲ +{int(row['rank_change_numeric'])}"
                ),
            }
        )
    else:
        cards.append(
            {
                "label": "▲ Biggest Risers",
                "main": "None",
                "detail": "No selected candidates improved rank.",
            }
        )

    if not fallers.empty:
        row = fallers.iloc[0]
        cards.append(
            {
                "label": "▼ Biggest Fallers",
                "main": scanner_display_value(row, "yahoo_ticker", "Unknown"),
                "detail": (
                    f"{scanner_rank_label(row.get('previous_rank'))} → "
                    f"{scanner_rank_label(row.get('current_rank'))} | "
                    f"▼ {int(row['rank_change_numeric'])}"
                ),
            }
        )
    else:
        cards.append(
            {
                "label": "▼ Biggest Fallers",
                "main": "None",
                "detail": "No selected candidates declined rank.",
            }
        )

    if not new_entries.empty:
        row = new_entries.iloc[0]
        cards.append(
            {
                "label": "New Opportunities",
                "main": scanner_display_value(row, "yahoo_ticker", "Unknown"),
                "detail": f"NEW | Entered Top {len(current)}",
            }
        )
    else:
        cards.append(
            {
                "label": "New Opportunities",
                "main": "None",
                "detail": "No new selected candidates.",
            }
        )

    if not dropped.empty:
        row = dropped.iloc[0]
        cards.append(
            {
                "label": "Dropped Out",
                "main": scanner_display_value(row, "yahoo_ticker", "Unknown"),
                "detail": f"{scanner_rank_label(row.get('rank'))} → OUT",
            }
        )
    else:
        cards.append(
            {
                "label": "Dropped Out",
                "main": "None",
                "detail": "No previous selected candidates dropped out.",
            }
        )

    return cards


def scanner_summary_bullets(validated, selected, history):
    bullets = [
        f"{len(validated)} companies scanned",
        f"{len(selected)} selected",
    ]

    if len(history) >= 2 and not selected.empty:
        new_entries = int(scanner_bool_series(selected, "new_entry").sum())
        previous_selected = scanner_selected_rows(history[-2]["frame"])
        dropped_count = 0
        if not previous_selected.empty and "yahoo_ticker" in previous_selected.columns:
            current_tickers = set(selected["yahoo_ticker"].astype(str))
            dropped_count = int(
                (~previous_selected["yahoo_ticker"].astype(str).isin(current_tickers)).sum()
            )
        bullets.append(f"{new_entries} new opportunities entered the Top {len(selected)}")
        bullets.append(f"{dropped_count} candidates dropped out")

    if not selected.empty and "sector" in selected.columns:
        sectors = selected["sector"].dropna().astype(str)
        if not sectors.empty:
            bullets.append(
                f"{sectors.value_counts().idxmax()} is the strongest represented sector"
            )

    if len(history) >= 2 and "region" in selected.columns:
        previous_selected = scanner_selected_rows(history[-2]["frame"])
        if "region" in previous_selected.columns:
            current_counts = selected["region"].dropna().astype(str).value_counts()
            previous_counts = previous_selected["region"].dropna().astype(str).value_counts()
            deltas = current_counts.subtract(previous_counts, fill_value=0)
            positive = deltas[deltas > 0]
            if not positive.empty:
                bullets.append(
                    f"{positive.idxmax()} gained the most high-ranking candidates"
                )

    return bullets


def scanner_history_table(history):
    rows = []
    for index, snapshot in enumerate(history):
        frame = snapshot["frame"]
        selected = scanner_selected_rows(frame)
        previous_selected = (
            scanner_selected_rows(history[index - 1]["frame"])
            if index > 0
            else pd.DataFrame()
        )

        top_candidate = (
            scanner_display_value(selected.iloc[0], "yahoo_ticker", "None")
            if not selected.empty
            else "None"
        )
        new_entries = 0
        largest_rise = ""
        largest_fall = ""

        if index > 0 and not selected.empty:
            previous_ranks = (
                previous_selected.set_index("yahoo_ticker")["rank"].to_dict()
                if not previous_selected.empty
                else {}
            )
            current = selected.copy()
            previous_values = current["yahoo_ticker"].map(previous_ranks)
            rank_change = previous_values - current["rank"]
            new_entries = int(previous_values.isna().sum())

            if rank_change.notna().any():
                max_change = rank_change.max()
                min_change = rank_change.min()
                if pd.notna(max_change) and max_change > 0:
                    row = current.loc[rank_change.idxmax()]
                    largest_rise = (
                        f"{row['yahoo_ticker']} ▲ +{int(max_change)}"
                    )
                if pd.notna(min_change) and min_change < 0:
                    row = current.loc[rank_change.idxmin()]
                    largest_fall = (
                        f"{row['yahoo_ticker']} ▼ {int(min_change)}"
                    )

        rows.append(
            {
                "timestamp": snapshot["timestamp"],
                "sort_timestamp": snapshot.get("sort_timestamp"),
                "top candidate": top_candidate,
                "number selected": len(selected),
                "new entries": new_entries,
                "largest rise": largest_rise,
                "largest fall": largest_fall,
            }
        )

    columns = [
        "timestamp",
        "top candidate",
        "number selected",
        "new entries",
        "largest rise",
        "largest fall",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)

    table = pd.DataFrame(rows).sort_values("sort_timestamp", ascending=False)
    return table.drop(columns=["sort_timestamp"], errors="ignore")[columns]


def render_scanner_research_overview(validated, selected, history):
    st.divider()
    st.subheader("Research Overview")

    st.markdown("**Today's Scanner Summary**")
    for bullet in scanner_summary_bullets(validated, selected, history):
        st.markdown(f"- {bullet}")

    if len(history) < 2:
        st.info("Historical comparisons will appear after the next scanner run.")
    else:
        cards = scanner_change_cards(selected, history)
        if cards:
            card_html = []
            for card in cards:
                card_html.append(
                    (
                        '<div class="scanner-change-card">'
                        f'<div class="scanner-change-label">{html.escape(card["label"])}</div>'
                        f'<div class="scanner-change-main">{html.escape(card["main"])}</div>'
                        f'<div class="scanner-change-detail">{html.escape(card["detail"])}</div>'
                        "</div>"
                    )
                )
            st.markdown(
                f'<div class="scanner-change-grid">{"".join(card_html)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("No rank changes are available for the latest scanner run.")


def render_scanner_history_section(history):
    with st.expander("Scanner History", expanded=False):
        table = scanner_history_table(history)
        if table.empty:
            st.info("No scanner history snapshots found.")
        else:
            responsive_table(table, hide_index=True)


def scanner_health_status(state, failed):
    if state.get("missing"):
        return "Error", False
    if state.get("stale") or not failed.empty:
        return "Warning", False
    return "Healthy", True


def render_scanner_status_mission_control(validated, selected, failed, state):
    st.subheader("Scanner Status")
    st.info(
        "Research only: scanner refreshes update local research outputs and do not place or modify trades."
    )

    health_label, health_ok = scanner_health_status(state, failed)
    cols = responsive_columns(5)
    with cols[0]:
        metric_card("Scanner Health", health_label, health_ok)
    with cols[1]:
        metric_card(
            "Last Scan",
            scanner_file_modified_label("latest_rankings.csv"),
            state.get("fresh"),
        )
    with cols[2]:
        metric_card("Universe Size", len(validated))
    with cols[3]:
        metric_card("Selected Candidates", len(selected), len(selected) > 0)
    with cols[4]:
        metric_card("Failed Tickers", len(failed), len(failed) == 0)

    refresh_clicked = st.button("Refresh Scanner Now", type="primary")
    return refresh_clicked


def scanner_why_selected(row):
    bullets = []

    if scanner_has_score_components(row):
        freshness = scanner_component_number(row, "freshness_component")
        history = scanner_component_number(row, "history_component")
        missing_data = scanner_component_number(row, "missing_data_component")
        volume = scanner_component_number(row, "volume_component")
        technical = scanner_component_number(row, "technical_component")
        liquidity = scanner_component_number(row, "liquidity_component")

        if freshness is not None:
            if freshness >= 40:
                bullets.append("Data current")
            elif freshness >= 20:
                bullets.append("Caution: price freshness is mixed")
            else:
                bullets.append("Caution: price data may be stale or unavailable")

        if history is not None:
            if history >= 18:
                bullets.append("Strong history coverage")
            elif history >= 10:
                bullets.append("Moderate history coverage")
            else:
                bullets.append("Caution: limited price history")

        if missing_data is not None:
            if missing_data >= 18:
                bullets.append("Missing data low")
            elif missing_data >= 15:
                bullets.append("Some missing data in history")
            else:
                bullets.append("Caution: elevated missing data")

        technical_score = scanner_number(row, "technical_score")
        if technical is not None:
            technical_label = (
                "unavailable"
                if technical_score is None
                else f"{technical_score:.1f}/5"
            )
            if technical >= 40:
                bullets.append(f"Strong technical score ({technical_label})")
            elif technical >= 30:
                bullets.append(f"Positive technical score ({technical_label})")
            else:
                bullets.append(f"Caution: technical score is modest ({technical_label})")

        if liquidity is not None:
            if liquidity >= 16:
                bullets.append("Liquidity component healthy")
            elif liquidity >= 8:
                bullets.append("Liquidity component moderate")
            else:
                bullets.append("Caution: liquidity component is weak")

        if volume is not None:
            if volume >= 10:
                bullets.append("Recent volume data present")
            else:
                bullets.append("Caution: recent volume data is weak")

        bullets.extend(scanner_portfolio_fit_bullets(row))
        bullets.extend(scanner_persistence_bullets(row))
        bullets.extend(scanner_risk_bullets(row))
        return bullets

    scanner_score = scanner_number(row, "scanner_score")
    if scanner_score is not None:
        if scanner_score >= 140:
            bullets.append("One of the highest-ranked opportunities in this scan")
        else:
            bullets.append("Ranked by scanner score")

    technical_score = scanner_number(row, "technical_score")
    if technical_score is not None:
        if technical_score >= 4:
            bullets.append("Strong technical momentum")
        elif technical_score >= 3:
            bullets.append("Positive technical profile")

    liquidity = scanner_number(row, "avg_traded_value_60d")
    if liquidity is not None and liquidity > 0:
        bullets.append("High trading liquidity proxy available")

    if scanner_yes(row, "latest_close_present") and not scanner_yes(
        row,
        "stale_latest_price",
    ):
        bullets.append("Clean recent price data")

    region = scanner_display_value(row, "region", "")
    if region:
        bullets.append(f"Leading opportunity from {region}")

    sector = scanner_display_value(row, "sector", "")
    if sector:
        bullets.append(f"Strong candidate within the {sector} sector")

    bullets.extend(scanner_portfolio_fit_bullets(row))
    bullets.extend(scanner_persistence_bullets(row))
    bullets.extend(scanner_risk_bullets(row))
    return bullets[:5]


def render_opportunity_intelligence(selected):
    st.subheader("Opportunity Intelligence")
    st.caption(
        "Research-only explanations based on scanner output fields. These cards "
        "do not place or modify trades."
    )

    if selected.empty:
        st.info("No selected candidates available for opportunity intelligence.")
        return

    cards = selected.copy()
    if "rank" in cards.columns:
        cards = cards.sort_values("rank", ascending=True)
    cards = cards.head(5)
    liquidity_max = (
        pd.to_numeric(
            cards.get("avg_traded_value_60d", pd.Series(dtype=float)),
            errors="coerce",
        )
        .dropna()
        .max()
    )
    if pd.isna(liquidity_max):
        liquidity_max = 0

    columns = responsive_columns(min(3, max(1, len(cards))))
    for index, (_, row) in enumerate(cards.iterrows()):
        rank = scanner_display_value(row, "rank", "?")
        movement_label, movement_class = scanner_rank_movement(row)
        ticker = html.escape(scanner_display_value(row, "yahoo_ticker", "UNKNOWN"))
        name = html.escape(scanner_display_value(row, "name", "Unnamed candidate"))
        region_raw = scanner_display_value(row, "region", "Unknown region")
        sector_raw = scanner_display_value(row, "sector", "Unknown sector")
        region = html.escape(region_raw)
        sector = html.escape(scanner_sector_label(sector_raw))
        region_class = scanner_region_class(region_raw)
        quality = scanner_quality_label(row)
        quality_class = (
            "scanner-quality-pass"
            if quality == "Pass"
            else "scanner-quality-fail"
        )
        score = scanner_number(row, "scanner_score")
        score_label = "Unavailable" if score is None else f"{score:.1f}"
        close = scanner_number(row, "latest_close")
        close_label = "Unavailable" if close is None else f"{close:,.2f}"
        liquidity = scanner_number(row, "avg_traded_value_60d")
        liquidity_label = scanner_compact_number(liquidity)
        technical_score = scanner_number(row, "technical_score")
        technical_label = (
            "Unavailable"
            if technical_score is None
            else f"{technical_score:.1f}"
        )
        bullets = scanner_why_selected(row)
        bullet_html = scanner_bullet_list_html(bullets)
        portfolio_fit_html = scanner_portfolio_fit_html(row)
        persistence_profile_html = scanner_persistence_profile_html(row)
        risk_profile_html = scanner_risk_profile_html(row)
        summary = html.escape(scanner_research_summary(row))
        scanner_pct = scanner_bar_pct(score, 150)
        technical_pct = scanner_bar_pct(technical_score, 5)
        liquidity_pct = scanner_bar_pct(liquidity, liquidity_max)

        card_html = f"""
            <div class="scanner-card">
                <div class="scanner-card-head">
                    <div>
                        <div class="scanner-rank">Rank {html.escape(str(rank))}</div>
                        <div class="scanner-ticker">{ticker}</div>
                        <div class="scanner-name">{name}</div>
                        <span class="scanner-move {movement_class}">{html.escape(movement_label)}</span>
                    </div>
                    <div class="scanner-score">
                        <div>{html.escape(score_label)}</div>
                        <div class="scanner-score-label">scanner score</div>
                    </div>
                </div>
                <div class="scanner-badges">
                    <span class="scanner-badge {region_class}">{region}</span>
                    <span class="scanner-badge">{sector}</span>
                    <span class="scanner-badge {quality_class}">Data Quality: {quality}</span>
                </div>
                <div class="scanner-summary">{summary}</div>
                <div class="scanner-bars">
                    <div class="scanner-bar-row">
                        <span>Scanner</span>
                        <span class="scanner-bar-track"><span class="scanner-bar-fill" style="width:{scanner_pct}%"></span></span>
                        <span>{html.escape(score_label)}</span>
                    </div>
                    <div class="scanner-bar-row">
                        <span>Technical</span>
                        <span class="scanner-bar-track"><span class="scanner-bar-fill" style="width:{technical_pct}%"></span></span>
                        <span>{html.escape(technical_label)}</span>
                    </div>
                    <div class="scanner-bar-row">
                        <span>Liquidity</span>
                        <span class="scanner-bar-track"><span class="scanner-bar-fill" style="width:{liquidity_pct}%"></span></span>
                        <span>{html.escape(liquidity_label)}</span>
                    </div>
                </div>
                <div class="scanner-facts">
                    <div><span class="scanner-fact-label">Latest close</span><br>{html.escape(close_label)}</div>
                    <div><span class="scanner-fact-label">Liquidity proxy</span><br>{html.escape(liquidity_label)}</div>
                </div>
                {portfolio_fit_html}
                {persistence_profile_html}
                {risk_profile_html}
                {bullet_html}
            </div>
        """

        with columns[index % len(columns)]:
            st.html(card_html)


def render_global_scanner_page():
    st.subheader("Global Scanner")
    render_scanner_auto_refresh_status(show_messages=False)

    validated = load_scanner_csv("universe_validated.csv")
    rankings = load_scanner_csv("latest_rankings.csv")
    selected = load_scanner_csv("selected_candidates.csv")
    history = load_scanner_history()
    portfolio_fit_context = load_portfolio_fit_context()
    selected_for_display = apply_portfolio_fit(selected, portfolio_fit_context)

    if validated.empty and rankings.empty and selected.empty:
        st.warning("No scanner outputs found yet.")
        st.caption(
            "Use the Refresh Scanner Now button above to generate local "
            "research outputs for this dashboard session."
        )
        return

    validated_pass = scanner_bool_series(validated, "data_quality_pass")
    selected_flag = scanner_bool_series(rankings, "selected_for_research")
    failed = (
        validated.loc[~validated_pass].copy()
        if not validated.empty and len(validated_pass) == len(validated)
        else pd.DataFrame()
    )

    refresh_clicked = render_scanner_status_mission_control(
        validated,
        selected,
        failed,
        scanner_output_state(),
    )
    if refresh_clicked:
        with st.spinner("Running research scanner..."):
            try:
                result = run_research_scanner_from_dashboard()
                st.success(
                    "Scanner refreshed: "
                    f"{result.get('validated_rows', 0)} validated, "
                    f"{result.get('selected_rows', 0)} selected, "
                    f"{result.get('quality_failures', 0)} failed."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Scanner failed: {exc}")

    render_scanner_research_overview(validated, selected, history)

    st.divider()
    st.subheader("Research Analysis")
    render_opportunity_intelligence(selected_for_display)
    render_opportunity_comparison(selected_for_display)

    st.divider()
    st.subheader("Region Breakdown")
    if "region" in validated.columns:
        region_breakdown = (
            validated.assign(_valid=validated_pass)
            .groupby("region", dropna=False)
            .agg(
                tickers=("yahoo_ticker", "count"),
                validated=("_valid", "sum"),
            )
            .reset_index()
            .sort_values("tickers", ascending=False)
        )
        responsive_table(region_breakdown, hide_index=True)
    else:
        st.info("No region column available in scanner output.")

    if "sector" in validated.columns:
        st.subheader("Sector Breakdown")
        sector_breakdown = (
            validated.groupby("sector", dropna=False)
            .size()
            .reset_index(name="tickers")
            .sort_values("tickers", ascending=False)
        )
        responsive_table(sector_breakdown, hide_index=True)

    render_scanner_history_section(history)

    with st.expander("Scanner Output Tables", expanded=False):
        st.subheader("Top Ranked Opportunities")
        if not rankings.empty and len(selected_flag) == len(rankings):
            ranked_display = rankings.copy()
            ranked_display["selected"] = selected_flag.map(
                {True: "Selected", False: ""}
            )
        else:
            ranked_display = rankings

        render_scanner_table(
            ranked_display.head(25),
            [
                "rank",
                "selected",
                "yahoo_ticker",
                "name",
                "region",
                "exchange",
                "currency",
                "sector",
                "latest_close",
                "technical_score",
                "scanner_score",
                "avg_traded_value_60d",
            ],
        )

        st.subheader("Selected Candidates")
        render_scanner_table(
            selected,
            [
                "rank",
                "yahoo_ticker",
                "name",
                "region",
                "exchange",
                "currency",
                "sector",
                "latest_close",
                "technical_score",
                "scanner_score",
            ],
        )

        st.subheader("Failed / Invalid Tickers")
        if failed.empty:
            st.success("No failed scanner tickers in the latest validation output.")
        else:
            render_scanner_table(
                failed,
                [
                    "yahoo_ticker",
                    "name",
                    "region",
                    "latest_close_present",
                    "valid_bar_count",
                    "missing_close_pct",
                    "stale_latest_price",
                    "volume_present",
                ],
            )


def equity_curve_y_domain(equity_series, reference_value=None):
    values = pd.to_numeric(equity_series, errors="coerce").dropna()
    if values.empty:
        return None

    min_value = float(values.min())
    max_value = float(values.max())
    value_range = max_value - min_value

    reference_candidates = [
        abs(float(reference_value))
        for reference_value in [reference_value, max_value, min_value]
        if reference_value is not None and pd.notna(reference_value)
    ]
    reference = max(reference_candidates) if reference_candidates else 0
    padding = max(value_range * 0.10, reference * 0.0015, 15)

    y_min = min_value - padding
    y_max = max_value + padding

    if min_value >= 0 and y_min < 0:
        y_min = 0
    if y_max <= y_min:
        y_max = y_min + max(padding * 2, 50)

    return y_min, y_max


def numeric_y_domain(values, *, minimum_padding):
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None

    min_value = float(values.min())
    max_value = float(values.max())
    value_range = max_value - min_value
    padding = max(value_range * 0.10, minimum_padding)

    y_min = min_value - padding
    y_max = max_value + padding
    if y_max <= y_min:
        y_max = y_min + max(padding * 2, minimum_padding * 2)

    return y_min, y_max


def render_equity_curve(chart_data, current_value, initial_capital=None):
    plot_data = chart_data.reset_index()[["date", "portfolio_value"]].copy()
    plot_data["date"] = pd.to_datetime(plot_data["date"], errors="coerce")
    plot_data["portfolio_value"] = pd.to_numeric(
        plot_data["portfolio_value"],
        errors="coerce",
    )
    plot_data = plot_data.dropna(subset=["date", "portfolio_value"])
    plot_data = plot_data.sort_values("date")
    plot_data["trading_date"] = plot_data["date"].dt.date
    plot_data = (
        plot_data.groupby("trading_date", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    if plot_data.empty:
        st.info("No valid equity values available for the chart yet.")
        return

    first_value = plot_data["portfolio_value"].iloc[0]
    baseline_value = initial_capital
    if baseline_value is None or pd.isna(baseline_value) or float(baseline_value) <= 0:
        baseline_value = first_value
    can_show_return = pd.notna(baseline_value) and float(baseline_value) != 0

    if can_show_return and abs(float(first_value) - float(baseline_value)) > 0.01:
        baseline_row = {
            "date": plot_data["date"].iloc[0] - pd.Timedelta(days=1),
            "portfolio_value": float(baseline_value),
            "trading_date": (
                plot_data["date"].iloc[0] - pd.Timedelta(days=1)
            ).date(),
        }
        plot_data = pd.concat(
            [pd.DataFrame([baseline_row]), plot_data],
            ignore_index=True,
        )

    plot_data["challenge_day"] = range(0, len(plot_data))
    plot_data["challenge_day_label"] = plot_data["challenge_day"].map(
        lambda day: f"Day {day}"
    )

    chart_mode = st.radio(
        "Equity chart view",
        ["Return from start (%)", "Zoomed GBP equity"],
        horizontal=True,
        key="thirty_day_equity_chart_view",
    )

    plot_data["return_pct"] = (
        (
            plot_data["portfolio_value"] / float(baseline_value) - 1
        )
        * 100
        if can_show_return
        else None
    )

    if chart_mode == "Return from start (%)" and can_show_return:
        y_domain = numeric_y_domain(
            plot_data["return_pct"],
            minimum_padding=0.05,
        )
        y_field = "return_pct:Q"
        y_title = "Return from start (%)"
        y_format = ".2f"
        zero_line = (
            alt.Chart(pd.DataFrame({"zero": [0]}))
            .mark_rule(color="rgba(148, 163, 184, 0.75)", strokeDash=[5, 5])
            .encode(y="zero:Q")
        )
        tooltip_value = alt.Tooltip(
            "return_pct:Q",
            title="Return from start",
            format=".2f",
        )
        caption = (
            "Return view shows cumulative percentage change from the "
            "30 Day Challenge initial capital."
        )
    else:
        y_domain = equity_curve_y_domain(
            plot_data["portfolio_value"],
            current_value,
        )
        y_field = "portfolio_value:Q"
        y_title = "Portfolio value (GBP, zoomed scale)"
        y_format = ",.2f"
        zero_line = None
        tooltip_value = alt.Tooltip(
            "portfolio_value:Q",
            title="Portfolio value",
            format=",.2f",
        )
        caption = (
            "Zoomed y-axis: "
            f"GBP {y_domain[0]:,.2f} to GBP {y_domain[1]:,.2f}."
            if y_domain is not None
            else ""
        )

    if y_domain is None:
        st.info("No valid equity values available for the chart yet.")
        return

    active_value_column = (
        "return_pct"
        if chart_mode == "Return from start (%)"
        else "portfolio_value"
    )
    chart_data_for_plot = plot_data.dropna(subset=[active_value_column])

    chart = (
        alt.Chart(chart_data_for_plot)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X(
                "challenge_day:O",
                title="Challenge day",
                axis=alt.Axis(labelExpr="'Day ' + datum.value"),
                sort=None,
            ),
            y=alt.Y(
                y_field,
                title=y_title,
                scale=alt.Scale(domain=list(y_domain), zero=False),
                axis=alt.Axis(format=y_format),
            ),
            tooltip=[
                alt.Tooltip(
                    "challenge_day_label:N",
                    title="Challenge day",
                ),
                alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
                alt.Tooltip(
                    "portfolio_value:Q",
                    title="Portfolio value",
                    format=",.2f",
                ),
                tooltip_value,
            ],
        )
        .properties(height=420)
    )
    if zero_line is not None:
        chart = zero_line + chart

    st.altair_chart(chart, width="stretch")
    if caption:
        st.caption(caption)


st.set_page_config(
    page_title="Garner Quant",
    page_icon="📊",
    layout="wide",
)

require_dashboard_login()
inject_mobile_css()
apply_responsive_styles()

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    supabase = (
        create_client(SUPABASE_URL, SUPABASE_KEY)
        if SUPABASE_URL and SUPABASE_KEY
        else None
    )
except Exception:
    supabase = None


def load_supabase_table(table_name, fallback_csv=None, order_col=None):
    try:
        if supabase is None:
            raise RuntimeError("Supabase is not configured.")

        query = supabase.table(table_name).select("*")

        if order_col:
            query = query.order(order_col)

        response = query.execute()
        return pd.DataFrame(response.data)

    except Exception:
        if fallback_csv:
            return load_csv(fallback_csv)

        return pd.DataFrame()


def load_trade_audit(journal):
    if journal is not None and not journal.empty:
        return build_trade_audit_trail(journal)

    return pd.DataFrame()


broker = load_supabase_table("broker_account", "broker_account.csv")
paper_30 = load_supabase_table(
    "paper_30_day_tracker",
    "paper_30_day_tracker.csv",
    "date",
)
holdings = load_supabase_table("holdings", "holdings_report.csv")
history = load_supabase_table("holdings_history", None, "date")
signals = load_supabase_table("signals", "signal_report_v2.csv")
trades = load_supabase_table("trade_journal", "trade_journal_v3.csv")

portfolio = load_csv("portfolio_v2.csv")
analytics = load_csv("trade_analytics_v3.csv")
snapshots = load_csv("trade_snapshots.csv")

if broker.empty:
    st.error(
        "broker_account.csv not found. Run main_v2.py first, then push the updated CSV files."
    )
    st.stop()

broker_row = broker.iloc[0]
current_unrealised_pnl = unrealised_pnl_from_holdings(
    holdings,
    fallback=broker_row.get("unrealised_pnl", 0),
)

if paper_30.empty:
    start_balance = 0
    current_balance = broker_row.get("portfolio_value", 0)
    total_return = 0
else:
    paper_row = paper_30.iloc[-1]
    start_balance = challenge_initial_capital(paper_30)
    current_balance = paper_row["portfolio_value"]
    total_return = (
        (current_balance / start_balance) - 1
        if start_balance > 0
        else 0
    )

win_rate_value = (
    analytics.iloc[0].get("win_rate", 0)
    if analytics is not None and not analytics.empty
    else 0
)
runtime_status = load_runtime_status()
runtime_details = runtime_brief_details(runtime_status)
latest_trade = latest_trade_details(trades)
open_positions = open_positions_count(holdings)
portfolio_value = broker_row.get("portfolio_value", current_balance)

st.title("Garner Quant")
st.caption("Personal investment research and paper trading dashboard.")

render_investment_brief(
    runtime_details,
    latest_trade,
    portfolio_value,
    total_return,
    broker_row.get("cash", 0),
    broker_row.get("buying_power", broker_row.get("cash", 0)),
    open_positions,
    win_rate_value,
)

home_tab, scanner_tab = st.tabs(["Home", "Global Scanner"])

with scanner_tab:
    render_global_scanner_page()

with home_tab:
    render_holdings_exposure(holdings, broker_row)

    st.divider()

    st.subheader("🚀 30 Day Paper Trading Challenge")

    if paper_30.empty:
        st.info("30 day tracker has not started yet.")
        start_balance = 0
        current_balance = 0
        total_return = 0

    else:
        paper_row = paper_30.iloc[-1]

        start_balance = challenge_initial_capital(paper_30)
        current_balance = paper_row["portfolio_value"]
        total_return = (
            (current_balance / start_balance) - 1
            if start_balance > 0
            else 0
        )

        paper_30["date"] = pd.to_datetime(
            paper_30["date"],
            errors="coerce",
        )

        start_date = paper_30["date"].min().date()
        today = pd.Timestamp.now().date()
        days_tracked = (today - start_date).days + 1

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card("Day", f"{days_tracked}/30", True)
            metric_card("Return", f"{total_return:.2%}", True)
            metric_card(
                "Realised PnL",
                f"£{paper_row['realised_pnl']:,.2f}",
                True,
            )

        with col2:
            metric_card("Starting Balance", f"£{start_balance:,.2f}")
            metric_card("Current Balance", f"£{current_balance:,.2f}")
            metric_card(
                "Unrealised PnL",
                f"£{current_unrealised_pnl:,.2f}",
                True,
            )

        st.subheader("📈 30 Day Equity Curve")

        chart_data = paper_30.copy()
        chart_data["date"] = pd.to_datetime(chart_data["date"])
        chart_data = chart_data.sort_values("date")
        chart_data = chart_data.set_index("date")

        render_equity_curve(chart_data, current_balance, start_balance)

    st.divider()

    st.subheader("📊 Strategy Analytics")

    cash_value = broker_row["cash"]
    portfolio_value = broker_row["portfolio_value"]
    cash_percent = cash_value / portfolio_value if portfolio_value > 0 else 0

    col1, col2 = responsive_columns(2)

    with col1:
        metric_card("Total Return", f"{total_return:.2%}", True)
        metric_card("Open Holdings", len(holdings))

    with col2:
        metric_card("Cash %", f"{cash_percent:.2%}", True)
        metric_card(
            "Unrealised PnL",
            f"£{current_unrealised_pnl:,.2f}",
            True,
        )

    st.subheader("📊 Benchmark")

    if not paper_30.empty:
        latest_tracker_row = paper_30.sort_values("date").iloc[-1]
        benchmark_return = float(
            latest_tracker_row.get("benchmark_return", 0)
        )

        if benchmark_return > 0.10:
            benchmark_return = benchmark_return / 100

        alpha = total_return - benchmark_return

        col1, col2, col3 = responsive_columns(3)

        with col1:
            metric_card("Garner Quant", f"{total_return:.2%}", True)

        with col2:
            metric_card("SPY", f"{benchmark_return:.2%}")

        with col3:
            metric_card("Alpha", f"{alpha:.2%}", True)

    else:
        st.info("No benchmark data available.")

    with st.expander("Open account balance details", expanded=False):

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card(
                "Portfolio Value",
                f"£{broker_row['portfolio_value']:,.2f}",
            )
            metric_card(
                "Buying Power",
                f"£{broker_row['buying_power']:,.2f}",
            )

        with col2:
            metric_card("Cash", f"£{broker_row['cash']:,.2f}")
            metric_card(
                "Unrealised PnL",
                f"£{current_unrealised_pnl:,.2f}",
                True,
            )

    st.divider()

    if not paper_30.empty and len(paper_30) > 1:
        portfolio_values = pd.to_numeric(
            paper_30["portfolio_value"],
            errors="coerce",
        )
        performance_values = portfolio_values[
            np.isfinite(portfolio_values) & (portfolio_values > 0)
        ]
        if len(performance_values) > 1:
            daily_return = performance_values.pct_change().dropna()

            best_day = daily_return.max()
            worst_day = daily_return.min()

            rolling_peak = performance_values.cummax()
            drawdown = (performance_values / rolling_peak) - 1
            max_drawdown = drawdown.min()

            col1, col2, col3 = responsive_columns(3)

            with col1:
                metric_card("Best Day", f"{best_day:.2%}", True)

            with col2:
                metric_card("Worst Day", f"{worst_day:.2%}")

            with col3:
                metric_card("Max Drawdown", f"{max_drawdown:.2%}")
        else:
            st.info("Need at least 2 valid days of data for daily return analytics.")

    else:
        st.info("Need at least 2 days of data for daily return analytics.")

    st.subheader("Day-over-Day Attribution")

    if history.empty:
        st.info("No holdings history available yet.")

    else:
        history["date"] = pd.to_datetime(history["date"])
        dates = sorted(history["date"].dt.date.unique())

        if len(dates) < 2:
            st.info("Need at least 2 days of holdings history for attribution.")

        else:
            yesterday = dates[-2]
            today = dates[-1]

            yesterday_holdings = history[
                history["date"].dt.date == yesterday
            ][["ticker", "market_value"]].rename(
                columns={"market_value": "Yesterday Value"}
            )

            today_holdings = history[
                history["date"].dt.date == today
            ][["ticker", "market_value"]].rename(
                columns={"market_value": "Today Value"}
            )

            attribution = today_holdings.merge(
                yesterday_holdings,
                on="ticker",
                how="outer",
            ).fillna(0)

            attribution["Daily PnL"] = (
                attribution["Today Value"]
                - attribution["Yesterday Value"]
            )

            total_yesterday = attribution["Yesterday Value"].sum()

            if total_yesterday > 0:
                attribution["Contribution %"] = (
                    attribution["Daily PnL"]
                    / total_yesterday
                    * 100
                )
            else:
                attribution["Contribution %"] = 0

            attribution = attribution.sort_values(
                "Daily PnL",
                ascending=False,
            )

            st.caption(f"Comparing {yesterday} → {today}")

            responsive_table(
                attribution.style.format(
                    {
                        "Yesterday Value": "£{:,.2f}",
                        "Today Value": "£{:,.2f}",
                        "Daily PnL": "£{:,.2f}",
                        "Contribution %": "{:.2f}%",
                    }
                ),
                hide_index=True,
            )

    st.subheader("Drawdown")

    if portfolio.empty or "drawdown" not in portfolio.columns:
        st.info("No drawdown data available.")
    else:
        st.line_chart(portfolio["drawdown"])

    st.divider()

    render_signals_summary(signals)

    with st.expander("Open detailed opportunity table", expanded=False):
        render_signal_tables(signals)

    st.divider()

    st.subheader("Trade Analytics")

    if analytics.empty:
        st.info("No trade analytics available.")
    else:
        analytics_row = analytics.iloc[0]

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card(
                "Journal Events",
                int(analytics_row["total_trades"]),
            )
            metric_card(
                "Win Rate",
                f"{analytics_row['win_rate']:.2%}",
                True,
            )

        with col2:
            metric_card(
                "Profit Factor",
                f"{analytics_row['profit_factor']:.2f}",
            )
            metric_card(
                "Realised PnL",
                f"£{analytics_row['realised_pnl']:,.2f}",
                True,
            )

    st.divider()

    with st.expander("Open detailed trade audit", expanded=False):
        st.subheader("Trade Audit")

        audit = load_trade_audit(trades)

        if audit.empty:
            st.info("No completed trades audited yet.")

        else:
            audit = audit.copy()

            audit["open_time"] = pd.to_datetime(
                audit["open_time"],
                format="mixed",
                errors="coerce",
            )

            audit["close_time"] = pd.to_datetime(
                audit["close_time"],
                format="mixed",
                errors="coerce",
            )

            audit["holding_days"] = (
                audit["close_time"] - audit["open_time"]
            ).dt.total_seconds() / 86400

            total_trades = len(audit)
            winning_trades = len(audit[audit["pnl"] > 0])
            losing_trades = len(audit[audit["pnl"] < 0])

            win_rate = (
                winning_trades / total_trades * 100
                if total_trades
                else 0
            )

            total_pnl = audit["pnl"].sum()
            best_trade = audit["pnl"].max()
            worst_trade = audit["pnl"].min()
            avg_pnl = audit["pnl"].mean()

            gross_profit = audit.loc[audit["pnl"] > 0, "pnl"].sum()
            gross_loss = abs(audit.loc[audit["pnl"] < 0, "pnl"].sum())

            profit_factor = (
                gross_profit / gross_loss
                if gross_loss > 0
                else 0
            )

            avg_win = (
                audit.loc[audit["pnl"] > 0, "pnl"].mean()
                if winning_trades > 0
                else 0
            )

            avg_loss = (
                audit.loc[audit["pnl"] < 0, "pnl"].mean()
                if losing_trades > 0
                else 0
            )

            c1, c2, c3 = responsive_columns(3)

            with c1:
                metric_card("Completed BUY -> SELL Pairs", total_trades)
                metric_card("Winners", winning_trades)

            with c2:
                metric_card("Win Rate", f"{win_rate:.1f}%", True)
                metric_card("Losers", losing_trades)

            with c3:
                metric_card("Total PnL", f"£{total_pnl:,.2f}", total_pnl >= 0)
                metric_card("Profit Factor", f"{profit_factor:.2f}", profit_factor >= 1)

            c4, c5, c6 = responsive_columns(3)

            with c4:
                metric_card("Average PnL", f"£{avg_pnl:,.2f}", avg_pnl >= 0)

            with c5:
                metric_card("Best Trade", f"£{best_trade:,.2f}", best_trade >= 0)

            with c6:
                metric_card("Worst Trade", f"£{worst_trade:,.2f}", worst_trade >= 0)

            st.divider()

            audit = audit.tail(50).iloc[::-1]

            for _, trade in audit.iterrows():
                symbol = trade.get("symbol", "Unknown")
                pnl = trade.get("pnl", 0)
                pnl_pct = trade.get("pnl_pct", 0)

                open_time = trade.get("open_time")
                close_time = trade.get("close_time")

                opened = (
                    open_time.strftime("%Y-%m-%d %H:%M")
                    if pd.notna(open_time)
                    else "N/A"
                )
                closed = (
                    close_time.strftime("%Y-%m-%d %H:%M")
                    if pd.notna(close_time)
                    else "N/A"
                )

                buy_price = trade.get("buy_price", 0)
                sell_price = trade.get("sell_price", 0)
                shares = trade.get("shares", 0)
                held = trade.get("holding_period", "N/A")
                open_reason = trade.get("open_reason", "N/A")
                close_reason = trade.get("close_reason", "N/A")

                result = "WIN ✅" if pnl > 0 else "LOSS ❌" if pnl < 0 else "FLAT ➖"

                with st.container(border=True):
                    st.subheader(f"{symbol} — {result}")

                    col1, col2 = responsive_columns(2)

                with col1:
                    st.write(f"**Opened:** {opened}")
                    st.write(f"**Closed:** {closed}")
                    st.write(f"**Held:** {held}")
                    st.write(f"**Shares:** {shares:.4f}")

                with col2:
                    st.write(f"**Buy:** £{buy_price:,.2f}")
                    st.write(f"**Sell:** £{sell_price:,.2f}")
                    st.write(f"**PnL:** £{pnl:,.2f} ({pnl_pct:.2f}%)")

                with st.expander("🔍 Trade Replay"):
                    trade_snapshot = pd.DataFrame()

                    if not snapshots.empty:

                        trade_snapshot = snapshots[
                            snapshots["ticker"] == symbol
                        ].copy()

                        if not trade_snapshot.empty:

                            trade_snapshot["timestamp"] = pd.to_datetime(
                                trade_snapshot["timestamp"],
                                errors="coerce"
                            )

                            trade_snapshot = trade_snapshot.sort_values("timestamp")

                    if trade_snapshot.empty:

                        st.info("No snapshot data available.")

                    else:

                        buy_rows = trade_snapshot[trade_snapshot["event"] == "BUY"]
                        sell_rows = trade_snapshot[trade_snapshot["event"] == "SELL"]

                        if buy_rows.empty:
                            st.info("No entry snapshot available for this trade yet.")
                            st.stop()

                        buy = buy_rows.iloc[0]
                        sell = sell_rows.iloc[-1] if not sell_rows.empty else None

                        st.markdown("### 🟢 Entry")

                        c1, c2 = responsive_columns(2)

                        with c1:
                            st.metric("Cash", f"£{buy['cash']:,.2f}")
                            st.metric("Weight", f"{buy['portfolio_weight']:.1%}")

                        with c2:
                            st.metric("Stop Loss", f"£{buy['stop_loss']:,.2f}")
                            st.metric("Take Profit", f"£{buy['take_profit']:,.2f}")

                        st.write(f"**Reason:** {buy['reason']}")

                        st.divider()

                        st.markdown("### 🔴 Exit")

                        if sell is None:
                            st.info("No exit snapshot available yet. This trade may still be open or was created before snapshot logging.")
                        else:
                            st.metric("Reason", sell["reason"])

                            st.metric(
                                "Portfolio Value",
                                f"£{sell['portfolio_value']:,.2f}"
                            )

                        st.divider()

                        st.markdown("### 📈 Result")

                        c1, c2 = responsive_columns(2)

                        with c1:
                            st.metric("PnL", f"£{pnl:,.2f}")

                        with c2:
                            st.metric("Return", f"{pnl_pct:.2f}%")

    st.divider()
    
    if audit.empty or "close_time" not in audit.columns or "pnl" not in audit.columns:
        st.info("No completed trade equity curve available yet.")
    else:
        st.subheader("📈 Realised Equity Curve")

        equity = audit.copy()
        equity["close_time"] = pd.to_datetime(
            equity["close_time"],
            format="mixed",
            errors="coerce"
        )

        equity = equity.dropna(subset=["close_time"])
        equity = equity.sort_values("close_time")
        equity["Cumulative PnL"] = equity["pnl"].cumsum()

        st.line_chart(
            equity.set_index("close_time")["Cumulative PnL"],
            width="stretch",
        )
    if audit.empty or "pnl" not in audit.columns:
        st.info("No trade statistics available yet.")
    else:
        st.subheader("Trade Statistics")

        if "holding_days" in audit.columns:
            avg_hold = audit["holding_days"].mean()
        elif "holding_period" in audit.columns:
            holding = pd.to_timedelta(
                audit["holding_period"],
                errors="coerce"
            )
            avg_hold = holding.dt.total_seconds().div(86400).mean()
        else:
            avg_hold = 0
 
        if "pnl_pct" in audit.columns:
            avg_return = audit["pnl_pct"].mean()
        else:
            avg_return = 0

        largest_win = (
            audit.loc[audit["pnl"].idxmax(), "symbol"]
            if "symbol" in audit.columns and len(audit[audit["pnl"] > 0]) > 0
            else "None"
        )

        c1, c2, c3 = responsive_columns(3)

        with c1:
            metric_card("Average Hold", f"{avg_hold:.1f} days")

        with c2:
            metric_card("Average Return", f"{avg_return:.2f}%", avg_return >= 0)

        with c3:
            metric_card("Largest Winner", largest_win)

    st.subheader("Trade Journal")

    if trades.empty:
        st.info("No trades logged yet.")

    else:
        trades = trades.copy()

        trades.columns = [
            col.lower().replace(" ", "_")
            for col in trades.columns
        ]

        required_cols = [
            "date",
            "time",
            "ticker",
            "action",
            "shares",
            "price",
            "value",
            "pnl",
            "reason",
        ]

        for col in required_cols:
            if col not in trades.columns:
                trades[col] = ""

        trades["time"] = trades["time"].fillna("").replace("nan", "")

        trades["date"] = (
            pd.to_datetime(
                trades["date"],
                format="mixed",
                errors="coerce",
            )
            .dt.strftime("%Y-%m-%d")
            .fillna("")
        )

        display_trades = trades[
            required_cols
        ].rename(
            columns={
                "date": "Date",
                "time": "Time",
                "ticker": "Ticker",
                "action": "Action",
                "shares": "Shares",
                "price": "Price",
                "value": "Value",
                "pnl": "PnL",
                "reason": "Reason",
            }
        )

        display_trades = display_trades.tail(20).iloc[::-1]

        responsive_table(
            display_trades.style.format(
                {
                    "Shares": "{:.2f}",
                    "Price": "£{:,.2f}",
                    "Value": "£{:,.2f}",
                    "PnL": "£{:,.2f}",
                }
            ),
            hide_index=True,
        )


st.caption("Garner Quant V3 | Paper Trading Only")
