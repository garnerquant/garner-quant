import html
import json
import logging
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
from dashboard.equity_chart import build_equity_curve_layers, build_realised_equity_chart
from dashboard.metrics import unrealised_pnl_from_holdings
from dashboard.paper_challenge import (
    build_day_over_day_attribution,
    build_paper_challenge_series,
    build_realised_pnl_series,
)
from dashboard.scanner_reader import ScannerDashboardReader, ScannerReaderError
from config import PAPER_TRADING_CHALLENGE_DAYS
from execution.trade_audit import build_authoritative_trade_audit
from reporting.paper_performance import challenge_initial_capital
from ui.auth import require_dashboard_login
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)
from ui.runtime_status import load_runtime_status, runtime_freshness, runtime_state

PROJECT_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
SCANNER_FEATURE_STORE_DIR = PROJECT_ROOT / "data" / "global_scanner" / "feature_store"
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
            padding:9px 10px;
            margin:9px 0;
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
            gap:7px;
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

        .scanner-takeaway-title {
            color:#e5e7eb;
            font-size:12px;
            font-weight:760;
            margin-top:10px;
        }

        .scanner-diagnostics {
            margin-top:10px;
            color:#cbd5e1;
            font-size:12px;
            border-top:1px solid rgba(148,163,184,0.14);
            padding-top:8px;
        }

        .scanner-diagnostics summary {
            color:#94a3b8;
            cursor:pointer;
            font-weight:700;
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


def scanner_bool_series(frame, column):
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=bool)

    return frame[column].astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y"}
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
    state = scanner_display_value(row, "movement_state", "").lower()
    if state == "new":
        return "NEW", "scanner-move-new"

    change = scanner_number(row, "rank_delta")
    if change is None:
        return "UNCHANGED", "scanner-move-flat"

    if change > 0:
        return f"▲ +{int(change)}", "scanner-move-up"
    if change < 0:
        return f"▼ {int(change)}", "scanner-move-down"

    return "UNCHANGED", "scanner-move-flat"


def scanner_research_summary(row):
    region = scanner_display_value(row, "country", "")
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


def scanner_has_risk_profile(row):
    return all(column in row.index for column in SCANNER_RISK_COLUMNS)


def scanner_has_persistence_profile(row):
    return all(column in row.index for column in SCANNER_PERSISTENCE_COLUMNS)


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


def scanner_add_unique_takeaway(items, text):
    if not text:
        return

    key = str(text).strip().lower()
    if key and key not in {item.lower() for item in items}:
        items.append(str(text).strip())


def scanner_key_takeaways(row):
    takeaways = []

    risk_level = scanner_display_value(row, "risk_level", "")
    volatility = scanner_number(row, "volatility_60d")
    drawdown = scanner_number(row, "max_drawdown_1y")
    if risk_level in {"High", "Very High"}:
        scanner_add_unique_takeaway(takeaways, f"{risk_level} risk profile")
    elif drawdown is not None and drawdown < 15:
        scanner_add_unique_takeaway(takeaways, "Low historical drawdown")
    elif volatility is not None:
        if volatility >= 45:
            scanner_add_unique_takeaway(takeaways, "High volatility")
        elif volatility >= 20:
            scanner_add_unique_takeaway(takeaways, "Moderate volatility")

    technical_score = scanner_number(row, "technical_score")
    if technical_score is not None:
        if technical_score >= 4:
            scanner_add_unique_takeaway(takeaways, "Strong technical momentum")
        elif technical_score >= 3:
            scanner_add_unique_takeaway(takeaways, "Positive technical profile")

    persistence_score = scanner_number(row, "persistence_score")
    days = scanner_number(row, "days_in_top_list")
    if persistence_score is not None and persistence_score >= 85:
        scanner_add_unique_takeaway(takeaways, "Strong persistence")
    elif days is not None and days >= 10:
        scanner_add_unique_takeaway(takeaways, "Persistent research candidate")

    if len(takeaways) < 3:
        for bullet in scanner_risk_bullets(row) + scanner_persistence_bullets(row):
            scanner_add_unique_takeaway(takeaways, bullet)
            if len(takeaways) >= 3:
                break

    return takeaways[:3]


