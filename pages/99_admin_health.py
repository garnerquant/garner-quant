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
    last_cycle_at = parse_timestamp(runtime_status.get("last_cycle_at"))
    if last_cycle_at is None:
        return "No heartbeat", False

    cycle_seconds = int(runtime_status.get("cycle_seconds", 300) or 300)
    threshold_seconds = max((cycle_seconds * 2) + 60, 600)
    now = pd.Timestamp.now(tz="Europe/London")
    is_healthy = (now - last_cycle_at).total_seconds() <= threshold_seconds
    return ("Healthy" if is_healthy else "Stale"), is_healthy


def heartbeat_age_label(runtime_status):
    last_cycle_at = parse_timestamp(runtime_status.get("last_cycle_at"))
    if last_cycle_at is None:
        return "Unknown"

    now = pd.Timestamp.now(tz="Europe/London")
    return format_runtime_duration((now - last_cycle_at).total_seconds())


def runtime_banner_state(runtime_status, heartbeat_ok):
    status = runtime_status.get("status", "not started")
    markets_open = safe_list(runtime_status.get("markets_open"))

    if status == "error":
        return "error", "🔴 Runtime Error", "Runtime reported an error."

    if status == "running" and heartbeat_ok and markets_open:
        return "live", "🟢 LIVE", "Runtime Running"

    if status == "running" and heartbeat_ok:
        return "waiting", "🟡 Waiting for Market", "Runtime Running"

    return "offline", "🔴 Runtime Offline", "Background runtime is not running."


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
    next_cycle = parse_timestamp(runtime_status.get("next_cycle_at"))
    if next_cycle is None:
        return "None"

    return next_cycle.strftime("%H:%M:%S")


def next_cycle_delta(runtime_status):
    next_cycle = parse_timestamp(runtime_status.get("next_cycle_at"))
    if next_cycle is None:
        return "Not scheduled"

    now = pd.Timestamp.now(tz="Europe/London")
    seconds = int((next_cycle - now).total_seconds())
    if seconds <= 0:
        return "due now"

    return f"in {format_runtime_duration(seconds)}"


def paper_execution_enabled(runtime_status, runtime_config):
    return bool(
        runtime_status.get("paper_execution_enabled")
        or runtime_config.get("paper_execution_enabled")
    )


def activity_state(runtime_status, runtime_config, heartbeat_ok, markets):
    status = runtime_status.get("status", "not started")
    mode = runtime_status.get("mode") or runtime_config.get("mode") or "monitor_only"
    markets_open = safe_list(runtime_status.get("markets_open"))
    paper_enabled = paper_execution_enabled(runtime_status, runtime_config)
    next_market_name, next_market_seconds = next_market_details(markets)
    stage = runtime_status.get("current_strategy_stage")

    if status == "error":
        return {
            "level": "error",
            "title": "🔴 Runtime Error",
            "current_activity": "Attention required.",
            "next_label": "Last Error",
            "next_value": runtime_status.get("last_error") or "Unknown runtime error.",
            "command": None,
        }

    if status != "running" or not heartbeat_ok:
        return {
            "level": "offline",
            "title": "🔴 Runtime Offline",
            "current_activity": "Not running",
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
            "title": "🟡 Waiting for Market",
            "current_activity": "Sleeping / waiting",
            "next_label": "Next Market",
            "next_value": next_market_text,
            "command": None,
        }

    if paper_enabled and mode == "paper_execution":
        return {
            "level": "live",
            "title": "🟢 Paper Trading Active",
            "current_activity": (
                stage
                or "Running strategy pipeline during open market sessions."
            ),
            "next_label": "Paper Only",
            "next_value": "Yes",
            "command": None,
        }

    return {
        "level": "live",
        "title": "🟢 Monitoring Live Markets",
        "current_activity": "Monitoring holdings and checking paper alerts.",
        "next_label": "Mode",
        "next_value": "Monitor Only",
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
runtime_status = load_json_file("data/live_runtime_status.json")
runtime_config = load_json_file("runtime/live_runtime_config.json")
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

st.markdown("**Live Event Feed**")
event_feed = build_live_event_feed(recent_cycles, limit=20)
if event_feed:
    responsive_table(pd.DataFrame(event_feed), hide_index=True)
else:
    st.info("No runtime events have been recorded yet.")

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

if not heartbeat_ok:
    st.warning(
        "Runtime heartbeat is stale or missing. Restart the runtime from the "
        "terminal or with systemd on the VPS."
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

if live_time_mode:
    refresh_seconds = min(30, int(refresh_interval) * 60)
    st.markdown(
        f"<meta http-equiv='refresh' content='{refresh_seconds}'>",
        unsafe_allow_html=True,
    )

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
