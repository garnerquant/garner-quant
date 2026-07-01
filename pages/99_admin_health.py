from pathlib import Path
import subprocess
import json
import html

import pandas as pd
import streamlit as st

from execution.live_market_monitor import (
    get_market_status,
    load_monitor_runtime,
    load_monitor_snapshot,
    run_live_market_monitor,
    save_monitor_runtime,
)
from runtime.live_runtime import (
    MARKET_SESSIONS,
    get_last_cycle,
    get_recent_cycles,
    get_runtime_statistics,
)
from notifications.alert_notifier import (
    notification_status,
    notify_alerts,
    notify_trade_event,
)
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)
from ui.auto_refresh import enable_auto_refresh
from ui.runtime_status import (
    freshness_for_timestamp,
    load_runtime_status,
    runtime_freshness,
    runtime_state,
)


FILES = [
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
    "trade_audit_trail.csv",
    "trade_snapshots.csv",
    "trade_analytics_v3.csv",
    "paper_30_day_tracker.csv",
    "portfolio_v2.csv",
    "signal_report_v2.csv",
]

HEALTHY = "Healthy"
INFO = "Info"
WARNING = "Warning"
CRITICAL = "Critical"

STATUS_LABELS = {
    HEALTHY: "🟢 Healthy",
    INFO: "🔵 Info",
    WARNING: "🟠 Warning",
    CRITICAL: "🔴 Critical",
}


st.set_page_config(
    page_title="Admin / System Health | Garner Quant",
    page_icon="⚙️",
    layout="wide",
)

apply_responsive_styles()
auto_refresh = enable_auto_refresh(
    interval_seconds=30,
    key="admin_health_auto_refresh",
)


def load_csv(filename):
    path = Path(filename)

    if not path.exists():
        return pd.DataFrame(), None

    try:
        return pd.read_csv(path), None
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), "File is empty"
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def load_json_file(filename):
    path = Path(filename)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def file_mtime(filename):
    path = Path(filename)

    if not path.exists():
        return ""

    return pd.Timestamp.fromtimestamp(path.stat().st_mtime)


def display_time(value):
    if value == "" or pd.isna(value):
        return ""

    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def age_label(value):
    if value == "" or pd.isna(value):
        return "Unavailable"

    seconds = max(
        0,
        int((pd.Timestamp.now() - pd.Timestamp(value)).total_seconds()),
    )

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"

    hours = minutes // 60
    if hours < 48:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"

    days = hours // 24
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} ago"


def format_age(value):
    return freshness_for_timestamp(value)["age"]


def freshness_badge(value):
    freshness = freshness_for_timestamp(value)
    return freshness["badge"], freshness["level"]


def parse_timestamp(value):
    if value is None or value == "":
        return None

    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Europe/London")

    return timestamp.tz_convert("Europe/London")


def countdown_label(next_refresh, now):
    if next_refresh is None:
        return "Unavailable"

    seconds = int((next_refresh - now).total_seconds())

    if seconds <= 0:
        return "due now"

    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


MARKET_DISPLAY = {
    "LSE": ("🇬🇧 London", "London Stock Exchange"),
    "US": ("🇺🇸 New York", "US Market"),
    "TSE": ("🇯🇵 Tokyo", "Tokyo Stock Exchange"),
}


def safe_list(value):
    return value if isinstance(value, list) else []


def format_time_value(value):
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "None"

    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def format_runtime_duration(seconds):
    seconds = max(0, int(seconds or 0))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def runtime_uptime_label(runtime_status):
    if runtime_status.get("status") != "running":
        return "Stopped"

    started_at = parse_timestamp(runtime_status.get("started_at"))
    if started_at is None:
        return "Unavailable"

    now = pd.Timestamp.now(tz="Europe/London")
    return format_runtime_duration((now - started_at).total_seconds())


def heartbeat_status(runtime_status):
    heartbeat = runtime_state(runtime_status)["heartbeat"]
    return heartbeat.get("display", heartbeat.get("label", "Unknown")), bool(
        heartbeat.get("healthy", False)
    )


def heartbeat_age_label(runtime_status):
    return runtime_state(runtime_status)["heartbeat"]["age"]


def runtime_banner_state(runtime_status, heartbeat_ok):
    state = runtime_state(runtime_status)

    if state["level"] == "error":
        return "error", "Runtime Error", state["last_error"] or "Runtime reported an error."

    if state["running"]:
        return state["level"], "Runtime Running", state["health"]

    return "offline", "Runtime Offline", "Background runtime is not running."


def market_countdown(market):
    session = MARKET_SESSIONS.get(market)
    if not session:
        return "Unknown", "Unavailable"

    local_now = pd.Timestamp.now(tz=session["timezone"])
    open_time = session["open"]
    close_time = session["close"]

    open_dt = local_now.normalize().replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )
    close_dt = local_now.normalize().replace(
        hour=close_time.hour,
        minute=close_time.minute,
        second=0,
        microsecond=0,
    )

    is_weekday = local_now.weekday() < 5
    is_open = is_weekday and open_dt <= local_now <= close_dt

    if is_open:
        seconds = (close_dt - local_now).total_seconds()
        return "Open", f"Closes in {format_runtime_duration(seconds)}"

    next_open = open_dt
    if not is_weekday or local_now >= open_dt:
        next_open = next_open + pd.Timedelta(days=1)

    while next_open.weekday() >= 5:
        next_open = next_open + pd.Timedelta(days=1)

    seconds = (next_open - local_now).total_seconds()
    return "Closed", f"Opens in {format_runtime_duration(seconds)}"


def seconds_until_market_open(market):
    session = MARKET_SESSIONS.get(market)
    if not session:
        return None

    local_now = pd.Timestamp.now(tz=session["timezone"])
    open_time = session["open"]
    close_time = session["close"]
    open_dt = local_now.normalize().replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )
    close_dt = local_now.normalize().replace(
        hour=close_time.hour,
        minute=close_time.minute,
        second=0,
        microsecond=0,
    )

    if local_now.weekday() < 5 and open_dt <= local_now <= close_dt:
        return 0

    next_open = open_dt
    if local_now.weekday() >= 5 or local_now >= open_dt:
        next_open = next_open + pd.Timedelta(days=1)

    while next_open.weekday() >= 5:
        next_open = next_open + pd.Timedelta(days=1)

    return max(0, int((next_open - local_now).total_seconds()))


def next_market_to_open(markets):
    candidates = []
    for market in markets:
        seconds = seconds_until_market_open(market)
        if seconds is not None and seconds > 0:
            candidates.append((seconds, market))

    if not candidates:
        return "None"

    seconds, market = min(candidates)
    name = MARKET_DISPLAY.get(market, (market, market))[0]
    return f"{name}: Opens in {format_runtime_duration(seconds)}"


def next_market_details(markets):
    candidates = []
    for market in markets:
        seconds = seconds_until_market_open(market)
        if seconds is not None and seconds > 0:
            candidates.append((seconds, market))

    if not candidates:
        return "None", None

    seconds, market = min(candidates)
    name = MARKET_DISPLAY.get(market, (market, market))[0]
    return name, seconds


def market_session_time(market):
    session = MARKET_SESSIONS.get(market)
    if not session:
        return "Session unavailable"

    return (
        f"{session['open'].strftime('%H:%M')} - "
        f"{session['close'].strftime('%H:%M')} "
        f"{session['timezone']}"
    )


def next_cycle_value(runtime_status):
    return runtime_state(runtime_status)["next_cycle"]["time"]


def next_cycle_delta(runtime_status):
    return runtime_state(runtime_status)["next_cycle"]["delta"]


def next_cycle_clock_label(runtime_status):
    return runtime_state(runtime_status)["next_scan_display"]


def paper_execution_enabled(runtime_status, runtime_config):
    return bool(
        runtime_status.get("paper_execution_enabled")
        or runtime_config.get("paper_execution_enabled")
    )


def activity_state(runtime_status, runtime_config, heartbeat_ok, markets):
    state = runtime_state(runtime_status)
    markets_open = safe_list(runtime_status.get("markets_open"))
    next_market_name, next_market_seconds = next_market_details(markets)

    if state["level"] == "error":
        return {
            "level": "error",
            "title": "Runtime Error",
            "current_activity": state["activity"],
            "next_label": "Last Error",
            "next_value": state["last_error"] or "Unknown runtime error.",
            "command": None,
        }

    if not state["running"]:
        return {
            "level": "offline",
            "title": "Runtime Offline",
            "current_activity": state["activity"],
            "next_label": "Next Action",
            "next_value": "Start runtime from PowerShell.",
            "command": "python runtime/live_runtime.py",
        }

    if not markets_open:
        next_market_text = (
            f"{next_market_name} opens in {format_runtime_duration(next_market_seconds)}"
            if next_market_seconds is not None
            else "No configured market is scheduled."
        )
        return {
            "level": "waiting",
            "title": "Runtime Running",
            "current_activity": state["activity"],
            "next_label": "Next Market",
            "next_value": next_market_text,
            "command": None,
        }

    return {
        "level": state["level"],
        "title": "Runtime Running",
        "current_activity": state["activity"],
        "next_label": "Next Cycle",
        "next_value": next_cycle_clock_label(runtime_status),
        "command": None,
    }


def what_happens_next_text(
    runtime_status,
    runtime_config,
    notification_health,
    markets,
):
    status = runtime_status.get("status", "not started")
    mode = runtime_status.get("mode") or runtime_config.get("mode") or "monitor_only"
    active_markets = safe_list(runtime_status.get("markets_open"))
    paper_enabled = paper_execution_enabled(runtime_status, runtime_config)
    telegram_ready = bool(notification_health.get("telegram_configured"))
    next_market_name, next_market_seconds = next_market_details(markets)
    next_cycle = next_cycle_value(runtime_status)

    if status == "error":
        return (
            "Garner Quant needs attention before relying on live runtime. "
            "Review the last error and restart the runtime when fixed."
        )

    if status != "running":
        return (
            "Garner Quant is not running. Start the runtime from PowerShell "
            "when you want independent live monitoring."
        )

    market_phrase = (
        f"watching {', '.join(active_markets)}"
        if active_markets
        else (
            f"waiting for {next_market_name} to open in "
            f"{format_runtime_duration(next_market_seconds)}"
            if next_market_seconds is not None
            else "waiting for the next configured market"
        )
    )
    execution_phrase = (
        "Paper execution is enabled."
        if paper_enabled and mode == "paper_execution"
        else "Paper execution is disabled, so it will only monitor prices and send paper alerts."
    )
    notification_phrase = (
        "Telegram notifications are ready."
        if telegram_ready
        else "Telegram is not configured, so notifications will use fallback logging."
    )

    return (
        f"Garner Quant is currently {market_phrase}. It will check again at "
        f"{next_cycle}. {execution_phrase} {notification_phrase}"
    )