def scanner_research_diagnostics(row):
    diagnostics = []
    component_labels = [
        ("freshness_component", "Data freshness"),
        ("history_component", "History coverage"),
        ("missing_data_component", "Missing data"),
        ("liquidity_component", "Liquidity component"),
        ("volume_component", "Volume component"),
        ("technical_component", "Technical component"),
    ]
    for column, label in component_labels:
        value = scanner_number(row, column)
        if value is not None:
            diagnostics.append(f"{label}: {value:.1f}")

    details = [
        ("volatility_20d", "20d volatility", scanner_percent_label),
        ("volatility_60d", "60d volatility", scanner_percent_label),
        ("atr_percent", "ATR", scanner_percent_label),
        ("max_drawdown_1y", "1Y max drawdown", scanner_percent_label),
        ("highest_rank_seen", "Highest rank", scanner_integer_label),
        ("average_rank", "Average rank", scanner_decimal_label),
        ("rank_volatility", "Rank volatility", scanner_decimal_label),
    ]
    for column, label, formatter in details:
        if column in row.index:
            value = formatter(row.get(column))
            if value != "Unavailable":
                diagnostics.append(f"{label}: {value}")

    return diagnostics


def scanner_diagnostics_html(row):
    diagnostics = scanner_research_diagnostics(row)
    if not diagnostics:
        return ""

    return (
        '<details class="scanner-diagnostics">'
        "<summary>Research Diagnostics</summary>"
        f"{scanner_bullet_list_html(diagnostics)}"
        "</details>"
    )


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

    return f"""
        <div class="scanner-risk-profile">
            <div class="scanner-risk-title">Risk</div>
            <div class="scanner-risk-grid">
                <div><span class="scanner-fact-label">Risk Level</span><br><span class="scanner-risk-value">{risk}</span></div>
                <div><span class="scanner-fact-label">Trend Stability</span><br><span class="scanner-risk-value">{html.escape(stability_label)}</span></div>
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

    return f"""
        <div class="scanner-risk-profile">
            <div class="scanner-risk-title">Persistence</div>
            <div class="scanner-risk-grid">
                <div><span class="scanner-fact-label">Level</span><br><span class="scanner-risk-value">{level}</span></div>
                <div><span class="scanner-fact-label">Score</span><br><span class="scanner-risk-value">{html.escape(score_label)}</span></div>
                <div><span class="scanner-fact-label">Days tracked</span><br><span class="scanner-risk-value">{html.escape(days)}</span></div>
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


