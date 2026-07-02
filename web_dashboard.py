import html
import json
import os
from pathlib import Path

import altair as alt
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

    st.markdown(
        f"""
        <div class="portfolio-hero">
            <div class="status-strip">
                <span class="runtime-badge">{html.escape(str(runtime_label))}</span>
                <span>Freshness {html.escape(str(freshness.get("label", "Unknown")))}</span>
                <span>Last Scan {html.escape(runtime_details["last_scan"])}</span>
                <span>Next {html.escape(str(runtime_details["next_scan"]))}</span>
            </div>
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
            runtime_event.get("message") or state.get("activity", "Runtime status unavailable."),
        )
    with activity_cols[2]:
        render_activity_item(
            "Runtime",
            f"{state.get('health', 'Unknown')} | Next {runtime_details['next_scan']}",
        )

    st.markdown(
        f"""
        <div class="research-note">
            <strong>Research</strong> {html.escape(research["label"])} <span style="color:#94a3b8;">{html.escape(research["detail"])}</span>
        </div>
        """,
        unsafe_allow_html=True,
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

page = "Home"


if page == "Home":
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

    st.subheader("Portfolio")

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
        paper_30["daily_return"] = paper_30["portfolio_value"].pct_change()

        best_day = paper_30["daily_return"].max()
        worst_day = paper_30["daily_return"].min()

        rolling_peak = paper_30["portfolio_value"].cummax()
        drawdown = (paper_30["portfolio_value"] / rolling_peak) - 1
        max_drawdown = drawdown.min()

        col1, col2, col3 = responsive_columns(3)

        with col1:
            metric_card("Best Day", f"{best_day:.2%}", True)

        with col2:
            metric_card("Worst Day", f"{worst_day:.2%}")

        with col3:
            metric_card("Max Drawdown", f"{max_drawdown:.2%}")

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

    st.subheader("Current Holdings")

    if holdings.empty:
        st.info("No open holdings.")

    else:
        holdings = holdings.copy()

        holdings.columns = [
            col.lower().replace(" ", "_")
            for col in holdings.columns
        ]

        portfolio_value = broker_row["portfolio_value"]

        holdings["portfolio_weight"] = (
            holdings["market_value"] / portfolio_value * 100
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
                        broker_row["cash"]
                        / broker_row["portfolio_value"]
                        * 100,
                        2,
                    ),
                    "unrealised_pnl": 0,
                }
            ]
        )

        holdings = pd.concat(
            [holdings, cash_row],
            ignore_index=True,
        )

        holdings = holdings.sort_values(
            "market_value",
            ascending=False,
        )

        display_holdings = holdings[
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

    st.divider()

    st.subheader("Current Signals")

    if signals.empty:
        st.info("No signal report available.")
    else:
        responsive_table(
            signals,
            hide_index=False,
        )

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

    st.subheader("Signals")

    if signals.empty:
        st.info("No signals available yet.")

    else:
        signals = signals.copy()

        signals.columns = [
            col.lower().replace(" ", "_")
            for col in signals.columns
        ]

        required_signal_cols = [
            "date",
            "ticker",
            "signal",
            "weight",
            "status",
        ]

        for col in required_signal_cols:
            if col not in signals.columns:
                signals[col] = ""

        display_signals = signals[
            required_signal_cols
        ].rename(
            columns={
                "date": "Date",
                "ticker": "Ticker",
                "signal": "Signal",
                "weight": "Weight",
                "status": "Status",
            }
        )

        responsive_table(
            display_signals,
            hide_index=True,
        )

    st.divider()

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