def render_activity_panel(activity, runtime_status):
    color = {
        "live": "#0f7b3f",
        "waiting": "#9a6b00",
        "error": "#b42318",
        "offline": "#b42318",
    }.get(activity["level"], "#175cd3")
    background = {
        "live": "#ecfdf3",
        "waiting": "#fffaeb",
        "error": "#fef3f2",
        "offline": "#fef3f2",
    }.get(activity["level"], "#eff8ff")
    command = activity.get("command")
    command_html = (
        "<div style='margin-top:12px;font-size:0.95rem;'>"
        "<strong>Command:</strong> "
        f"<code>{html.escape(command)}</code></div>"
        if command
        else ""
    )
    next_cycle = next_cycle_delta(runtime_status)

    st.markdown(
        f"""
        <div style="
            border:1px solid {color};
            border-left:8px solid {color};
            background:{background};
            padding:22px 24px;
            border-radius:8px;
            margin:8px 0 16px 0;">
            <div style="font-size:1.8rem;font-weight:700;color:{color};">
                {html.escape(activity["title"])}
            </div>
            <div style="margin-top:14px;font-size:1.05rem;">
                <strong>Current Activity:</strong><br>
                {html.escape(activity["current_activity"])}
            </div>
            <div style="margin-top:12px;font-size:1.05rem;">
                <strong>{html.escape(activity["next_label"])}:</strong><br>
                {html.escape(activity["next_value"])}
            </div>
            <div style="margin-top:12px;font-size:0.95rem;color:#475467;">
                <strong>Next Runtime Cycle:</strong> {html.escape(next_cycle)}
            </div>
            {command_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_live_event_feed(cycles, limit=20):
    events = []
    for cycle in cycles:
        cycle_events = safe_list(cycle.get("events"))
        if cycle_events:
            for event in reversed(cycle_events):
                severity = event.get("severity", "info")
                events.append(
                    {
                        "Time": format_time_value(event.get("timestamp")),
                        "Icon": {
                            "error": "ðŸ”´",
                            "warning": "ðŸŸ¡",
                            "info": "âœ…",
                        }.get(severity, "âœ…"),
                        "Event": event.get("type", "Runtime Event"),
                        "Explanation": event.get("message", ""),
                    }
                )

                if len(events) >= limit:
                    return events[:limit]

            continue

        event_time = format_time_value(cycle.get("finished_at"))
        status = cycle.get("status", "unknown")
        markets_checked = safe_list(cycle.get("markets_checked"))
        markets_open = safe_list(cycle.get("markets_open"))
        holdings_monitored = int(cycle.get("holdings_monitored", 0) or 0)
        alerts_found = int(cycle.get("alerts_found", 0) or 0)

        if markets_checked:
            events.append(
                {
                    "Time": event_time,
                    "Icon": "✅" if status == "success" else "🔴",
                    "Event": "Cycle Complete",
                    "Explanation": (
                        f"Checked {', '.join(markets_checked)}. "
                        f"{', '.join(markets_open)} open."
                        if markets_open
                        else f"Checked {', '.join(markets_checked)}. No markets were open."
                    ),
                }
            )

        if not markets_open:
            events.append(
                {
                    "Time": event_time,
                    "Icon": "🟡",
                    "Event": "Waiting",
                    "Explanation": "No markets currently open.",
                }
            )

        events.append(
            {
                "Time": event_time,
                "Icon": "📡",
                "Event": "Monitor",
                "Explanation": (
                    f"{holdings_monitored} holdings monitored. "
                    f"{alerts_found} alerts found."
                ),
            }
        )

        if cycle.get("paper_execution_attempted"):
            events.append(
                {
                    "Time": event_time,
                    "Icon": "🧾",
                    "Event": "Strategy executed",
                    "Explanation": (
                        "Paper execution completed"
                        if cycle.get("paper_execution_completed")
                        else "Paper execution attempted"
                    ),
                }
            )

        trades_recorded = int(cycle.get("trades_recorded", 0) or 0)
        if trades_recorded:
            events.append(
                {
                    "Time": event_time,
                    "Icon": "🧾",
                    "Event": "Paper Trade",
                    "Explanation": f"{trades_recorded} paper trades recorded.",
                }
            )

        notifications_sent = int(cycle.get("notifications_sent", 0) or 0)
        if notifications_sent:
            events.append(
                {
                    "Time": event_time,
                    "Icon": "🔔",
                    "Event": "Notification",
                    "Explanation": f"{notifications_sent} alert notifications sent.",
                }
            )

        events.append(
            {
                "Time": event_time,
                "Icon": "✅" if status == "success" else "🔴",
                "Event": "Cycle Complete" if status == "success" else "Cycle Error",
                "Explanation": (
                    cycle.get("cycle_summary")
                    or "Runtime cycle finished."
                ),
            }
        )

        if len(events) >= limit:
            break

    return events[:limit]


def empty_notification_summary():
    return {
        "sent": 0,
        "skipped": 0,
        "errors": [],
        "last_notification_sent": None,
        "notifications_sent_today": 0,
        "skipped_due_to_cooldown": 0,
        "skipped_due_to_deduplication": 0,
    }


def format_reason_counts(reason_counts):
    if not reason_counts:
        return "None"

    return ", ".join(
        f"{reason}: {count}"
        for reason, count in reason_counts.items()
    )


def build_decision_trace_rows(decisions):
    rows = []
    for decision in decisions:
        rows.append(
            {
                "Ticker": decision.get("ticker"),
                "Signal": decision.get("signal"),
                "Holding?": "Yes" if decision.get("current_holding") else "No",
                "Target Weight": decision.get("target_weight"),
                "Current Weight": decision.get("current_weight"),
                "Decision": decision.get("portfolio_decision"),
                "Reason": decision.get("reason"),
            }
        )
    return rows


def short_time(value):
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "Unavailable"
    return timestamp.strftime("%H:%M:%S")


def human_age(value):
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "Unavailable"

    now = pd.Timestamp.now(tz="Europe/London")
    return f"{format_runtime_duration((now - timestamp).total_seconds())} ago"


def next_scan_label(runtime_status):
    return runtime_state(runtime_status)["next_scan_display"]


def market_is_open(market):
    return market_countdown(market)[0] == "Open"


def market_badge(label, market):
    return {
        "label": label,
        "status": "OPEN" if market_is_open(market) else "CLOSED",
        "healthy": market_is_open(market),
    }


def expand_market_names(markets):
    names = []
    for market in safe_list(markets):
        if market == "LSE":
            names.append("London")
        elif market == "US":
            names.extend(["NYSE", "NASDAQ"])
        elif market == "TSE":
            names.append("Tokyo")
        else:
            names.append(str(market))
    return names


def render_market_banner(configured_markets):
    markets = [
        market_badge("LSE", "LSE"),
        market_badge("NYSE", "US"),
        market_badge("NASDAQ", "US"),
        market_badge("Tokyo", "TSE"),
    ]
    cols = responsive_columns(4)
    for index, market in enumerate(markets):
        icon = "🟢" if market["healthy"] else "🔴"
        cols[index].metric(market["label"], f"{icon} {market['status']}")

    st.caption(f"Next Market: {next_market_to_open(configured_markets)}")


def latest_successful_cycle(cycles):
    for cycle in cycles:
        if cycle.get("status") == "success":
            return cycle
    return None


def latest_notification_label():
    state = load_json_file("data/notification_state.json")
    sent_log = safe_list(state.get("sent_log"))
    if not sent_log:
        return "No notification sent today", "", ""

    today = pd.Timestamp.now(tz="Europe/London").date()
    for row in reversed(sent_log):
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None or timestamp.date() != today:
            continue
        if row.get("type") == "trade_event":
            return (
                str(row.get("action", "TRADE")).upper(),
                str(row.get("ticker", "Unknown")),
                timestamp.strftime("%H:%M"),
            )
        return (
            str(row.get("alert_type", "ALERT")),
            str(row.get("ticker", "Unknown")),
            timestamp.strftime("%H:%M"),
        )

    return "No notification sent today", "", ""


def telegram_panel_state(notification_health):
    state = notification_state()
    sent_today = [
        row
        for row in safe_list(state.get("sent_log"))
        if parse_timestamp(row.get("timestamp")) is not None
        and parse_timestamp(row.get("timestamp")).date() == today_london_date()
    ]
    has_channel_delivery = any(row.get("delivery") == "channel" for row in sent_today)
    has_fallback_delivery = any(row.get("delivery") == "fallback" for row in sent_today)

    if notification_health.get("telegram_configured"):
        return "Telegram Connected", "Latest message"
    if has_fallback_delivery and not has_channel_delivery:
        return "Telegram Fallback Only", "Notifications are being logged but not sent"
    return "Telegram Not Configured", "No live Telegram delivery available"


def notification_state():
    return load_json_file("data/notification_state.json")


def today_london_date():
    return pd.Timestamp.now(tz="Europe/London").date()


def trade_datetime(row):
    timestamp = row.get("timestamp")
    if timestamp:
        parsed = parse_timestamp(timestamp)
        if parsed is not None:
            return parsed

    date_value = row.get("date")
    time_value = row.get("time")
    if date_value is None:
        return None

    date_text = str(date_value).strip()
    time_text = str(time_value or "").strip()
    date_parsed = pd.to_datetime(date_text, errors="coerce")
    if pd.isna(date_parsed):
        return None

    if time_text:
        parsed = pd.to_datetime(
            f"{date_parsed.strftime('%Y-%m-%d')} {time_text}",
            errors="coerce",
        )
    else:
        parsed = date_parsed

    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize("Europe/London")


def is_today_trade(row):
    timestamp = trade_datetime(row)
    return timestamp is not None and timestamp.date() == today_london_date()


def event_icon(event_type, severity="info"):
    if severity == "error":
        return "❌"
    if severity == "warning":
        return "⚠"
    event_type = str(event_type or "")
    if "Decision Trace" in event_type:
        return "📝"
    if "Telegram" in event_type or "Notification" in event_type:
        return "🔔"
    if "Portfolio" in event_type or "Trade" in event_type:
        return "💼"
    if "Signal" in event_type or "Strategy" in event_type or "Downloaded" in event_type:
        return "📈"
    return "▶"


def event_label(event):
    event_type = event.get("type", "Runtime Event")
    details = event.get("details") or {}
    if event_type == "Generated Signals":
        total = (
            int(details.get("buy_signals", 0) or 0)
            + int(details.get("sell_signals", 0) or 0)
            + int(details.get("hold_signals", 0) or 0)
        )
        return f"Generated {total} signals"
    if event_type == "Paper Portfolio Updated":
        trades = int(details.get("paper_trades", 0) or 0)
        return f"Portfolio {'changed' if trades else 'unchanged'}"
    if event_type == "Decision Trace Created":
        return "Decision Trace created"
    if event_type == "Runtime Sleeping":
        return "Sleeping until next cycle"
    return event.get("message") or event_type


def build_timeline_rows(cycles, runtime_status, limit=12):
    rows = []
    for cycle in cycles:
        for event in reversed(safe_list(cycle.get("events"))):
            rows.append(
                {
                    "Time": short_time(event.get("timestamp")),
                    "": event_icon(event.get("type"), event.get("severity", "info")),
                    "Activity": event_label(event),
                    "Stage": event.get("type", "Runtime Event"),
                }
            )
            if len(rows) >= limit:
                return rows

        if not safe_list(cycle.get("events")):
            rows.append(
                {
                    "Time": short_time(cycle.get("finished_at")),
                    "": "▶",
                    "Activity": cycle.get("cycle_summary") or "Runtime cycle finished",
                    "Stage": cycle.get("status", "cycle"),
                }
            )

    if runtime_status.get("next_cycle_at"):
        rows.append(
            {
                "Time": next_cycle_clock_label(runtime_status),
                "": "▶",
                "Activity": f"Sleeping until {next_cycle_clock_label(runtime_status)}",
                "Stage": "Next Cycle",
            }
        )
    return rows[:limit]


def health_item(
    label,
    ok,
    healthy_text="Healthy",
    bad_text="Needs attention",
    bad_level="red",
):
    if ok:
        return {"Check": label, "Status": f"🟢 {healthy_text}"}
    icon = "🟡" if bad_level == "yellow" else "🔴"
    return {"Check": label, "Status": f"{icon} {bad_text}"}


def heartbeat_health_item(runtime_status):
    heartbeat = runtime_state(runtime_status)["heartbeat"]
    if heartbeat.get("level") == "overdue":
        return {"Check": "Heartbeat", "Status": "🔴 Overdue"}
    if heartbeat.get("level") == "delayed":
        return {"Check": "Heartbeat", "Status": "🟡 Delayed"}
    if heartbeat.get("level") == "missing":
        return {"Check": "Heartbeat", "Status": "🔴 Missing"}
    return {"Check": "Heartbeat", "Status": f"🟢 {heartbeat.get('label', 'Healthy')}"}


def operator_summary(
    runtime_status,
    runtime_config,
    heartbeat_ok,
    markets,
    execution_summary,
    notification_health,
):
    state = runtime_state(runtime_status)
    if not state["running"]:
        if state["level"] == "error":
            return "Garner Quant needs attention. Review the latest runtime error."
        return "Garner Quant is offline. Start the runtime before relying on live status."

    if not state["healthy"]:
        return "Garner Quant is running, but its heartbeat is stale. Check the runtime host."

    status = runtime_status.get("status")
    active_markets = safe_list(runtime_status.get("markets_open"))
    trades = int(execution_summary.get("paper_trades", 0) or 0)
    trace_count = int(execution_summary.get("decision_trace_count", 0) or 0)
    notifications = int(notification_health.get("notifications_sent_today", 0) or 0)

    if not active_markets:
        next_name, next_seconds = next_market_details(markets)
        if next_seconds is not None:
            return f"Runtime is waiting for {next_name} to open in {format_runtime_duration(next_seconds)}."
        return "Runtime is waiting for the next configured market session."

    if trades:
        return f"Garner Quant executed {trades} paper trade{'s' if trades != 1 else ''} and notified Telegram."

    if trace_count:
        return "Garner Quant is monitoring live markets. The latest strategy completed successfully with no portfolio changes required."

    return "Garner Quant is monitoring live markets and waiting for the next strategy scan."


def meaningful_strategy_summary(summary):
    if not isinstance(summary, dict) or not summary:
        return False

    signal_fields = [
        "symbols_scanned",
        "buy_signals",
        "sell_signals",
        "hold_signals",
        "paper_trades",
        "trades_recorded",
        "decision_trace_count",
    ]
    return any(float(summary.get(field, 0) or 0) > 0 for field in signal_fields)


def latest_completed_execution_summary(current_summary):
    if meaningful_strategy_summary(current_summary):
        return current_summary, "runtime_status"

    execution_log = load_json_file("data/live_runtime_execution_log.json")
    executions = safe_list(execution_log.get("executions"))
    for execution in reversed(executions):
        if execution.get("status") != "success":
            continue
        if meaningful_strategy_summary(execution):
            return execution, "execution_log"

    return current_summary or {}, "runtime_status"


def runtime_status_sentence(
    runtime_status,
    strategy_summary,
    today_trade_rows,
    notification_health,
):
    state = runtime_state(runtime_status)
    if not state["running"]:
        if state["level"] == "error":
            return "Garner Quant needs attention. The runtime reported an error."
        return "Garner Quant is offline. Start the runtime before relying on live status."

    stage = mission_stage(runtime_status)
    markets = expand_market_names(runtime_status.get("markets_open"))
    market_text = ", ".join(markets) if markets else "configured markets"
    next_cycle = next_cycle_clock_label(runtime_status)

    if today_trade_rows:
        latest = today_trade_rows[-1]
        action = str(latest.get("action", "trade")).upper()
        ticker = latest.get("ticker", "Unknown")
        delivery = latest.get("telegram_status", "No/Unknown")
        return (
            f"Garner Quant executed one {action} trade in {ticker} today "
            f"and logged Telegram delivery as {delivery.lower()}."
        )

    if stage == "Sleep":
        return (
            "Garner Quant completed its latest strategy run successfully "
            f"and is sleeping until {next_cycle}."
        )

    if stage in {"Paper Execution", "Portfolio Decision", "Signal Generation", "Price Download"}:
        return f"Garner Quant is currently processing {stage.lower()} for {market_text}."

    if meaningful_strategy_summary(strategy_summary):
        return (
            "Garner Quant completed the latest strategy run with "
            f"{int(strategy_summary.get('paper_trades', strategy_summary.get('trades_recorded', 0)) or 0)} "
            "portfolio changes."
        )

    return f"Garner Quant is monitoring {market_text} and waiting for the next scan."


def mission_stage(runtime_status):
    return runtime_state(runtime_status)["display_stage"]


def pipeline_state(stage, current_stage):
    stages = [
        "Market Check",
        "Price Download",
        "Signal Generation",
        "Portfolio Decision",
        "Paper Execution",
        "Telegram",
        "Sleep",
    ]
    try:
        current_index = stages.index(current_stage)
    except ValueError:
        current_index = len(stages) - 1

    index = stages.index(stage)
    if index < current_index:
        return "complete"
    if index == current_index:
        return "current"
    return "future"


def inject_mission_control_css():
    st.markdown(
        """
        <style>
        .gq-hero {
            border: 1px solid rgba(125, 211, 252, 0.42);
            border-left: 8px solid #22c55e;
            border-radius: 8px;
            padding: 1.15rem;
            background: linear-gradient(135deg, rgba(15,23,42,0.96), rgba(17,24,39,0.92));
            color: #f8fafc;
            margin: 0.25rem 0 1rem 0;
        }
        .gq-hero-title {
            font-size: 1.65rem;
            font-weight: 800;
            letter-spacing: 0;
            margin-bottom: 0.65rem;
        }
        .gq-hero-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
        }
        .gq-hero-item, .gq-card {
            border: 1px solid rgba(148,163,184,0.24);
            border-radius: 8px;
            padding: 0.85rem;
            background: rgba(255,255,255,0.04);
        }
        .gq-label {
            color: #cbd5e1;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0;
            margin-bottom: 0.3rem;
        }
        .gq-value {
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .gq-pipeline {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.45rem;
            margin: 0.35rem 0 1rem 0;
        }
        .gq-stage {
            border-radius: 8px;
            padding: 0.72rem 0.58rem;
            text-align: center;
            border: 1px solid rgba(148,163,184,0.25);
            min-height: 4.2rem;
            font-size: 0.86rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .gq-stage.complete { background: rgba(34,197,94,0.16); border-color: rgba(34,197,94,0.55); }
        .gq-stage.current { background: rgba(59,130,246,0.2); border-color: rgba(59,130,246,0.7); font-weight: 800; }
        .gq-stage.future { background: rgba(148,163,184,0.08); color: #94a3b8; }
        .gq-health-grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 0.55rem;
            margin-bottom: 1rem;
        }
        .gq-health {
            border-radius: 8px;
            padding: 0.8rem;
            border: 1px solid rgba(148,163,184,0.25);
            font-weight: 700;
        }
        .gq-health.green { background: rgba(34,197,94,0.12); border-color: rgba(34,197,94,0.5); }
        .gq-health.yellow { background: rgba(234,179,8,0.12); border-color: rgba(234,179,8,0.55); }
        .gq-health.red { background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.55); }
        .gq-performance-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.55rem;
            margin: 0.25rem 0 1rem 0;
        }
        .gq-performance {
            border-radius: 8px;
            padding: 0.85rem;
            border: 1px solid rgba(148,163,184,0.25);
            background: rgba(255,255,255,0.03);
        }
        .gq-performance.positive { color:#22c55e; border-color: rgba(34,197,94,0.45); }
        .gq-performance.negative { color:#ef4444; border-color: rgba(239,68,68,0.45); }
        .gq-performance.neutral { color:#e5e7eb; }
        .gq-freshness-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.4rem 0 0.75rem 0;
        }
        .gq-freshness {
            border-radius: 8px;
            padding: 0.85rem;
            border: 1px solid rgba(148,163,184,0.28);
            background: rgba(255,255,255,0.035);
        }
        .gq-freshness.live, .gq-freshness.recent {
            border-color: rgba(34,197,94,0.55);
        }
        .gq-freshness.slightly-stale {
            border-color: rgba(234,179,8,0.6);
        }
        .gq-freshness.stale {
            border-color: rgba(249,115,22,0.65);
        }
        .gq-freshness.very-stale {
            border-color: rgba(239,68,68,0.65);
        }
        .gq-freshness.missing {
            border-color: rgba(148,163,184,0.35);
            opacity: 0.78;
        }
        .gq-badge-buy { color:#166534; background:#dcfce7; padding:0.15rem 0.45rem; border-radius:999px; font-weight:700; }
        .gq-badge-sell { color:#991b1b; background:#fee2e2; padding:0.15rem 0.45rem; border-radius:999px; font-weight:700; }
        .gq-badge-traded { color:#1d4ed8; background:#dbeafe; padding:0.15rem 0.45rem; border-radius:999px; font-weight:700; }
        .gq-badge-neutral { color:#374151; background:#e5e7eb; padding:0.15rem 0.45rem; border-radius:999px; font-weight:700; }
        @media (max-width: 900px) {
            .gq-hero-grid, .gq-pipeline, .gq-health-grid, .gq-performance-grid, .gq-freshness-grid {
                grid-template-columns: 1fr;
            }
            .gq-hero-title {
                font-size: 1.3rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero_status(runtime_status, runtime_config, heartbeat_ok, markets_open):
    state = runtime_state(runtime_status)
    current_stage = mission_stage(runtime_status)
    raw_stage = state["stage"]
    live_label = state["banner"]
    markets = " • ".join(expand_market_names(markets_open)) if markets_open else "No markets open"
    mode = (
        runtime_status.get("mode")
        or runtime_config.get("mode")
        or "monitor_only"
    ).replace("_", " ").title()
    if state["running"]:
        live_label = state["banner"]
    elif state["level"] == "error":
        live_label = "Garner Quant Needs Attention"
    else:
        live_label = "Garner Quant Offline"
    health = f"Runtime {state['health']}"
    st.markdown(
        f"""
        <div class="gq-hero">
            <div class="gq-hero-title">{html.escape(live_label)}</div>
            <div style="font-size:2.15rem;font-weight:900;line-height:1.1;margin-bottom:0.85rem;">
                {html.escape(current_stage)}
            </div>
            <div class="gq-hero-grid">
                <div class="gq-hero-item"><div class="gq-label">Mode</div><div class="gq-value">{html.escape(mode)}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Next Scan</div><div class="gq-value" style="font-size:1.35rem;">{html.escape(next_scan_label(runtime_status))}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Health</div><div class="gq-value">{html.escape(health)}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Markets Open</div><div class="gq-value">{html.escape(markets)}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Last Cycle</div><div class="gq-value">{html.escape(short_time(runtime_status.get("last_cycle_at")))}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Next Cycle</div><div class="gq-value">{html.escape(next_cycle_clock_label(runtime_status))}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Heartbeat</div><div class="gq-value">{html.escape(heartbeat_status(runtime_status)[0])}</div></div>
                <div class="gq-hero-item"><div class="gq-label">Current Stage</div><div class="gq-value">{html.escape(raw_stage)}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return state["stage"]


def render_pipeline(current_stage):
    stages = [
        "Market Check",
        "Price Download",
        "Signal Generation",
        "Portfolio Decision",
        "Paper Execution",
        "Telegram",
        "Sleep",
    ]
    html_parts = ['<div class="gq-pipeline">']
    for stage in stages:
        state = pipeline_state(stage, current_stage)
        prefix = "✓ " if state == "complete" else "● " if state == "current" else ""
        html_parts.append(
            f'<div class="gq-stage {state}">{html.escape(prefix + stage)}</div>'
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def health_card_rows(health_rows):
    cards = ['<div class="gq-health-grid">']
    for row in health_rows:
        status = row.get("Status", "")
        if "🔴" in status or "ðŸ”´" in status:
            color = "red"
        elif "🟡" in status or "ðŸŸ¡" in status:
            color = "yellow"
        else:
            color = "green"
        cards.append(
            f'<div class="gq-health {color}"><div class="gq-label">{html.escape(row.get("Check", ""))}</div>'
            f'<div>{html.escape(status)}</div></div>'
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)


def value_class(value):
    text = str(value).replace("%", "").replace(",", "").replace("£", "").strip()
    try:
        numeric = float(text)
    except ValueError:
        return "neutral"
    if numeric > 0:
        return "positive"
    if numeric < 0:
        return "negative"
    return "neutral"


def safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def money_label(value):
    numeric = safe_float(value)
    if numeric is None:
        return "Unavailable"
    return f"£{numeric:,.2f}"


def price_label(value):
    numeric = safe_float(value)
    if numeric is None:
        return "Unavailable"
    return f"£{numeric:,.2f}"


def percent_label(value):
    numeric = safe_float(value)
    if numeric is None:
        return "Unavailable"
    return f"{numeric * 100:.2f}%"


def render_performance_strip(items):
    cards = ['<div class="gq-performance-grid">']
    for label, value in items:
        css_class = value_class(value)
        cards.append(
            f'<div class="gq-performance {css_class}"><div class="gq-label">{html.escape(label)}</div>'
            f'<div class="gq-value">{html.escape(str(value))}</div></div>'
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)


def data_freshness_items(runtime_status=None):
    files = [
        ("Runtime Status", "data/live_runtime_status.json"),
        ("Execution Log", "data/live_runtime_execution_log.json"),
        ("Trade Journal", "trade_journal_v3.csv"),
        ("Portfolio", "paper_portfolio_v3.csv"),
        ("Decision Trace", "data/runtime_decision_trace.json"),
        ("Telegram Notifications", "data/notification_state.json"),
        ("Market Intelligence", "data/market_intelligence.json"),
    ]
    items = []
    for label, filename in files:
        if label == "Runtime Status":
            freshness = runtime_freshness(runtime_status or {})
            modified_at = freshness["timestamp"]
            badge = freshness["badge"]
            level = freshness["level"]
            age = freshness["age"]
        else:
            modified_at = file_mtime(filename)
            badge, level = freshness_badge(modified_at)
            age = format_age(modified_at)
        items.append(
            {
                "label": label,
                "filename": filename,
                "modified_at": modified_at,
                "age": age,
                "badge": badge,
                "level": level,
            }
        )
    return items


def data_freshness_summary(items):
    levels = [item["level"] for item in items]
    if any(level == "missing" for level in levels):
        return "Some runtime data files are missing."
    if any(level in {"stale", "very-stale"} for level in levels):
        return "Runtime appears inactive."
    if any(level == "slightly-stale" for level in levels):
        return "Some runtime data appears stale."
    return "All runtime data is current."


def render_data_freshness_card(items):
    cards = ['<div class="gq-freshness-grid">']
    for item in items:
        age_text = (
            "Not found"
            if item["level"] == "missing"
            else f"Updated {item['age']}"
        )
        cards.append(
            f'<div class="gq-freshness {html.escape(item["level"])}">'
            f'<div class="gq-label">{html.escape(item["label"])}</div>'
            f'<div class="gq-value">{html.escape(age_text)}</div>'
            f'<div style="margin-top:0.35rem;font-weight:700;">{html.escape(item["badge"])}</div>'
            '</div>'
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)


def market_intelligence_rows(limit=10):
    intelligence = load_json_file("data/market_intelligence.json")
    rows = []
    for item in safe_list(intelligence.get("stories"))[:limit]:
        rows.append(
            {
                "Time": short_time(item.get("published_at")),
                "Tickers": ", ".join(safe_list(item.get("matched_tickers"))) or "-",
                "Source": item.get("source") or "Unknown",
                "Headline": item.get("headline") or "Untitled",
                "Category": item.get("category") or "Market",
                "Sentiment": item.get("sentiment") or "unknown",
                "Importance": item.get("importance") or "unknown",
                "URL": item.get("url") or "",
            }
        )
    return rows, intelligence


def portfolio_exposure_rows(intelligence, limit=8):
    rows = []
    for item in safe_list(intelligence.get("portfolio_exposure"))[:limit]:
        rows.append(
            {
                "Ticker": item.get("ticker"),
                "Stories": item.get("stories_count", 0),
                "Holding": "Yes" if item.get("in_current_holdings") else "No",
                "Signal Today": "Yes" if item.get("in_todays_signals") else "No",
                "Top Importance": item.get("highest_importance", "unknown"),
            }
        )
    return rows


def top_story_rows(intelligence, limit=5):
    rows = []
    for item in safe_list(intelligence.get("top_stories"))[:limit]:
        rows.append(
            {
                "Time": short_time(item.get("published_at")),
                "Headline": item.get("headline") or "Untitled",
                "Category": item.get("category") or "Market",
                "Importance": item.get("importance") or "unknown",
                "Tickers": ", ".join(safe_list(item.get("matched_tickers"))) or "-",
            }
        )
    return rows


def macro_calendar_rows(intelligence, limit=8):
    rows = []
    calendar_items = safe_list(intelligence.get("macro_calendar"))
    if not calendar_items:
        try:
            from market_intelligence.market_calendar import macro_calendar

            calendar_items = safe_list(macro_calendar().get("events"))
        except Exception:
            calendar_items = []

    for item in calendar_items[:limit]:
        rows.append(
            {
                "Event": item.get("event"),
                "Category": item.get("category"),
                "Region": item.get("region"),
                "Importance": item.get("importance"),
            }
        )
    return rows


def market_groups():
    markets = [
        ("LSE", "LSE"),
        ("NYSE", "US"),
        ("NASDAQ", "US"),
        ("Tokyo", "TSE"),
    ]
    open_items = [label for label, market in markets if market_is_open(market)]
    closed_items = [label for label, market in markets if not market_is_open(market)]
    return open_items, closed_items


def load_transaction_log_file():
    path = Path("trade_transactions_v1.csv")
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def trade_notification_sent(row):
    return trade_notification_status(row) in {"Yes", "Fallback"}


def trade_notification_status(row):
    state = notification_state()
    sent_log = safe_list(state.get("sent_log"))
    ticker = str(row.get("ticker", ""))
    action = str(row.get("action", "")).upper()
    row_time = trade_datetime(row)
    if row_time is None:
        return "No/Unknown"

    for item in reversed(sent_log):
        if item.get("type") != "trade_event":
            continue
        if ticker and ticker != str(item.get("ticker", "")):
            continue
        if action and action != str(item.get("action", "")).upper():
            continue
        sent_time = parse_timestamp(item.get("timestamp"))
        if sent_time is None:
            continue
        if abs((sent_time - row_time).total_seconds()) <= 180:
            return "Yes" if item.get("delivery") == "channel" else "Fallback"

    return "No/Unknown"


def today_trades_from_sources(journal):
    rows = []
    if not journal.empty and "action" in journal.columns:
        for _, row in journal.iterrows():
            item = row.to_dict()
            if is_today_trade(item):
                item["source"] = "trade_journal"
                item["timestamp"] = trade_datetime(item)
                item["telegram_sent"] = trade_notification_sent(item)
                item["telegram_status"] = trade_notification_status(item)
                rows.append(item)

    if rows:
        return sorted(rows, key=lambda item: item.get("timestamp") or pd.Timestamp.min)

    transaction_log = load_transaction_log_file()
    if not transaction_log.empty and "action" in transaction_log.columns:
        for _, row in transaction_log.iterrows():
            item = row.to_dict()
            if is_today_trade(item):
                item["source"] = "transaction_log"
                item["timestamp"] = trade_datetime(item)
                item["telegram_sent"] = trade_notification_sent(item)
                item["telegram_status"] = trade_notification_status(item)
                rows.append(item)

    if rows:
        return sorted(rows, key=lambda item: item.get("timestamp") or pd.Timestamp.min)

    runtime_latest = load_runtime_status().get("latest_paper_trade")
    if isinstance(runtime_latest, dict) and is_today_trade(runtime_latest):
        runtime_latest["source"] = "runtime_status"
        runtime_latest["timestamp"] = trade_datetime(runtime_latest)
        runtime_latest["telegram_sent"] = trade_notification_sent(runtime_latest)
        runtime_latest["telegram_status"] = trade_notification_status(runtime_latest)
        rows.append(runtime_latest)

    if rows:
        return sorted(rows, key=lambda item: item.get("timestamp") or pd.Timestamp.min)

    state = notification_state()
    for row in safe_list(state.get("sent_log")):
        if row.get("type") != "trade_event":
            continue
        ticker = str(row.get("ticker", ""))
        if ticker.upper().startswith("TEST") or ticker.upper() == "BUY.L":
            continue
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None or timestamp.date() != today_london_date():
            continue
        rows.append(
            {
                "source": "notification_state",
                "timestamp": timestamp,
                "time": timestamp.strftime("%H:%M:%S"),
                "action": row.get("action"),
                "ticker": ticker,
                "price": None,
                "shares": None,
                "value": None,
                "pnl": None,
                "telegram_sent": row.get("delivery") == "channel",
                "telegram_status": "Yes" if row.get("delivery") == "channel" else "Fallback",
            }
        )
    return sorted(rows, key=lambda item: item.get("timestamp") or pd.Timestamp.min)


def latest_trade_from_journal(journal):
    trades = today_trades_from_sources(journal)
    return trades[-1] if trades else None


def portfolio_snapshot_rows(portfolio, holdings, portfolio_value):
    rows = []
    if portfolio.empty:
        return rows

    holding_lookup = {}
    if not holdings.empty and "ticker" in holdings.columns:
        holding_lookup = {
            row.get("ticker"): row
            for _, row in holdings.iterrows()
        }

    for _, row in portfolio.iterrows():
        ticker = row.get("ticker")
        holding = holding_lookup.get(ticker, {})
        market_value = holding.get("market_value", row.get("position_value", 0))
        weight = (
            float(market_value) / portfolio_value
            if portfolio_value
            else None
        )
        rows.append(
            {
                "Ticker": ticker,
                "Weight": None if weight is None else f"{weight * 100:.1f}%",
                "PnL %": percent_label(holding.get("unrealised_pnl_percent")),
                "Entry Date": row.get("entry_date"),
                "Current Price": price_label(
                    holding.get("current_price", row.get("entry_price"))
                ),
            }
        )
    return rows


def tracker_period_return(tracker, days):
    if tracker.empty or "portfolio_value" not in tracker.columns:
        return "Unavailable"

    working = tracker.copy()
    if "date" in working.columns:
        working["_date"] = pd.to_datetime(working["date"], errors="coerce")
        working = working.dropna(subset=["_date"])
        if not working.empty:
            cutoff = working["_date"].max() - pd.Timedelta(days=days)
            working = working[working["_date"] >= cutoff]

    values = pd.to_numeric(working["portfolio_value"], errors="coerce").dropna()
    if len(values) < 2 or values.iloc[0] == 0:
        return "Unavailable"

    return f"{((values.iloc[-1] / values.iloc[0]) - 1) * 100:.2f}%"


def tracker_day_pnl(tracker):
    if tracker.empty or "portfolio_value" not in tracker.columns:
        return "Unavailable"

    values = pd.to_numeric(tracker["portfolio_value"], errors="coerce").dropna()
    if len(values) < 2:
        return "Unavailable"

    return f"{values.iloc[-1] - values.iloc[-2]:,.2f}"


def decorated_trace_rows(decisions):
    rows = []
    for row in build_decision_trace_rows(decisions):
        signal = row.get("Signal")
        decision = row.get("Decision")
        row["Signal Badge"] = (
            f"BUY" if signal == "BUY" else "SELL" if signal == "SELL" else "HOLD"
        )
        row["Decision Badge"] = "TRADED" if decision == "TRADE_EXECUTED" else "NO TRADE"
        rows.append(row)
    return rows


def run_git_command(args):
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "Unavailable"


def latest_date(df, candidates):
    if df.empty:
        return ""

    for column in candidates:
        if column in df.columns:
            values = pd.to_datetime(df[column], errors="coerce")
            values = values.dropna()

            if not values.empty:
                return values.max()

    first_column = df.columns[0] if len(df.columns) else None

    if first_column is None:
        return ""

    values = pd.to_datetime(df[first_column], errors="coerce")
    values = values.dropna()

    if values.empty:
        return ""

    return values.max()


def is_recent(value, hours=36):
    if value == "" or pd.isna(value):
        return False

    age_hours = (
        pd.Timestamp.now() - pd.Timestamp(value)
    ).total_seconds() / 3600
    return age_hours <= hours


def numeric_series(df, column):
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)

    return pd.to_numeric(df[column], errors="coerce")


def numeric_sum(df, column):
    values = numeric_series(df, column)

    if values.empty:
        return 0.0

    return float(values.fillna(0).sum())


def first_numeric(df, column, default=0.0):
    values = numeric_series(df, column)

    if values.empty:
        return default

    return float(values.fillna(default).iloc[0])


def completed_pair_capacity(journal):
    if journal.empty or "action" not in journal.columns:
        return 0

    actions = journal["action"].astype(str).str.upper()
    buys = int((actions == "BUY").sum())
    sells = int((actions == "SELL").sum())
    return min(buys, sells)


def status_rank(status):
    return {
        HEALTHY: 0,
        INFO: 0,
        WARNING: 1,
        CRITICAL: 2,
    }.get(status, 0)


def add_check(checks, section, name, status, details):
    action = "No action needed"

    if status == WARNING:
        action = "Run GitHub workflow or inspect CSV file"
    elif status == CRITICAL:
        action = "Run python main_v2.py locally, check Supabase sync, then inspect CSV file"

    checks.append(
        {
            "Section": section,
            "Check name": name,
            "Status": STATUS_LABELS[status],
            "Details": details,
            "Recommended action": action,
        }
    )


def freshness_status(filename, exists, row_count, modified_at):
    if not exists:
        return CRITICAL if filename in REQUIRED_FILES else WARNING

    if row_count == 0:
        return WARNING

    if modified_at == "":
        return WARNING

    age_hours = (
        pd.Timestamp.now() - pd.Timestamp(modified_at)
    ).total_seconds() / 3600

    if age_hours > 72:
        return WARNING

    return HEALTHY


REQUIRED_FILES = {
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
}

data = {}
load_errors = {}

for filename in FILES:
    data[filename], load_errors[filename] = load_csv(filename)

broker = data["broker_account.csv"]
holdings = data["holdings_report.csv"]
portfolio = data["paper_portfolio_v3.csv"]
journal = data["trade_journal_v3.csv"]
audit = data["trade_audit_trail.csv"]
snapshots = data["trade_snapshots.csv"]
analytics = data["trade_analytics_v3.csv"]
tracker = data["paper_30_day_tracker.csv"]
backtest_portfolio = data["portfolio_v2.csv"]
signals = data["signal_report_v2.csv"]

checks = []

for filename in FILES:
    path = Path(filename)
    error = load_errors[filename]

    if path.exists() and error is None:
        status = HEALTHY if filename in REQUIRED_FILES else INFO
        detail = f"{len(data[filename])} rows"
    elif path.exists():
        status = WARNING
        detail = error
    else:
        status = CRITICAL if filename in REQUIRED_FILES else WARNING
        detail = f"Missing expected file: {filename}"

    add_check(checks, "Data Files", f"{filename} available", status, detail)

generated_files = [
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
    "trade_audit_trail.csv",
    "trade_analytics_v3.csv",
    "paper_30_day_tracker.csv",
    "portfolio_v2.csv",
    "signal_report_v2.csv",
]
generated_mtimes = [
    file_mtime(filename)
    for filename in generated_files
    if file_mtime(filename) != ""
]
latest_generated_mtime = max(generated_mtimes) if generated_mtimes else ""

add_check(
    checks,
    "Freshness",
    "Generated CSVs updated recently",
    HEALTHY if is_recent(latest_generated_mtime, hours=36) else INFO,
    (
        f"Latest generated CSV modified {display_time(latest_generated_mtime)}"
        if latest_generated_mtime != ""
        else "Generated CSV metadata unavailable"
    ),
)

portfolio_latest_date = latest_date(backtest_portfolio, ["Date", "date"])
add_check(
    checks,
    "Freshness",
    "Latest portfolio_v2.csv date exists",
    HEALTHY if portfolio_latest_date != "" else WARNING,
    (
        f"Latest date {display_time(portfolio_latest_date)}"
        if portfolio_latest_date != ""
        else "No parseable date column found in portfolio_v2.csv"
    ),
)

tracker_latest_date = latest_date(tracker, ["date", "Date"])
add_check(
    checks,
    "Freshness",
    "Tracker updated recently",
    HEALTHY if is_recent(tracker_latest_date, hours=36) else WARNING,
    (
        f"Latest tracker date {display_time(tracker_latest_date)}"
        if tracker_latest_date != ""
        else "No parseable tracker date found"
    ),
)

add_check(
    checks,
    "Freshness",
    "signal_report_v2.csv has rows",
    HEALTHY if len(signals) > 0 else WARNING,
    f"{len(signals)} rows",
)

if journal.empty:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Trade journal exists and has rows",
        CRITICAL,
        "trade_journal_v3.csv has no rows",
    )
else:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Trade journal exists and has rows",
        HEALTHY,
        f"{len(journal)} rows",
    )

if tracker.empty:
    add_check(
        checks,
        "Freshness",
        "Tracker exists and has rows",
        WARNING,
        "paper_30_day_tracker.csv has no rows",
    )
else:
    latest_tracker = (
        tracker["date"].iloc[-1]
        if "date" in tracker.columns
        else f"Row {len(tracker)}"
    )
    add_check(
        checks,
        "Freshness",
        "Tracker exists and has rows",
        HEALTHY,
        str(latest_tracker),
    )

if analytics.empty:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Analytics exists and has rows",
        WARNING,
        "trade_analytics_v3.csv has no rows",
    )
else:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Analytics exists and has rows",
        HEALTHY,
        f"{len(analytics)} rows",
    )

if broker.empty:
    add_check(
        checks,
        "Portfolio Integrity",
        "Broker cash + holdings equals portfolio value",
        CRITICAL,
        "broker_account.csv is missing or empty",
    )
else:
    cash = first_numeric(broker, "cash")
    broker_value = first_numeric(broker, "portfolio_value")
    holdings_value = numeric_sum(holdings, "market_value")
    difference = abs((cash + holdings_value) - broker_value)
    tolerance = max(1.0, broker_value * 0.001)
    status = HEALTHY if difference <= tolerance else CRITICAL
    detail = (
        f"cash {cash:,.2f} + holdings {holdings_value:,.2f}; "
        f"broker value {broker_value:,.2f}; diff {difference:,.2f}"
    )
    add_check(
        checks,
        "Portfolio Integrity",
        "Broker cash + holdings equals portfolio value",
        status,
        detail,
    )

if holdings.empty and portfolio.empty:
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        HEALTHY,
        "No open holdings in either file",
    )
elif "ticker" not in holdings.columns or "ticker" not in portfolio.columns:
    missing_columns = []
    if "ticker" not in holdings.columns:
        missing_columns.append("holdings_report.csv:ticker")
    if "ticker" not in portfolio.columns:
        missing_columns.append("paper_portfolio_v3.csv:ticker")
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        CRITICAL,
        f"Missing column(s): {', '.join(missing_columns)}",
    )
else:
    holdings_tickers = set(holdings["ticker"].dropna().astype(str))
    portfolio_tickers = set(portfolio["ticker"].dropna().astype(str))
    status = HEALTHY if holdings_tickers == portfolio_tickers else CRITICAL
    missing_from_holdings = sorted(portfolio_tickers - holdings_tickers)
    missing_from_portfolio = sorted(holdings_tickers - portfolio_tickers)
    detail = (
        f"expected portfolio tickers={sorted(portfolio_tickers)}; "
        f"actual holdings tickers={sorted(holdings_tickers)}; "
        f"missing_from_holdings={missing_from_holdings}; "
        f"missing_from_portfolio={missing_from_portfolio}"
    )
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        status,
        detail,
    )

if portfolio.empty or "ticker" not in portfolio.columns:
    add_check(
        checks,
        "Portfolio Integrity",
        "No duplicate open portfolio tickers",
        WARNING,
        "No portfolio tickers available",
    )
else:
    duplicates = portfolio.loc[
        portfolio["ticker"].duplicated(),
        "ticker",
    ].dropna().astype(str).tolist()
    duplicate_count = len(duplicates)
    add_check(
        checks,
        "Portfolio Integrity",
        "No duplicate open portfolio tickers",
        HEALTHY if duplicate_count == 0 else CRITICAL,
        (
            f"{duplicate_count} duplicate rows: {duplicates}"
            if duplicates
            else "No duplicate tickers"
        ),
    )

if broker.empty or "cash" not in broker.columns:
    add_check(
        checks,
        "Portfolio Integrity",
        "No negative cash",
        CRITICAL,
        "Cash unavailable",
    )
else:
    cash = first_numeric(broker, "cash")
    add_check(
        checks,
        "Portfolio Integrity",
        "No negative cash",
        HEALTHY if cash >= 0 else CRITICAL,
        f"Cash {cash:,.2f}",
    )

share_issues = []
for filename, df in [
    ("holdings_report.csv", holdings),
    ("paper_portfolio_v3.csv", portfolio),
    ("trade_journal_v3.csv", journal),
]:
    shares = numeric_series(df, "shares")
    if not shares.empty:
        negative_count = int((shares < 0).sum())
        if negative_count:
            share_issues.append(f"{filename}: {negative_count}")

add_check(
    checks,
    "Portfolio Integrity",
    "No negative shares",
    CRITICAL if share_issues else HEALTHY,
    "; ".join(share_issues) if share_issues else "No negative shares found",
)

possible_pairs = completed_pair_capacity(journal)
audit_rows = len(audit)
add_check(
    checks,
    "Trade Journal / Audit",
    "Audit rows are not greater than possible completed pairs",
    HEALTHY if audit_rows <= possible_pairs else CRITICAL,
    f"Audit rows {audit_rows}; possible completed pairs {possible_pairs}",
)

if Path("trade_snapshots.csv").exists():
    status = HEALTHY if load_errors["trade_snapshots.csv"] is None else WARNING
    detail = load_errors["trade_snapshots.csv"] or f"{len(snapshots)} rows"
else:
    status = WARNING
    detail = "File is missing"

add_check(checks, "Snapshots", "trade_snapshots.csv exists", status, detail)

if broker.empty:
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        INFO,
        "CSV fallback has no broker rows",
    )
elif "updated_at" in broker.columns:
    latest_broker_update = broker["updated_at"].dropna().astype(str).tail(1)
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        HEALTHY if not latest_broker_update.empty else WARNING,
        latest_broker_update.iloc[0] if not latest_broker_update.empty else "Missing",
    )
else:
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        INFO,
        "Not present in CSV fallback; Supabase broker rows carry updated_at",
    )

freshness_rows = []
for filename in FILES:
    path = Path(filename)
    exists = path.exists()
    df = data[filename]
    modified_at = file_mtime(filename)
    row_count = len(df) if load_errors[filename] is None else 0
    status = freshness_status(filename, exists, row_count, modified_at)
    freshness_rows.append(
        {
            "filename": filename,
            "exists": "yes" if exists else "no",
            "last modified": display_time(modified_at),
            "age": age_label(modified_at),
            "row count": row_count,
            "freshness status": STATUS_LABELS[status],
        }
    )

checks_df = pd.DataFrame(checks)
passed_count = int((checks_df["Status"] == STATUS_LABELS[HEALTHY]).sum())
info_count = int((checks_df["Status"] == STATUS_LABELS[INFO]).sum())
warning_count = int((checks_df["Status"] == STATUS_LABELS[WARNING]).sum())
critical_count = int((checks_df["Status"] == STATUS_LABELS[CRITICAL]).sum())
total_checks = len(checks_df)
scored_checks = passed_count + warning_count + critical_count
pass_percent = (
    (passed_count / scored_checks) * 100
    if scored_checks
    else 0
)

if critical_count:
    overall_status = "Critical"
elif warning_count:
    overall_status = "Warnings"
else:
    overall_status = "Healthy"

latest_commit_time = run_git_command(["log", "-1", "--format=%ci"])
latest_commit_message = run_git_command(["log", "-1", "--format=%s"])
csv_update_status = (
    STATUS_LABELS[HEALTHY]
    if is_recent(latest_generated_mtime, hours=36)
    else STATUS_LABELS[INFO]
)

portfolio_latest_date = latest_date(backtest_portfolio, ["Date", "date"])
tracker_latest_date = latest_date(tracker, ["date", "Date"])

cash = first_numeric(broker, "cash")
portfolio_value = first_numeric(broker, "portfolio_value")
realised_pnl = first_numeric(broker, "realised_pnl")
unrealised_pnl = first_numeric(broker, "unrealised_pnl")
holdings_value = numeric_sum(holdings, "market_value")
open_holdings_count = len(portfolio)

st.title("⚙️ Admin / System Health")
if auto_refresh["enabled"]:
    st.caption(f"Auto-refresh: ON | Every {auto_refresh['interval_seconds']}s")
else:
    st.caption("Auto-refresh: OFF")

summary_cols = responsive_columns(7)
summary_cols[0].metric("Overall status", overall_status)
summary_cols[1].metric("Total checks", total_checks)
summary_cols[2].metric("Healthy checks", passed_count)
summary_cols[3].metric("Info", info_count)
summary_cols[4].metric("Warnings", warning_count)
summary_cols[5].metric("Critical issues", critical_count)
summary_cols[6].metric("Passed", f"{pass_percent:.0f}%")

st.caption(
    "Last validation time: "
    f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

if st.button("Run Full System Validation"):
    st.session_state["health_validation_complete"] = {
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_checks": total_checks,
        "warnings": warning_count,
        "critical": critical_count,
    }
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

validation_result = st.session_state.get("health_validation_complete")

if validation_result:
    st.success(
        "Validation complete | "
        f"{validation_result['timestamp']} | "
        f"Total checks: {validation_result['total_checks']} | "
        f"Warnings: {validation_result['warnings']} | "
        f"Critical issues: {validation_result['critical']}"
    )

st.divider()
st.subheader("GitHub Automation")

git_cols = responsive_columns(4)
git_cols[0].metric(
    "Last generated data commit time",
    latest_commit_time or "Unavailable",
)
git_cols[1].metric(
    "Latest commit message",
    latest_commit_message or "Unavailable",
)
git_cols[2].metric("Generated CSV freshness", csv_update_status)
git_cols[3].metric(
    "Latest CSV modified",
    (
        f"{display_time(latest_generated_mtime)} ({age_label(latest_generated_mtime)})"
        if latest_generated_mtime != ""
        else "Unavailable"
    ),
)

st.divider()
st.subheader("Market Data / Signals")

market_cols = responsive_columns(4)
market_cols[0].metric(
    "Latest portfolio date",
    display_time(portfolio_latest_date) or "Unavailable",
)
market_cols[1].metric(
    "Latest tracker date",
    display_time(tracker_latest_date) or "Unavailable",
)
market_cols[2].metric("Signal report rows", len(signals))
market_cols[3].metric(
    "Tracker freshness",
    (
        STATUS_LABELS[HEALTHY]
        if is_recent(tracker_latest_date, hours=36)
        else STATUS_LABELS[WARNING]
    ),
)

st.divider()
st.subheader("Portfolio Summary")

portfolio_cols = responsive_columns(6)
portfolio_cols[0].metric("Cash", f"{cash:,.2f}")
portfolio_cols[1].metric("Holdings market value", f"{holdings_value:,.2f}")
portfolio_cols[2].metric("Portfolio value", f"{portfolio_value:,.2f}")
portfolio_cols[3].metric("Realised PnL", f"{realised_pnl:,.2f}")
portfolio_cols[4].metric("Unrealised PnL", f"{unrealised_pnl:,.2f}")
portfolio_cols[5].metric("Open holdings", open_holdings_count)

st.divider()
st.subheader("Live Control Centre")
runtime_status = load_runtime_status()
runtime_config = load_json_file("runtime/live_runtime_config.json")
runtime_status = dict(runtime_status)
runtime_status.setdefault("cycle_seconds", runtime_config.get("cycle_seconds", 300))
decision_trace = load_json_file("data/runtime_decision_trace.json")
last_cycle = get_last_cycle()
recent_cycles = get_recent_cycles(limit=50)
runtime_stats = get_runtime_statistics()
notification_health = notification_status()
heartbeat_label, heartbeat_ok = heartbeat_status(runtime_status)
configured_markets = safe_list(runtime_config.get("markets")) or [
    "LSE",
    "US",
    "TSE",
]
activity = activity_state(
    runtime_status,
    runtime_config,
    heartbeat_ok,
    configured_markets,
)
active_markets = safe_list(runtime_status.get("markets_open"))

st.caption(
    "The dashboard does not run the live system. It only displays the "
    "runtime heartbeat, market state, and operations log written by "
    "runtime/live_runtime.py."
)

inject_mission_control_css()
execution_summary = runtime_status.get("execution_summary") or {}
strategy_summary, strategy_summary_source = latest_completed_execution_summary(
    execution_summary
)
last_successful = latest_successful_cycle(recent_cycles)
mode_label = (
    runtime_status.get("mode")
    or runtime_config.get("mode")
    or "monitor_only"
).replace("_", " ").title()
active_market_label = (
    f"{', '.join(expand_market_names(active_markets))} OPEN"
    if active_markets
    else "Markets Closed"
)
runtime_live = runtime_state(runtime_status)["running"]
trace_decisions = safe_list(decision_trace.get("decisions"))

current_mission_stage = render_hero_status(
    runtime_status,
    runtime_config,
    heartbeat_ok,
    active_markets,
)

today_trade_rows = today_trades_from_sources(journal)
st.info(
    runtime_status_sentence(
        runtime_status,
        strategy_summary,
        today_trade_rows,
        notification_health,
    )
)

st.markdown("**Data Freshness**")
freshness_items = data_freshness_items(runtime_status)
render_data_freshness_card(freshness_items)
st.caption(data_freshness_summary(freshness_items))

st.markdown("**Live Pipeline**")
render_pipeline(current_mission_stage)

open_market_names, closed_market_names = market_groups()
market_panel_cols = responsive_columns(2)
with market_panel_cols[0]:
    st.markdown("**Markets Currently Open**")
    if open_market_names:
        st.success("  ".join(f"🟢 {name}" for name in open_market_names))
    else:
        st.info("No configured markets are currently open.")
with market_panel_cols[1]:
    st.markdown("**Closed**")
    if closed_market_names:
        st.warning("  ".join(f"🔴 {name}" for name in closed_market_names))
    else:
        st.success("All configured markets are open.")
st.caption(f"Next Market Event: {next_market_to_open(configured_markets)}")

st.markdown("**Market Intelligence**")
headline_rows, intelligence = market_intelligence_rows(limit=10)
intelligence_cols = responsive_columns(4)
intelligence_cols[0].metric("Stories Stored", intelligence.get("stories_count", 0))
intelligence_cols[1].metric(
    "Sources",
    ", ".join(safe_list(intelligence.get("sources"))) or "Unavailable",
)
intelligence_cols[2].metric(
    "Last Updated",
    short_time(intelligence.get("generated_at")),
)
intelligence_cols[3].metric(
    "Errors",
    len(safe_list(intelligence.get("errors"))),
)
st.caption(
    "Read-only market intelligence. Headlines are operator context only and "
    "do not change signals, portfolio decisions, or paper execution."
)
st.info(intelligence.get("market_summary") or "No market summary available yet.")

mi_tabs = st.tabs(
    [
        "Latest Headlines",
        "Portfolio Exposure",
        "Top Stories",
        "Macro Calendar",
    ]
)
with mi_tabs[0]:
    if headline_rows:
        responsive_table(pd.DataFrame(headline_rows), hide_index=True)
    else:
        st.info("No market intelligence headlines have been collected yet.")
with mi_tabs[1]:
    exposure_rows = portfolio_exposure_rows(intelligence)
    if exposure_rows:
        responsive_table(pd.DataFrame(exposure_rows), hide_index=True)
    else:
        st.info("No current portfolio exposure has been matched to headlines yet.")
with mi_tabs[2]:
    top_rows = top_story_rows(intelligence)
    if top_rows:
        responsive_table(pd.DataFrame(top_rows), hide_index=True)
    else:
        st.info("No top stories have been identified yet.")
with mi_tabs[3]:
    calendar_rows = macro_calendar_rows(intelligence)
    if calendar_rows:
        responsive_table(pd.DataFrame(calendar_rows), hide_index=True)
    else:
        st.info("No macro calendar items are available yet.")

st.markdown("**Latest Completed Strategy**")
st.caption(
    "Using the latest successful runtime execution log when the live cycle is still in progress."
    if strategy_summary_source == "execution_log"
    else "Using the latest completed runtime status summary."
)
strategy_cols = responsive_columns(6)
strategy_cols[0].metric("Symbols Scanned", strategy_summary.get("symbols_scanned", 0))
strategy_cols[1].metric("BUY Signals", strategy_summary.get("buy_signals", 0))
strategy_cols[2].metric("SELL Signals", strategy_summary.get("sell_signals", 0))
strategy_cols[3].metric(
    "Portfolio Changes",
    strategy_summary.get("paper_trades", strategy_summary.get("trades_recorded", 0)),
)
strategy_cols[4].metric(
    "Completed In",
    f"{float(strategy_summary.get('execution_time_seconds', 0) or 0):.2f}s",
)
strategy_cols[5].metric("Current Holdings", f"{open_holdings_count} positions")

latest_trade_today = latest_trade_from_journal(journal)
latest_notification_title, latest_notification_ticker, latest_notification_time = (
    latest_notification_label()
)

trade_cols = responsive_columns(2)
with trade_cols[0]:
    st.markdown("**Latest Paper Trade**")
    if latest_trade_today:
        latest_trade_time = latest_trade_today.get("timestamp")
        st.metric(
            latest_trade_today.get("action", "TRADE"),
            latest_trade_today.get("ticker", "Unknown"),
            short_time(latest_trade_time),
        )
        trade_weight = None
        trade_value = safe_float(latest_trade_today.get("value"))
        if trade_value is not None and portfolio_value:
            trade_weight = f"{(trade_value / portfolio_value) * 100:.2f}%"
        detail_cols = responsive_columns(5)
        detail_cols[0].metric("Price", price_label(latest_trade_today.get("price")))
        detail_cols[1].metric("Value", money_label(latest_trade_today.get("value")))
        detail_cols[2].metric(
            "Shares",
            (
                f"{safe_float(latest_trade_today.get('shares')):.4f}"
                if safe_float(latest_trade_today.get("shares")) is not None
                else "Unavailable"
            ),
        )
        detail_cols[3].metric("Weight", trade_weight or "Unavailable")
        detail_cols[4].metric(
            "Notification",
            latest_trade_today.get("telegram_status", "No/Unknown"),
        )
    else:
        st.info("No paper trade today.")
with trade_cols[1]:
    st.markdown("**Telegram**")
    telegram_status, telegram_detail = telegram_panel_state(notification_health)
    st.metric(
        telegram_status,
        latest_notification_title,
        (
            f"{latest_notification_ticker} | {latest_notification_time}"
            if latest_notification_ticker
            else telegram_detail
        ),
    )
    st.caption(
        f"Total notifications today: {notification_health.get('notifications_sent_today', 0)}"
    )

st.markdown("**Today's Trades**")
if today_trade_rows:
    today_trade_display = []
    for row in today_trade_rows:
        today_trade_display.append(
            {
                "Time": short_time(row.get("timestamp")),
                "Action": row.get("action"),
                "Ticker": row.get("ticker"),
                "Price": price_label(row.get("price")),
                "Shares": (
                    f"{safe_float(row.get('shares')):.4f}"
                    if safe_float(row.get("shares")) is not None
                    else "Unavailable"
                ),
                "Value": money_label(row.get("value")),
                "PnL": money_label(row.get("pnl")),
                "Telegram Sent": row.get("telegram_status", "No/Unknown"),
            }
        )
    responsive_table(pd.DataFrame(today_trade_display), hide_index=True)
else:
    st.info("No paper trades recorded today.")

render_performance_strip(
    [
        ("Today's PnL", tracker_day_pnl(tracker)),
        ("This Week", tracker_period_return(tracker, 7)),
        ("This Month", tracker_period_return(tracker, 30)),
        ("Portfolio Value", money_label(portfolio_value)),
        ("Cash Remaining", money_label(cash)),
    ]
)

portfolio_rows = portfolio_snapshot_rows(portfolio, holdings, portfolio_value)
st.markdown("**Mini Portfolio**")
if portfolio_rows:
    responsive_table(pd.DataFrame(portfolio_rows), hide_index=True)
else:
    st.info("No open paper holdings.")

st.markdown("**Mission Control Diagnostics**")
operator_cols = responsive_columns(8)
operator_cols[0].metric("State", "🟢 LIVE" if runtime_live else "🔴 OFFLINE")
operator_cols[1].metric("Mode", mode_label)
operator_cols[2].metric("Market", active_market_label)
operator_cols[3].metric("Runtime", runtime_state(runtime_status)["health"])
operator_cols[4].metric("Last Cycle", short_time(runtime_status.get("last_cycle_at")))
operator_cols[5].metric("Next Cycle", next_cycle_clock_label(runtime_status))
operator_cols[6].metric("Next Scan", next_scan_label(runtime_status))
operator_cols[7].metric("Heartbeat", heartbeat_label)

st.info(
    operator_summary(
        runtime_status,
        runtime_config,
        heartbeat_ok,
        configured_markets,
        execution_summary,
        notification_health,
    )
)

st.markdown("**Global Market Banner**")
render_market_banner(configured_markets)

latest_notification_title, latest_notification_ticker, latest_notification_time = (
    latest_notification_label()
)

st.markdown("**Quick Stats**")
quick_cols = responsive_columns(6)
quick_cols[0].metric("Today's Strategy Runs", runtime_stats.get("today_strategy_runs", 0))
quick_cols[1].metric("Today's Paper Trades", runtime_stats.get("today_paper_trades", 0))
quick_cols[2].metric("Today's Notifications", runtime_stats.get("today_notifications", 0))
quick_cols[3].metric("Runtime Uptime", runtime_uptime_label(runtime_status))
quick_cols[4].metric(
    "Average Cycle Time",
    f"{runtime_stats.get('average_cycle_duration', 0):.2f}s",
)
quick_cols[5].metric("Current Holdings", open_holdings_count)

run_cols = responsive_columns(3)
if last_successful is None:
    run_cols[0].metric("Last Successful Strategy", "Unavailable")
    run_cols[1].metric("Completed", "Unavailable")
else:
    run_cols[0].metric(
        "Last Successful Strategy",
        short_time(last_successful.get("finished_at")),
    )
    run_cols[1].metric("Completed", human_age(last_successful.get("finished_at")))
run_cols[2].metric(
    "Latest Notification",
    latest_notification_title,
    (
        f"{latest_notification_ticker} | {latest_notification_time}"
        if latest_notification_ticker
        else ""
    ),
)

st.markdown("**Operations Health**")
health_rows = [
    health_item("Runtime", runtime_live),
    heartbeat_health_item(runtime_status),
    health_item(
        "Paper Execution",
        paper_execution_enabled(runtime_status, runtime_config),
        healthy_text="Enabled",
        bad_text="Disabled",
        bad_level="yellow",
    ),
    health_item(
        "Telegram",
        notification_health.get("telegram_configured"),
        healthy_text="Connected",
        bad_text="Not configured",
        bad_level="yellow",
    ),
    health_item(
        "Decision Trace",
        bool(trace_decisions),
        healthy_text="Working",
        bad_text="No trace yet",
        bad_level="yellow",
    ),
    health_item(
        "Auto Refresh",
        auto_refresh.get("enabled"),
        healthy_text="Enabled",
        bad_text="Disabled",
        bad_level="yellow",
    ),
]
health_card_rows(health_rows)

render_activity_panel(activity, runtime_status)

status_cols = responsive_columns(6)
status_cols[0].metric(
    "Runtime Status",
    runtime_status.get("status", "not started"),
)
status_cols[1].metric(
    "Mode",
    runtime_status.get("mode")
    or runtime_config.get("mode")
    or "monitor_only",
)
status_cols[2].metric(
    "Paper Execution",
    "Enabled"
    if paper_execution_enabled(runtime_status, runtime_config)
    else "Disabled",
)
status_cols[3].metric("Next Market", next_market_to_open(configured_markets))
status_cols[4].metric("Next Cycle", next_cycle_delta(runtime_status))
status_cols[5].metric("Heartbeat", heartbeat_label)

latest_event = runtime_status.get("latest_runtime_event") or {}
latest_trade = runtime_status.get("latest_paper_trade") or {}
progress_value = 1.0 if runtime_status.get("status") == "running" else 0.0
st.progress(progress_value)
runtime_now_cols = responsive_columns(3)
runtime_now_cols[0].metric(
    "Current Strategy Stage",
    runtime_status.get("current_strategy_stage") or "Idle",
)
runtime_now_cols[1].metric(
    "Latest Runtime Event",
    latest_event.get("type") or "None",
)
runtime_now_cols[2].metric(
    "Latest Paper Trade",
    (
        f"{latest_trade.get('action')} {latest_trade.get('ticker')}"
        if latest_trade
        else "None"
    ),
)

if False:
    banner_cols = responsive_columns(5)
    banner_cols[0].metric(banner_title, banner_detail)
    banner_cols[1].metric(
        "Runtime Mode",
        runtime_status.get("mode")
        or runtime_config.get("mode")
        or "monitor_only",
    )
    banner_cols[2].metric(
        "Runtime State",
        runtime_status.get("status", "not started"),
    )
    banner_cols[3].metric("Runtime Version", "V2 / Control Centre V1")
    banner_cols[4].metric(
    "Heartbeat",
    f"{heartbeat_label} · Paper Only",
)

if False:
    st.success("Live Runtime is running in paper-only monitoring mode.")
elif False:
    st.warning("Runtime is healthy and waiting for the next open market.")
elif False:
    st.error("Runtime is offline or unavailable. Start it from PowerShell when needed.")

if last_cycle is None:
    st.info(
        "No runtime operation cycles have been logged yet. Start the runtime "
        "to populate the control centre."
    )
else:
    st.markdown("**Cycle Summary**")
    st.info(last_cycle.get("cycle_summary", "No cycle summary available."))
    summary_cols = responsive_columns(3)
    summary_cols[0].markdown(
        f"**Reason**\n\n{last_cycle.get('reason') or 'Unavailable'}"
    )
    summary_cols[1].markdown(
        f"**Action taken**\n\n{last_cycle.get('action_taken') or 'Unavailable'}"
    )
    summary_cols[2].markdown(
        "**Next expected action**\n\n"
        f"{last_cycle.get('next_expected_action') or 'Unavailable'}"
    )

st.markdown("**What Happens Next?**")
st.info(
    what_happens_next_text(
        runtime_status,
        runtime_config,
        notification_health,
        configured_markets,
    )
)

st.markdown("**Global Market Status**")
market_cols = responsive_columns(3)
for index, market in enumerate(["LSE", "US", "TSE"]):
    label, full_name = MARKET_DISPLAY.get(market, (market, market))
    status_label, countdown = market_countdown(market)
    market_cols[index].markdown(f"### {label}")
    market_cols[index].metric("Status", status_label, countdown)
    market_cols[index].caption(f"{full_name} | {market_session_time(market)}")

market_summary_cols = responsive_columns(3)
market_summary_cols[0].metric(
    "Current active market(s)",
    ", ".join(active_markets) if active_markets else "No markets currently open",
)
market_summary_cols[1].metric(
    "Next market to open",
    next_market_to_open(configured_markets),
)
market_summary_cols[2].metric(
    "Runtime timezone",
    "UTC heartbeat / local sessions",
)

st.markdown("**Runtime Control Panel**")
control_cols = responsive_columns(6)
control_cols[0].metric(
    "Runtime",
    "Running" if runtime_status.get("status") == "running" else "Stopped",
)
control_cols[1].metric(
    "Mode",
    runtime_status.get("mode")
    or runtime_config.get("mode")
    or "monitor_only",
)
control_cols[2].metric(
    "Paper Execution",
    "Enabled"
    if paper_execution_enabled(runtime_status, runtime_config)
    else "Disabled",
)
control_cols[3].metric(
    "Cycle Interval",
    f"{runtime_config.get('cycle_seconds', runtime_status.get('cycle_seconds', 300))}s",
)
control_cols[4].metric(
    "Telegram",
    "Configured"
    if notification_health.get("telegram_configured")
    else "Not configured",
)
control_cols[5].metric("Heartbeat", heartbeat_label)
st.caption(
    "Display only: runtime settings are not editable from the dashboard yet. "
    "Paper Execution Mode updates the paper portfolio automatically only when "
    "explicitly enabled in the runtime config. It never places real broker orders."
)

st.markdown("**Runtime Activity Timeline**")
timeline_rows = build_timeline_rows(recent_cycles, runtime_status, limit=14)
if timeline_rows:
    responsive_table(pd.DataFrame(timeline_rows), hide_index=True)
else:
    st.info("No runtime timeline events have been recorded yet.")

st.markdown("**Strategy Decision Trace**")
st.caption("This explains why signals did or did not become paper trades.")
st.caption(
    "Signals are strategy opinions. Trades only happen when the portfolio "
    "manager needs to change the paper portfolio."
)

trace_decisions = safe_list(decision_trace.get("decisions"))
trace_summary = runtime_status.get("execution_summary") or {}
trace_count = int(
    trace_summary.get(
        "decision_trace_count",
        decision_trace.get("decision_trace_count", len(trace_decisions)),
    )
    or 0
)
trace_trades = int(
    trace_summary.get(
        "trade_count",
        decision_trace.get(
            "trade_count",
            decision_trace.get("trades_recorded", 0),
        ),
    )
    or 0
)
trace_no_trades = int(
    trace_summary.get(
        "no_trade_count",
        decision_trace.get("no_trade_count", max(0, trace_count - trace_trades)),
    )
    or 0
)
trace_reasons = (
    trace_summary.get("top_no_trade_reasons")
    or decision_trace.get("top_no_trade_reasons")
    or {}
)

if trace_decisions:
    st.info(
        "Garner Quant generated "
        f"{trace_count} signals and recorded {trace_trades} paper trades. "
        f"{trace_no_trades} signals did not become trades because the "
        "portfolio manager found no required portfolio changes or a safety "
        "condition blocked the candidate."
    )
    trace_cols = responsive_columns(4)
    trace_cols[0].metric("Signals evaluated", trace_count)
    trace_cols[1].metric("Trades recorded", trace_trades)
    trace_cols[2].metric("No-trade decisions", trace_no_trades)
    trace_cols[3].metric(
        "Top no-trade reasons",
        format_reason_counts(trace_reasons),
    )
    filter_cols = responsive_columns([1, 1])
    trace_filter = filter_cols[0].radio(
        "Trace filter",
        ["All", "BUY", "SELL", "NO TRADE", "TRADED"],
        horizontal=True,
        key="decision_trace_filter",
    )
    trace_search = filter_cols[1].text_input(
        "Ticker search",
        key="decision_trace_search",
        placeholder="Search ticker",
    )
    trace_rows = pd.DataFrame(decorated_trace_rows(trace_decisions))

    if trace_filter == "BUY":
        trace_rows = trace_rows[trace_rows["Signal"] == "BUY"]
    elif trace_filter == "SELL":
        trace_rows = trace_rows[trace_rows["Signal"] == "SELL"]
    elif trace_filter == "NO TRADE":
        trace_rows = trace_rows[trace_rows["Decision"] == "NO_TRADE"]
    elif trace_filter == "TRADED":
        trace_rows = trace_rows[trace_rows["Decision"] == "TRADE_EXECUTED"]

    if trace_search:
        trace_rows = trace_rows[
            trace_rows["Ticker"].astype(str).str.contains(
                trace_search,
                case=False,
                na=False,
            )
        ]

    if trace_rows.empty:
        st.info("No decision trace rows match the selected filters.")
    else:
        def highlight_traded(row):
            if row.get("Decision") == "TRADE_EXECUTED":
                return ["background-color: rgba(34, 197, 94, 0.16)"] * len(row)
            return [""] * len(row)

        def colour_badges(value):
            if value == "BUY":
                return "background-color: #dcfce7; color: #166534; font-weight: 700;"
            if value == "SELL":
                return "background-color: #fee2e2; color: #991b1b; font-weight: 700;"
            if value == "TRADED":
                return "background-color: #dbeafe; color: #1d4ed8; font-weight: 700;"
            if value == "NO TRADE":
                return "background-color: #e5e7eb; color: #374151; font-weight: 700;"
            return ""

        display_columns = [
            "Ticker",
            "Signal Badge",
            "Holding?",
            "Target Weight",
            "Current Weight",
            "Decision Badge",
            "Reason",
        ]
        responsive_table(
            trace_rows[display_columns]
            .style
            .apply(highlight_traded, axis=1)
            .map(colour_badges, subset=["Signal Badge", "Decision Badge"]),
            hide_index=True,
        )
else:
    st.info(
        "No decision trace has been written yet. It will appear after the "
        "paper execution pipeline evaluates strategy signals."
    )

st.markdown("**Runtime Health**")
total_cycles = runtime_stats.get("total_cycles", 0)
successful_cycles = runtime_stats.get("successful_cycles", 0)
success_rate = (
    successful_cycles / total_cycles * 100
    if total_cycles
    else 0
)
health_cols = responsive_columns(6)
health_cols[0].metric("Heartbeat", heartbeat_label)
health_cols[1].metric("Runtime Uptime", runtime_uptime_label(runtime_status))
health_cols[2].metric("Total Cycles", total_cycles)
health_cols[3].metric(
    "Heartbeat Age",
    heartbeat_age_label(runtime_status),
)
health_cols[4].metric(
    "Average runtime",
    f"{runtime_stats.get('average_cycle_duration', 0):.2f}s",
)
health_cols[5].metric(
    "Last successful run",
    format_time_value(runtime_stats.get("last_successful_run")),
)
health_detail_cols = responsive_columns(6)
health_detail_cols[0].metric(
    "Last Heartbeat",
    format_time_value(runtime_status.get("last_cycle_at")),
)
health_detail_cols[1].metric(
    "Last Error",
    runtime_status.get("last_error") or "None",
)
health_detail_cols[2].metric("Success Rate", f"{success_rate:.0f}%")
health_detail_cols[3].metric(
    "Runtime Events",
    runtime_status.get("execution_log_count", 0),
)
health_detail_cols[4].metric(
    "Telegram",
    "Ready" if notification_health.get("telegram_configured") else "Fallback",
)
health_detail_cols[5].metric(
    "Paper Execution Status",
    (
        "Enabled"
        if paper_execution_enabled(runtime_status, runtime_config)
        else "Disabled"
    ),
)

runtime_shared_state = runtime_state(runtime_status)

if runtime_shared_state["running"] and not heartbeat_ok:
    st.warning(
        "Runtime heartbeat is overdue. Check whether the scheduled runtime "
        "cycle has stalled."
    )

strategy_stats_cols = responsive_columns(5)
strategy_stats_cols[0].metric(
    "Today's Strategy Runs",
    runtime_stats.get("today_strategy_runs", 0),
)
strategy_stats_cols[1].metric(
    "Today's Paper Trades",
    runtime_stats.get("today_paper_trades", 0),
)
strategy_stats_cols[2].metric(
    "Today's Notifications",
    runtime_stats.get("today_notifications", 0),
)
strategy_stats_cols[3].metric(
    "Today's Runtime Errors",
    runtime_stats.get("today_runtime_errors", 0),
)
strategy_stats_cols[4].metric(
    "Average Strategy Runtime",
    f"{runtime_stats.get('average_strategy_runtime', 0):.2f}s",
)

runtime_detail_cols = responsive_columns(2)
runtime_detail_cols[0].metric(
    "Longest Runtime",
    f"{runtime_stats.get('longest_runtime', 0):.2f}s",
)
runtime_detail_cols[1].metric(
    "Runtime Uptime",
    runtime_uptime_label(runtime_status),
)

st.markdown("**Recent Cycles**")
if recent_cycles:
    recent_rows = []
    for cycle in recent_cycles:
        recent_rows.append(
            {
                "Time": format_time_value(cycle.get("finished_at")),
                "Duration": f"{float(cycle.get('duration_seconds', 0) or 0):.2f}s",
                "Markets": (
                    ", ".join(cycle.get("markets_open", []))
                    or "No markets currently open"
                ),
                "Paper Trades": cycle.get("trades_recorded", 0),
                "Alerts": cycle.get("alerts_found", 0),
                "Status": cycle.get("status"),
                "Summary": cycle.get("cycle_summary", ""),
            }
        )
    responsive_table(pd.DataFrame(recent_rows), hide_index=True)
else:
    st.info("No recent runtime cycles are available.")

st.code(
    "python runtime/live_runtime.py\n"
    "sudo systemctl restart garner-quant-runtime",
    language="powershell",
)
st.caption(
    "Restart locally from the terminal running the runtime, or on a VPS with "
    "systemd. The dashboard displays health only and does not start processes."
)

st.divider()
st.subheader("Live Market Monitor")
st.caption(
    "Live-Time Mode is monitoring only. It does not trade, sell, modify "
    "portfolio state, or change strategy decisions. It only refreshes prices "
    "and sends paper alerts."
)

runtime = load_monitor_runtime()
now_london = pd.Timestamp.now(tz="Europe/London")
market_status = get_market_status(now=now_london.to_pydatetime())

runtime_interval = int(runtime.get("refresh_interval_minutes", 5) or 5)
interval_options = [1, 2, 5, 10, 15]
interval_index = (
    interval_options.index(runtime_interval)
    if runtime_interval in interval_options
    else interval_options.index(5)
)

live_mode_cols = responsive_columns(2)
live_time_mode = live_mode_cols[0].checkbox(
    "Live-Time Mode",
    value=bool(runtime.get("enabled", False)),
)
refresh_interval = live_mode_cols[1].selectbox(
    "Refresh interval",
    interval_options,
    index=interval_index,
    format_func=lambda value: f"{value} minute{'s' if value != 1 else ''}",
)

last_refresh = parse_timestamp(runtime.get("last_refresh"))
next_refresh = parse_timestamp(runtime.get("next_refresh"))

runtime_update = {
    **runtime,
    "enabled": live_time_mode,
    "refresh_interval_minutes": refresh_interval,
    "market_status": market_status.get("status"),
    "market": market_status.get("market"),
    "updated_at": now_london.isoformat(),
}

if not live_time_mode:
    runtime_update["next_refresh"] = None
    save_monitor_runtime(runtime_update)
    next_refresh = None
else:
    if next_refresh is None:
        next_refresh = now_london

    if market_status.get("is_open") and now_london >= next_refresh:
        monitor_result = run_live_market_monitor(save_snapshot=True)
        alerts = monitor_result.get("alerts", [])
        notification_summary = (
            notify_alerts(alerts)
            if alerts
            else empty_notification_summary()
        )
        st.session_state["live_monitor_result"] = monitor_result
        st.session_state["live_notification_summary"] = notification_summary
        last_refresh = now_london
        next_refresh = now_london + pd.Timedelta(minutes=refresh_interval)
        runtime_update["last_refresh"] = last_refresh.isoformat()
        runtime_update["next_refresh"] = next_refresh.isoformat()
        runtime_update["last_auto_run_alerts"] = len(alerts)
        save_monitor_runtime(runtime_update)
    elif market_status.get("is_open"):
        runtime_update["next_refresh"] = next_refresh.isoformat()
        save_monitor_runtime(runtime_update)
    else:
        runtime_update["next_refresh"] = None
        save_monitor_runtime(runtime_update)
        next_refresh = None

status_cols = responsive_columns(6)
status_cols[0].metric(
    "Live-Time Mode",
    "ON" if live_time_mode else "OFF",
)
status_cols[1].metric(
    "Market Status",
    market_status.get("status", "Unavailable"),
)
status_cols[2].metric(
    "Refresh Interval",
    f"{refresh_interval} min",
)
status_cols[3].metric(
    "Last Refresh",
    (
        last_refresh.strftime("%Y-%m-%d %H:%M:%S")
        if last_refresh is not None
        else "None"
    ),
)
status_cols[4].metric(
    "Next Refresh",
    (
        next_refresh.strftime("%Y-%m-%d %H:%M:%S")
        if next_refresh is not None
        else "Paused"
    ),
)
status_cols[5].metric(
    "Countdown",
    countdown_label(next_refresh, now_london),
)

if live_time_mode and market_status.get("is_open"):
    st.success("Monitoring active")
elif live_time_mode:
    st.warning("Market closed")
else:
    st.info("Live-Time Mode is off")

if market_status.get("warning"):
    st.warning(market_status["warning"])

monitor_buttons = responsive_columns(2)

if monitor_buttons[0].button("Refresh Live Monitor"):
    monitor_result = run_live_market_monitor(save_snapshot=True)
    st.session_state["live_monitor_result"] = monitor_result
    last_refresh = pd.Timestamp.now(tz="Europe/London")
    runtime_update["last_refresh"] = last_refresh.isoformat()
    if live_time_mode and market_status.get("is_open"):
        next_refresh = last_refresh + pd.Timedelta(minutes=refresh_interval)
        runtime_update["next_refresh"] = next_refresh.isoformat()
    save_monitor_runtime(runtime_update)
    st.success(
        "Live monitor refreshed. Paper alerts only; no portfolio state changed."
    )

if monitor_buttons[1].button("Refresh Monitor + Send Alerts"):
    monitor_result = run_live_market_monitor(save_snapshot=True)
    alerts = monitor_result.get("alerts", [])
    notification_summary = (
        notify_alerts(alerts)
        if alerts
        else empty_notification_summary()
    )
    st.session_state["live_monitor_result"] = monitor_result
    st.session_state["live_notification_summary"] = notification_summary
    last_refresh = pd.Timestamp.now(tz="Europe/London")
    runtime_update["last_refresh"] = last_refresh.isoformat()
    if live_time_mode and market_status.get("is_open"):
        next_refresh = last_refresh + pd.Timedelta(minutes=refresh_interval)
        runtime_update["next_refresh"] = next_refresh.isoformat()
    save_monitor_runtime(runtime_update)
    st.success(
        "Live monitor refreshed and notifications checked. Paper alerts only; "
        "no portfolio state changed."
    )

monitor_snapshot = st.session_state.get("live_monitor_result")
if monitor_snapshot is None:
    monitor_snapshot = load_monitor_snapshot()

notification_summary = st.session_state.get("live_notification_summary")
notification_state = notification_status()
if notification_summary is None:
    notification_summary = notification_state.get("last_summary", {})

st.subheader("Notifications")
st.caption(
    "Notifications are reporting only. They do not place trades, modify "
    "portfolio state, or change strategy decisions."
)

test_buttons = responsive_columns(3)
test_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
test_key_timestamp = pd.Timestamp.now().strftime("%Y%m%d%H%M%S")

if test_buttons[0].button("Send Test Notification"):
    notification_summary = notify_alerts(
        [
            {
                "ticker": "TEST",
                "alert_type": "TEST_NOTIFICATION",
                "severity": "info",
                "message": "Garner Quant test paper alert.",
                "current_price": 100.0,
                "trigger_price": 100.0,
                "unrealised_pnl": 0.0,
                "timestamp": test_timestamp,
            }
        ],
        cooldown_minutes=0,
    )
    st.session_state["live_notification_summary"] = notification_summary
    notification_state = notification_status()
    st.success("Test notification sent through the notifier.")

if test_buttons[1].button("Send Test BUY Notification"):
    notification_summary = notify_trade_event(
        {
            "trade_id": f"TEST_BUY_{test_key_timestamp}",
            "action": "BUY",
            "ticker": "TEST.L",
            "entry_price": 136.80,
            "shares": 18.42,
            "position_value": 2519.52,
            "stop_loss": 132.89,
            "take_profit": 140.02,
            "timestamp": test_timestamp,
        }
    )
    st.session_state["live_notification_summary"] = notification_summary
    notification_state = notification_status()
    st.success("Test BUY notification sent through the notifier.")

if test_buttons[2].button("Send Test SELL Notification"):
    notification_summary = notify_trade_event(
        {
            "trade_id": f"TEST_SELL_{test_key_timestamp}",
            "action": "SELL",
            "ticker": "TEST.L",
            "exit_price": 140.35,
            "shares": 18.42,
            "pnl": 64.23,
            "pnl_percent": 0.026,
            "holding_period": "8 days",
            "reason": "TAKE PROFIT",
            "timestamp": test_timestamp,
        }
    )
    st.session_state["live_notification_summary"] = notification_summary
    notification_state = notification_status()
    st.success("Test SELL notification sent through the notifier.")

notification_cols = responsive_columns(8)
notification_cols[0].metric(
    "Telegram configured",
    "Yes" if notification_state.get("telegram_configured") else "No",
)
notification_cols[1].metric(
    "Email configured",
    "Yes" if notification_state.get("email_configured") else "No",
)
notification_cols[2].metric(
    "Last trade notification",
    notification_state.get("last_trade_notification_sent") or "None",
)
notification_cols[3].metric(
    "Last monitor alert",
    notification_state.get("last_monitor_alert_sent") or "None",
)
notification_cols[4].metric(
    "Sent today",
    notification_state.get("notifications_sent_today", 0),
)
notification_cols[5].metric(
    "Cooldown skips",
    notification_summary.get("skipped_due_to_cooldown", 0),
)
notification_cols[6].metric(
    "Dedup skips",
    notification_summary.get("skipped_due_to_deduplication", 0),
)
notification_cols[7].metric(
    "Errors",
    len(notification_summary.get("errors", [])),
)

last_notification_error = (
    notification_state.get("last_notification_error")
    or "No notification errors recorded."
)
st.caption(f"Last notification error: {last_notification_error}")

if monitor_snapshot is None:
    st.info("No live monitor snapshot yet. Click Refresh Live Monitor to run V1.")
else:
    monitor_cols = responsive_columns(5)
    monitor_cols[0].metric(
        "Last monitor update",
        monitor_snapshot.get("timestamp", "Unavailable"),
    )
    monitor_cols[1].metric(
        "Holdings monitored",
        monitor_snapshot.get("holdings_monitored", 0),
    )
    monitor_cols[2].metric(
        "Live value estimate",
        f"{monitor_snapshot.get('live_portfolio_value_estimate', 0):,.2f}",
    )
    monitor_cols[3].metric(
        "Live unrealised PnL",
        f"{monitor_snapshot.get('live_unrealised_pnl', 0):,.2f}",
    )
    monitor_cols[4].metric(
        "Active alerts",
        len(monitor_snapshot.get("alerts", [])),
    )

    if notification_summary:
        st.caption(
            "Last notification run: "
            f"sent {notification_summary.get('sent', 0)}, "
            f"skipped {notification_summary.get('skipped', 0)}."
        )

    alerts = monitor_snapshot.get("alerts", [])
    errors = monitor_snapshot.get("errors", [])
    positions = monitor_snapshot.get("positions", [])
    notification_errors = notification_summary.get("errors", [])

    if alerts:
        st.warning("Paper alerts are active.")
        for alert in alerts:
            ticker = alert.get("ticker", "Unknown")
            alert_type = alert.get("alert_type", "ALERT")
            st.markdown(f"**Paper Alert: {ticker} {alert_type}**")
            st.write(alert.get("message", "Alert triggered."))

            alert_cols = responsive_columns(3)
            current_price = alert.get("current_price")
            trigger_price = alert.get("trigger_price")
            alert_pnl = alert.get("unrealised_pnl")
            alert_cols[0].metric(
                "Current price",
                "Unavailable" if current_price is None else f"{current_price:,.2f}",
            )
            alert_cols[1].metric(
                "Trigger level",
                "Unavailable" if trigger_price is None else f"{trigger_price:,.2f}",
            )
            alert_cols[2].metric(
                "Unrealised PnL",
                "Unavailable" if alert_pnl is None else f"{alert_pnl:,.2f}",
            )
            st.info("Action: Would exit now if live execution was enabled.")
    else:
        st.success("No active live paper alerts.")

    if notification_errors:
        st.error("Notification errors detected.")
        responsive_table(
            pd.DataFrame({"error": notification_errors}),
            hide_index=True,
        )

    if errors:
        st.error("Price fetch or position data errors detected.")
        responsive_table(
            pd.DataFrame({"error": errors}),
            hide_index=True,
        )

    if positions:
        display_positions = pd.DataFrame(positions)
        visible_columns = [
            "ticker",
            "current_price",
            "market_value",
            "unrealised_pnl",
            "unrealised_pnl_percent",
            "stop_loss",
            "take_profit",
            "status",
            "price_timestamp",
        ]
        visible_columns = [
            column
            for column in visible_columns
            if column in display_positions.columns
        ]
        responsive_table(
            display_positions[visible_columns],
            hide_index=True,
        )

st.divider()
st.subheader("Integrity Score")

score_cols = responsive_columns(5)
score_cols[0].metric("Total checks", total_checks)
score_cols[1].metric("Healthy", passed_count)
score_cols[2].metric("Info", info_count)
score_cols[3].metric("Warnings / Critical", f"{warning_count} / {critical_count}")
score_cols[4].metric("Percentage passed", f"{pass_percent:.0f}%")

for section in [
    "Data Files",
    "Portfolio Integrity",
    "Trade Journal / Audit",
    "Snapshots",
    "Freshness",
]:
    section_df = checks_df[checks_df["Section"] == section]

    if section_df.empty:
        continue

    st.subheader(section)
    responsive_table(section_df, hide_index=True)

st.divider()
st.subheader("Data Freshness")
responsive_table(
    pd.DataFrame(freshness_rows),
    hide_index=True,
)

st.divider()
st.subheader("Data Sources")
responsive_table(
    pd.DataFrame(
        [
            {
                "Component": "Broker",
                "Source": "Supabase / broker_account.csv fallback",
            },
            {
                "Component": "Holdings",
                "Source": "Supabase / holdings_report.csv fallback",
            },
            {
                "Component": "Trade Journal",
                "Source": "Supabase / trade_journal_v3.csv fallback",
            },
            {
                "Component": "Trade Audit",
                "Source": "derived from current journal / CSV fallback",
            },
            {
                "Component": "Analytics",
                "Source": "trade_analytics_v3.csv",
            },
            {
                "Component": "Snapshots",
                "Source": "trade_snapshots.csv",
            },
        ]
    ),
    hide_index=True,
)

warnings_df = checks_df[checks_df["Status"].isin([WARNING, CRITICAL])]

st.divider()
st.subheader("Warnings")

if warnings_df.empty:
    st.success("No warnings detected.")
else:
    responsive_table(warnings_df, hide_index=True)