def scanner_compare_label(row):
    ticker = scanner_display_value(row, "ticker", "Unknown")
    name = scanner_display_value(row, "display_name", "")
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
    metrics = [
        {
            "label": "Opportunity Score",
            "column": "scanner_score",
            "kind": "score",
            "compare": "higher",
        },
        {
            "label": "Data Quality Confidence",
            "column": "data_quality_confidence",
            "kind": "score",
            "compare": "higher",
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

    region = scanner_display_value(row, "country", "")
    if region:
        bullets.append(f"Leading opportunity from {region}")

    sector = scanner_display_value(row, "sector", "")
    if sector:
        bullets.append(f"Strong candidate within the {sector} sector")

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
    cards = cards.sort_values("global_rank", ascending=True)
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
        rank = scanner_display_value(row, "global_rank", "?")
        movement_label, movement_class = scanner_rank_movement(row)
        ticker = html.escape(scanner_display_value(row, "ticker", "UNKNOWN"))
        name = html.escape(scanner_display_value(row, "display_name", "Unnamed candidate"))
        region_raw = scanner_display_value(row, "country", "Unknown country")
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
        takeaways = scanner_key_takeaways(row)
        takeaway_html = scanner_bullet_list_html(takeaways)
        if takeaway_html:
            takeaway_html = (
                '<div class="scanner-takeaway-title">Key Takeaways</div>'
                f"{takeaway_html}"
            )
        diagnostics_html = scanner_diagnostics_html(row)
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
                {risk_profile_html}
                {persistence_profile_html}
                {takeaway_html}
                {diagnostics_html}
            </div>
        """

        with columns[index % len(columns)]:
            st.html(card_html)


def render_global_scanner_page():
    st.subheader("Global Scanner")
    st.caption("Read-only view of the currently published Scanner v2 generation.")
    if st.button("Reload published generation", key="reload_scanner_generation"):
        st.rerun()

    try:
        bundle = ScannerDashboardReader(SCANNER_FEATURE_STORE_DIR).load_bundle()
    except ScannerReaderError as exc:
        messages = {
            "no_active_generation": "No completed Scanner v2 generation is currently published.",
            "missing_generation": "The active Scanner v2 pointer references a missing generation.",
            "incomplete_generation": "The active Scanner v2 generation is incomplete and was not loaded.",
            "missing_artifact": "The active Scanner v2 generation is missing a required artifact.",
            "malformed_pointer": "The Scanner v2 active-generation pointer is invalid.",
            "malformed_manifest": "The Scanner v2 generation manifest is invalid.",
        }
        st.error(messages.get(
            exc.code,
            "Scanner output contract validation failed. Run the Scanner v2 producer outside the dashboard.",
        ))
        st.caption("Run Scanner v2 acquisition and feature generation outside Streamlit, then reload this page.")
        return

    metadata = bundle.metadata
    features = bundle.features
    rankings = bundle.rankings
    selected = bundle.candidates
    rejected = bundle.rejections
    movement = bundle.movement

    st.success("Completed Scanner v2 generation loaded successfully.")
    metadata_columns = responsive_columns(4)
    metadata_columns[0].metric("Generation", metadata.generation_id[:12])
    metadata_columns[1].metric("Scored assets", metadata.scored_assets)
    metadata_columns[2].metric("Candidates", metadata.candidate_count)
    metadata_columns[3].metric("Rejected / failed", metadata.rejected_assets + metadata.failed_assets)
    st.caption(
        f"Completed {format_scanner_timestamp(metadata.ended_at)} · "
        f"Acquisition {metadata.acquisition_generation} · "
        f"Schema {metadata.feature_schema_version} · Scoring {metadata.scoring_version}"
    )

    if selected.empty:
        st.info("The completed Scanner v2 generation contains zero selected candidates.")
    else:
        st.subheader("Selected Candidates")
        render_opportunity_intelligence(selected)
        render_opportunity_comparison(selected)

    st.info(
        "Portfolio-fit and diversification scoring is unavailable in this view "
        "until it is published as a canonical producer output."
    )

    st.divider()
    if "sector" in features.columns:
        st.subheader("Sector Breakdown")
        sector_breakdown = (
            features.groupby("sector", dropna=False)
            .size()
            .reset_index(name="tickers")
            .sort_values("tickers", ascending=False)
        )
        responsive_table(sector_breakdown, hide_index=True)

    with st.expander("Scanner Output Tables", expanded=False):
        st.subheader("Top Ranked Opportunities")
        render_scanner_table(
            rankings.head(25),
            [
                "global_rank",
                "selected_for_research",
                "ticker",
                "display_name",
                "country",
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
                "global_rank",
                "ticker",
                "display_name",
                "country",
                "exchange",
                "currency",
                "sector",
                "latest_close",
                "technical_score",
                "scanner_score",
            ],
        )

        st.subheader("Rejected / Failed Assets")
        if rejected.empty:
            st.success("No rejected or failed assets in this generation.")
        else:
            render_scanner_table(
                rejected,
                [
                    "ticker",
                    "display_name",
                    "terminal_state",
                    "rejection_reason",
                ],
            )

        st.subheader("Ranking Movement")
        if movement.empty:
            st.info("No ranking movement rows were published for this generation.")
        else:
            render_scanner_table(
                movement,
                [
                    "ticker", "previous_rank", "current_rank", "rank_delta",
                    "previous_score", "current_score", "score_delta", "movement_state",
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
    plot_data = chart_data.copy()
    if plot_data.empty:
        st.info("No valid equity values available for the chart yet.")
        return

    baseline_value = initial_capital
    if baseline_value is None or pd.isna(baseline_value) or float(baseline_value) <= 0:
        baseline_value = plot_data["portfolio_value"].iloc[0]
    can_show_return = pd.notna(baseline_value) and float(baseline_value) != 0

    chart_mode = st.radio(
        "Equity chart view",
        ["Return from start (%)", "Zoomed GBP equity"],
        horizontal=True,
        key="paper_challenge_equity_chart_view",
    )

    if "return_pct" not in plot_data.columns:
        plot_data["return_pct"] = (
            (plot_data["portfolio_value"] / float(baseline_value) - 1) * 100
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
            f"{PAPER_TRADING_CHALLENGE_DAYS} Day Challenge initial capital."
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

    shared_encoding = {
        "x": alt.X(
            "challenge_day:Q",
            title="Challenge day",
            axis=alt.Axis(labelExpr="'Day ' + datum.value"),
            scale=alt.Scale(domain=[0, PAPER_TRADING_CHALLENGE_DAYS]),
        ),
        "y": alt.Y(
            y_field,
            title=y_title,
            scale=alt.Scale(domain=list(y_domain), zero=False),
            axis=alt.Axis(format=y_format),
        ),
    }
    tooltip = [
        alt.Tooltip("challenge_day_label:N", title="Challenge day"),
        alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
        alt.Tooltip("is_recorded:N", title="Recorded snapshot"),
        alt.Tooltip(
            "portfolio_value:Q",
            title="Portfolio value",
            format=",.2f",
        ),
        tooltip_value,
    ]
    chart = build_equity_curve_layers(
        chart_data_for_plot,
        shared_encoding,
        tooltip,
    ).properties(height=420)
    if zero_line is not None:
        chart = zero_line + chart

    st.altair_chart(chart, width="stretch")
    if caption:
        st.caption(caption)
    st.caption("Only recorded valuation days are plotted; missing days are not converted to zero or forward-filled.")


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


HOME_SOURCE_DETAILS = {}


def csv_modified_at(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        return pd.Timestamp.fromtimestamp(path.stat().st_mtime, tz="UTC")
    except Exception:
        return None


def frame_latest_timestamp(frame, table_name):
    if frame is None or frame.empty:
        return None

    candidates = {
        "broker_account": ["updated_at", "timestamp", "date"],
        "paper_30_day_tracker": ["date", "updated_at", "timestamp"],
        "holdings": ["valuation_updated_at", "updated_at", "date", "timestamp"],
        "trade_journal": ["timestamp", "created_at", "date"],
    }.get(table_name, ["updated_at", "timestamp", "date"])

    data = frame.copy()
    if table_name == "trade_journal" and {"date", "time"}.issubset(data.columns):
        date_text = data["date"].fillna("").astype(str)
        time_text = data["time"].fillna("").astype(str).replace("nan", "")
        parsed = pd.to_datetime(
            (date_text + " " + time_text).str.strip(),
            errors="coerce",
            utc=True,
        )
        if parsed.notna().any():
            return parsed.max()

    for column in candidates:
        if column not in data.columns:
            continue
        parsed = pd.to_datetime(data[column], errors="coerce", utc=True)
        if parsed.notna().any():
            return parsed.max()

    return None


def local_home_accounting_reconciled(tolerance=0.01):
    broker = load_csv("broker_account.csv")
    holdings = load_csv("holdings_report.csv")
    portfolio = load_csv("paper_portfolio_v3.csv")

    if broker.empty or holdings.empty or portfolio.empty:
        return False
    if not {"cash", "positions_value", "portfolio_value"}.issubset(broker.columns):
        return False
    if "market_value" not in holdings.columns:
        return False

    broker_row = broker.iloc[0]
    cash = numeric_value(broker_row.get("cash"))
    positions_value = numeric_value(broker_row.get("positions_value"))
    portfolio_value = numeric_value(broker_row.get("portfolio_value"))
    holding_values = pd.to_numeric(holdings.get("market_value"), errors="coerce")
    if holding_values.isna().any():
        return False
    holdings_value = numeric_value(holding_values.sum())

    if abs(holdings_value - positions_value) > tolerance:
        return False
    if abs((cash + holdings_value) - portfolio_value) > tolerance:
        return False

    if "ticker" not in holdings.columns or "ticker" not in portfolio.columns:
        return False

    holdings_tickers = set(
        holdings["ticker"].dropna().astype(str).str.strip().str.upper()
    )
    portfolio_tickers = set(
        portfolio["ticker"].dropna().astype(str).str.strip().str.upper()
    )
    holdings_tickers.discard("CASH")
    portfolio_tickers.discard("CASH")
    return holdings_tickers == portfolio_tickers


def load_home_table(table_name, fallback_csv=None, order_col=None):
    local = load_csv(fallback_csv) if fallback_csv else pd.DataFrame()
    local_reconciled = local_home_accounting_reconciled()
    remote = pd.DataFrame()
    remote_error = None

    try:
        if supabase is None:
            raise RuntimeError("Supabase is not configured.")

        query = supabase.table(table_name).select("*")
        if order_col:
            query = query.order(order_col)
        response = query.execute()
        remote = pd.DataFrame(response.data)
    except Exception as exc:
        remote_error = str(exc)

    local_ts = frame_latest_timestamp(local, table_name) or csv_modified_at(fallback_csv)
    remote_ts = frame_latest_timestamp(remote, table_name)

    accounting_projection = table_name in {
        "broker_account",
        "paper_30_day_tracker",
        "holdings",
    }
    use_local = bool(
        fallback_csv
        and not local.empty
        and local_reconciled
        and (
            accounting_projection
            or remote.empty
            or remote_ts is None
            or (local_ts is not None and local_ts >= remote_ts)
        )
    )

    if use_local:
        source = "local CSV (reconciled)"
        frame = local
    elif not remote.empty:
        source = "Supabase"
        frame = remote
    elif not local.empty:
        source = "local CSV fallback"
        frame = local
    else:
        source = "unavailable"
        frame = pd.DataFrame()

    HOME_SOURCE_DETAILS[table_name] = {
        "source": source,
        "local_reconciled": local_reconciled,
        "local_timestamp": local_ts,
        "remote_timestamp": remote_ts,
        "remote_error": remote_error,
    }
    return frame


def home_source_summary():
    labels = []
    for table_name in ["broker_account", "paper_30_day_tracker", "holdings", "trade_journal"]:
        detail = HOME_SOURCE_DETAILS.get(table_name, {})
        source = detail.get("source", "unknown")
        if table_name == "paper_30_day_tracker":
            label = "tracker"
        elif table_name == "trade_journal":
            label = "trades"
        else:
            label = table_name.replace("_account", "").replace("_", " ")
        labels.append(f"{label}: {source}")
    return "Home data sources | " + " | ".join(labels)


def load_trade_audit(journal):
    return build_authoritative_trade_audit(journal)


broker = load_home_table("broker_account", "broker_account.csv")
paper_30 = load_home_table(
    "paper_30_day_tracker",
    "paper_30_day_tracker.csv",
    "date",
)
holdings = load_home_table("holdings", "holdings_report.csv")
history = load_supabase_table("holdings_history", None, "date")
signals = load_supabase_table("signals", "signal_report_v2.csv")
trades = load_home_table("trade_journal", "trade_journal_v3.csv")

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
    challenge_result = None
else:
    start_balance = challenge_initial_capital(paper_30)
    challenge_result = build_paper_challenge_series(
        paper_30,
        start_balance,
        PAPER_TRADING_CHALLENGE_DAYS,
        today=pd.Timestamp.now().date(),
    )
    valid_tracker = paper_30.copy()
    valid_tracker["_timestamp"] = pd.to_datetime(valid_tracker["date"], errors="coerce")
    valid_tracker = valid_tracker.dropna(subset=["_timestamp"]).sort_values("_timestamp", kind="stable")
    if not valid_tracker.empty and not challenge_result.data.empty:
        endpoint_timestamp = challenge_result.data.iloc[-1]["timestamp"]
        challenge_tracker = valid_tracker[valid_tracker["_timestamp"].le(endpoint_timestamp)]
        paper_row = challenge_tracker.iloc[-1] if not challenge_tracker.empty else valid_tracker.iloc[-1]
    else:
        paper_row = broker_row
    current_balance = (
        float(challenge_result.data.iloc[-1]["total_equity"])
        if not challenge_result.data.empty
        else float(paper_row["portfolio_value"])
    )
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
st.caption(home_source_summary())

home_tab, scanner_tab = st.tabs(["Home", "Global Scanner"])

with scanner_tab:
    render_global_scanner_page()

with home_tab:
    render_holdings_exposure(holdings, broker_row)

    st.divider()

    st.subheader(f"🚀 {PAPER_TRADING_CHALLENGE_DAYS} Day Paper Trading Challenge")

    if paper_30.empty or challenge_result is None or challenge_result.data.empty:
        if paper_30.empty:
            st.info(f"{PAPER_TRADING_CHALLENGE_DAYS} day tracker has not started yet.")
        else:
            st.warning("Equity history exists, but it contains no valid total-equity observations.")
        start_balance = 0
        current_balance = 0
        total_return = 0

    else:
        start_balance = challenge_initial_capital(paper_30)
        chart_data = challenge_result.data.copy(deep=True)
        current_challenge_day = challenge_result.current_day
        current_balance = float(chart_data.iloc[-1]["total_equity"])
        total_return = (
            (current_balance / start_balance) - 1
            if start_balance > 0
            else 0
        )

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card("Day", f"{current_challenge_day}/{PAPER_TRADING_CHALLENGE_DAYS}", True)
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

        if challenge_result.completed:
            st.success(f"The {PAPER_TRADING_CHALLENGE_DAYS}-day challenge is complete.")
        if challenge_result.malformed_observations:
            st.warning(f"{challenge_result.malformed_observations} malformed equity observation(s) were excluded.")
        if challenge_result.incomplete_valuations:
            st.warning(f"{challenge_result.incomplete_valuations} valuation observation(s) lack a usable cash balance.")
        if challenge_result.reconciliation_error:
            LOGGER.warning("Paper challenge reconciliation: %s", challenge_result.reconciliation_error)
            st.warning("The latest equity observation does not reconcile to the displayed account balance.")

        st.subheader(f"📈 {PAPER_TRADING_CHALLENGE_DAYS} Day Equity Curve")

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

    if challenge_result is not None and len(challenge_result.data) > 1:
        performance_values = challenge_result.data["total_equity"]
        if len(performance_values) > 1:
            daily_return = performance_values.pct_change().dropna()

            best_day = daily_return.max()
            worst_day = daily_return.min()

            drawdown = challenge_result.data["drawdown_pct"] / 100
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

    attribution_result = build_day_over_day_attribution(history, paper_30)
    if attribution_result.status == "available":
        attribution = attribution_result.data.rename(columns={
            "component": "Component",
            "beginning_value": "Beginning Value",
            "ending_value": "Ending Value",
            "attribution": "Equity Change",
        }).sort_values("Equity Change", ascending=False, kind="stable")

        st.caption(
            f"Comparing {attribution_result.beginning_date.date()} → "
            f"{attribution_result.ending_date.date()}; components reconcile to "
            f"£{attribution_result.equity_change:,.2f}. Cash includes flows, realised activity, and fees because the current snapshot contract does not separate them."
        )
        responsive_table(
            attribution.style.format({
                "Beginning Value": "£{:,.2f}",
                "Ending Value": "£{:,.2f}",
                "Equity Change": "£{:,.2f}",
            }),
            hide_index=True,
        )
    elif attribution_result.status == "mismatch":
        LOGGER.warning("Paper attribution reconciliation: %s", attribution_result.message)
        st.warning("Holdings snapshots are present, but attribution does not reconcile to account equity and was not presented as valid.")
    elif attribution_result.status == "malformed":
        st.warning("Holdings history exists but does not satisfy the attribution data contract.")
    else:
        st.info("Attribution is unavailable until two comparable canonical holdings and account snapshots exist. Current holdings are never used to reconstruct history.")

    st.subheader("Drawdown")

    if challenge_result is None or challenge_result.data.empty:
        st.info("No valid total-equity history is available for drawdown.")
    elif len(challenge_result.data) == 1:
        st.info("Only the starting equity observation is available; drawdown is 0.00%.")
    else:
        drawdown_data = challenge_result.data[
            ["timestamp", "challenge_day", "total_equity", "running_peak", "drawdown_pct"]
        ].copy()
        drawdown_chart = (
            alt.Chart(drawdown_data)
            .mark_line(point=True, color="#DC2626")
            .encode(
                x=alt.X(
                    "challenge_day:Q",
                    title="Challenge day",
                    scale=alt.Scale(domain=[0, PAPER_TRADING_CHALLENGE_DAYS]),
                ),
                y=alt.Y("drawdown_pct:Q", title="Drawdown (%)", scale=alt.Scale(zero=True)),
                tooltip=[
                    alt.Tooltip("timestamp:T", title="Date", format="%Y-%m-%d"),
                    alt.Tooltip("challenge_day:Q", title="Challenge day"),
                    alt.Tooltip("total_equity:Q", title="Total equity", format=",.2f"),
                    alt.Tooltip("running_peak:Q", title="Running peak", format=",.2f"),
                    alt.Tooltip("drawdown_pct:Q", title="Drawdown", format=".2f"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(drawdown_chart, width="stretch")
        st.caption("Drawdown is calculated only from the same recorded total-equity observations shown in the challenge curve.")

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
    
    realised_series = build_realised_pnl_series(
        audit,
        paper_row.get("realised_pnl"),
        starting_balance=start_balance,
        challenge_start_date=(
            challenge_result.data.iloc[0]["date"]
            if challenge_result is not None and not challenge_result.data.empty
            else None
        ),
        through=(
            challenge_result.data.iloc[-1]["timestamp"]
            if challenge_result is not None and not challenge_result.data.empty
            else None
        ),
    )
    if realised_series.reconciliation_error:
        LOGGER.warning("Paper realised P&L reconciliation: %s", realised_series.reconciliation_error)
        st.warning("Realised trade events do not reconcile to the headline Realised P&L, so the curve was not displayed as valid.")
    elif realised_series.event_count == 0:
        st.info("No canonical realised trade events are available yet; realised P&L remains £0.00 until the first close.")
    else:
        st.subheader("📈 Realised Equity Curve")
        realised_chart = build_realised_equity_chart(realised_series.data, start_balance)
        st.altair_chart(realised_chart, width="stretch")
        st.caption("Starting balance plus canonical after-fee realised P&L; same-day closes are netted for display only.")
    if realised_series.malformed_events:
        st.warning(f"{realised_series.malformed_events} malformed realised event(s) were excluded.")
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
