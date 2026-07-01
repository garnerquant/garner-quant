from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import json
import sys
import time as time_module
import traceback


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from execution.live_market_monitor import (  # noqa: E402
    load_current_holding_tickers,
    run_live_market_monitor,
)
from notifications.alert_notifier import notify_alerts  # noqa: E402


CONFIG_FILE = ROOT_DIR / "runtime" / "live_runtime_config.json"
STATUS_FILE = ROOT_DIR / "data" / "live_runtime_status.json"
EXECUTION_LOG_FILE = ROOT_DIR / "data" / "live_runtime_execution_log.json"
OPERATIONS_LOG_FILE = ROOT_DIR / "data" / "runtime_operations_log.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "mode": "monitor_only",
    "allowed_modes": ["monitor_only", "paper_execution"],
    "cycle_seconds": 300,
    "markets": ["LSE", "US", "TSE"],
    "send_notifications": True,
    "paper_execution_enabled": False,
}

MARKET_SESSIONS = {
    "LSE": {
        "timezone": "Europe/London",
        "open": time(8, 0),
        "close": time(16, 30),
    },
    "US": {
        "timezone": "America/New_York",
        "open": time(9, 30),
        "close": time(16, 0),
    },
    "TSE": {
        "timezone": "Asia/Tokyo",
        "open": time(9, 0),
        "close": time(15, 0),
    },
}


def utc_now():
    return datetime.now(ZoneInfo("UTC"))


def iso_timestamp(value=None):
    value = value or utc_now()
    return value.isoformat(timespec="seconds")


def load_config(path=CONFIG_FILE):
    path = Path(path)

    if not path.exists():
        config = dict(DEFAULT_CONFIG)
        config["_config_exists"] = False
        return config

    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        config = {}

    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    merged["_config_exists"] = True
    return merged


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        return str(value)


def runtime_event(event_type, message, severity="info", details=None, now=None):
    return {
        "timestamp": iso_timestamp(now),
        "type": event_type,
        "severity": severity,
        "message": message,
        "details": json_safe(details or {}),
    }


def append_event(events, event_type, message, severity="info", details=None, now=None):
    event = runtime_event(
        event_type,
        message,
        severity=severity,
        details=details,
        now=now,
    )
    events.append(event)
    return event


def load_status(path=STATUS_FILE):
    path = Path(path)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_execution_log(path=EXECUTION_LOG_FILE):
    path = Path(path)

    if not path.exists():
        return {
            "last_execution_at": None,
            "executions": [],
        }

    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log = {}

    log.setdefault("last_execution_at", None)
    log.setdefault("executions", [])
    return log


def save_execution_log(log, path=EXECUTION_LOG_FILE):
    save_json(log, path)


def load_operations_log(path=OPERATIONS_LOG_FILE):
    path = Path(path)

    if not path.exists():
        return {
            "cycles": [],
        }

    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log = {}

    log.setdefault("cycles", [])
    return log


def save_operations_log(log, path=OPERATIONS_LOG_FILE):
    log["cycles"] = log.get("cycles", [])[-500:]
    save_json(log, path)


def append_operations_log(entry):
    try:
        log = load_operations_log()
        log.setdefault("cycles", []).append(entry)
        save_operations_log(log)
    except Exception:
        pass


def get_recent_cycles(limit=20):
    cycles = load_operations_log().get("cycles", [])
    return list(reversed(cycles[-limit:]))


def get_last_cycle():
    cycles = load_operations_log().get("cycles", [])
    return cycles[-1] if cycles else None


def get_runtime_statistics():
    cycles = load_operations_log().get("cycles", [])
    today = utc_now().date()
    total_cycles = len(cycles)
    successful_cycles = len(
        [
            cycle
            for cycle in cycles
            if cycle.get("status") == "success"
        ]
    )
    failed_cycles = len(
        [
            cycle
            for cycle in cycles
            if cycle.get("status") == "error"
        ]
    )
    durations = [
        float(cycle.get("duration_seconds", 0) or 0)
        for cycle in cycles
    ]
    notifications = [
        float(cycle.get("notifications_sent", 0) or 0)
        for cycle in cycles
    ]
    trades = [
        float(cycle.get("trades_recorded", 0) or 0)
        for cycle in cycles
    ]
    strategy_durations = [
        float(
            (cycle.get("execution_summary") or {}).get(
                "execution_time_seconds",
                0,
            )
            or 0
        )
        for cycle in cycles
        if cycle.get("paper_execution_completed")
    ]
    successful_runs = [
        cycle.get("finished_at")
        for cycle in cycles
        if cycle.get("status") == "success"
    ]
    today_cycles = []
    for cycle in cycles:
        try:
            finished_at = datetime.fromisoformat(cycle.get("finished_at", ""))
        except Exception:
            continue

        if finished_at.astimezone(ZoneInfo("UTC")).date() == today:
            today_cycles.append(cycle)

    today_strategy_runs = len(
        [
            cycle
            for cycle in today_cycles
            if cycle.get("paper_execution_completed")
        ]
    )
    today_paper_trades = sum(
        int(cycle.get("trades_recorded", 0) or 0)
        for cycle in today_cycles
    )
    today_notifications = sum(
        int(cycle.get("notifications_sent", 0) or 0)
        for cycle in today_cycles
    )
    today_errors = len(
        [cycle for cycle in today_cycles if cycle.get("status") == "error"]
    )

    return {
        "total_cycles": total_cycles,
        "successful_cycles": successful_cycles,
        "failed_cycles": failed_cycles,
        "average_cycle_duration": (
            sum(durations) / total_cycles
            if total_cycles
            else 0
        ),
        "average_notifications": (
            sum(notifications) / total_cycles
            if total_cycles
            else 0
        ),
        "average_trades": (
            sum(trades) / total_cycles
            if total_cycles
            else 0
        ),
        "last_successful_run": successful_runs[-1] if successful_runs else None,
        "today_strategy_runs": today_strategy_runs,
        "today_paper_trades": today_paper_trades,
        "today_notifications": today_notifications,
        "today_runtime_errors": today_errors,
        "average_strategy_runtime": (
            sum(strategy_durations) / len(strategy_durations)
            if strategy_durations
            else 0
        ),
        "longest_runtime": max(durations) if durations else 0,
    }


def write_status(update, path=STATUS_FILE):
    status = load_status(path)
    status.update(update)
    save_json(status, path)
    try:
        from execution.supabase_sync import sync_runtime_status

        sync_runtime_status(path)
    except Exception as exc:
        print(f"Warning: runtime status Supabase mirror failed: {exc}")
    return status


def execution_id(now, markets_open):
    market_key = "-".join(markets_open) if markets_open else "none"
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}_{market_key}"


def append_execution_log(entry):
    log = load_execution_log()
    log["last_execution_at"] = entry.get("timestamp")
    log.setdefault("executions", []).append(entry)
    log["executions"] = log["executions"][-200:]
    save_execution_log(log)
    return log


def market_for_ticker(ticker):
    ticker = str(ticker or "").strip().upper()

    if ticker.endswith(".L"):
        return "LSE"

    if ticker.endswith(".T"):
        return "TSE"

    if ticker and "." not in ticker:
        return "US"

    return "UNKNOWN"


def markets_for_holdings(tickers):
    markets = set()
    unknown = []

    for ticker in tickers:
        market = market_for_ticker(ticker)
        if market == "UNKNOWN":
            unknown.append(str(ticker))
        else:
            markets.add(market)

    if unknown:
        markets.update(["LSE", "US", "TSE"])

    return sorted(markets), unknown


def is_session_open(market, now=None):
    session = MARKET_SESSIONS.get(market)

    if session is None:
        return False

    now = now or utc_now()
    local_now = now.astimezone(ZoneInfo(session["timezone"]))

    if local_now.weekday() >= 5:
        return False

    return session["open"] <= local_now.time() <= session["close"]


def open_markets(markets, now=None):
    return [
        market
        for market in markets
        if is_session_open(market, now=now)
    ]


def empty_notification_summary():
    return {
        "sent": 0,
        "skipped": 0,
        "errors": [],
        "skipped_due_to_cooldown": 0,
        "skipped_due_to_deduplication": 0,
    }


def build_cycle_explanation(
    markets_open,
    mode,
    blocked_reason,
    execution_entry,
    alerts_found,
    error=None,
):
    if error:
        return {
            "cycle_summary": "Runtime cycle failed.",
            "reason": str(error),
            "action_taken": "No further action was taken during this cycle.",
            "next_expected_action": (
                "Review logs and fix the error before relying on live runtime."
            ),
        }

    if not markets_open:
        return {
            "cycle_summary": (
                "Runtime completed successfully. No markets were open."
            ),
            "reason": "All configured markets were closed during this cycle.",
            "action_taken": "No monitoring or paper execution was required.",
            "next_expected_action": (
                "Runtime will check again on the next scheduled cycle."
            ),
        }

    if blocked_reason:
        if mode == "monitor_only":
            return {
                "cycle_summary": (
                    "Runtime completed successfully in monitor-only mode."
                ),
                "reason": "Market was open, but paper execution is disabled.",
                "action_taken": (
                    "Live holdings were monitored and paper alerts were checked."
                ),
                "next_expected_action": (
                    "Enable Paper Execution Mode only when ready for automatic "
                    "paper trading."
                ),
            }

        return {
            "cycle_summary": "Paper execution was blocked by safety controls.",
            "reason": blocked_reason,
            "action_taken": "No paper trades were created.",
            "next_expected_action": (
                "Review runtime config if paper execution should be enabled."
            ),
        }

    trades_recorded = (
        execution_entry.get("trades_recorded", 0)
        if execution_entry is not None
        else 0
    )

    if trades_recorded > 0:
        return {
            "cycle_summary": (
                "Strategy ran successfully and recorded paper trades."
            ),
            "reason": (
                "New BUY/SELL actions were generated by the strategy pipeline."
            ),
            "action_taken": (
                "Paper portfolio was updated and trade notifications were sent."
            ),
            "next_expected_action": (
                "Review trade notifications and dashboard positions."
            ),
        }

    if execution_entry is not None:
        return {
            "cycle_summary": (
                "Strategy ran successfully. No new paper trades were needed."
            ),
            "reason": "No qualifying BUY or SELL actions were generated.",
            "action_taken": (
                "Strategy pipeline completed and portfolio remained unchanged."
            ),
            "next_expected_action": (
                "Runtime will continue monitoring on the next cycle."
            ),
        }

    return {
        "cycle_summary": "Runtime completed successfully.",
        "reason": "No runtime action required during this cycle.",
        "action_taken": (
            "Runtime checked market state and maintained heartbeat data."
        ),
        "next_expected_action": (
            "Runtime will check again on the next scheduled cycle."
        ),
    }


def paper_execution_blocked_reason(
    config,
    markets_open,
    execution_log=None,
    now=None,
):
    allowed_modes = config.get("allowed_modes", [])
    mode = config.get("mode")
    execution_log = execution_log or {}
    now = now or utc_now()

    if not config.get("_config_exists", False):
        return "config missing"

    if mode not in allowed_modes:
        return f"mode {mode} is not allowed"

    if mode != "paper_execution":
        return f"mode is {mode}"

    if config.get("paper_execution_enabled") is not True:
        return "paper_execution_enabled is false"

    if not markets_open:
        return "market closed"

    last_execution_at = execution_log.get("last_execution_at")
    if last_execution_at:
        try:
            last_execution = datetime.fromisoformat(last_execution_at)
            elapsed = (now - last_execution).total_seconds()
            if elapsed < int(config.get("cycle_seconds", 300)):
                return "already executed within current cycle"
        except Exception:
            pass

    return None


def run_paper_execution(now, markets_open, mode, events=None):
    events = events if events is not None else []
    execution_started = time_module.perf_counter()
    entry = {
        "execution_id": execution_id(now, markets_open),
        "timestamp": iso_timestamp(now),
        "mode": mode,
        "markets_open": markets_open,
        "symbols_scanned": 0,
        "signals_count": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "hold_signals": 0,
        "trades_recorded": 0,
        "paper_trades": 0,
        "portfolio_changed": False,
        "decision_trace_count": 0,
        "no_trade_count": 0,
        "trade_count": 0,
        "top_no_trade_reasons": {},
        "notifications_sent": 0,
        "execution_time_seconds": 0,
        "latest_paper_trade": None,
        "status": "started",
        "error": None,
    }
    append_event(
        events,
        "Strategy Started",
        "Started autonomous paper strategy pipeline.",
        details={"markets_open": markets_open},
        now=now,
    )

    try:
        from main_v2 import main as run_daily_pipeline

        result = run_daily_pipeline(
            show_charts=False,
            send_telegram=False,
            sync_remote=False,
        )
        result = result or {}
        for event in result.get("events", []):
            append_event(
                events,
                event.get("type", "Strategy Event"),
                event.get("message", "Strategy pipeline event."),
                severity=event.get("severity", "info"),
                details=event.get("details", {}),
            )
        entry.update(
            {
                "symbols_scanned": int(result.get("symbols_scanned", 0)),
                "signals_count": int(result.get("signals_count", 0)),
                "buy_signals": int(result.get("buy_signals", 0)),
                "sell_signals": int(result.get("sell_signals", 0)),
                "hold_signals": int(result.get("hold_signals", 0)),
                "trades_recorded": int(result.get("trades_recorded", 0)),
                "paper_trades": int(result.get("paper_trades", 0)),
                "portfolio_changed": bool(result.get("portfolio_changed", False)),
                "decision_trace_count": int(
                    result.get("decision_trace_count", 0) or 0
                ),
                "no_trade_count": int(result.get("no_trade_count", 0) or 0),
                "trade_count": int(result.get("trade_count", 0) or 0),
                "top_no_trade_reasons": json_safe(
                    result.get("top_no_trade_reasons", {})
                ),
                "notifications_sent": int(
                    result.get(
                        "notifications_sent",
                        result.get("trade_notifications_sent", 0),
                    )
                ),
                "execution_time_seconds": float(
                    result.get(
                        "execution_time_seconds",
                        time_module.perf_counter() - execution_started,
                    )
                    or 0
                ),
                "latest_paper_trade": json_safe(result.get("latest_paper_trade")),
                "status": "success",
            }
        )
        append_event(
            events,
            "Decision Trace Created",
            (
                f"{entry['decision_trace_count']} decisions traced. "
                f"{entry['trades_recorded']} trades recorded."
            ),
            details={
                "decision_trace_count": entry["decision_trace_count"],
                "no_trade_count": entry["no_trade_count"],
                "trade_count": entry["trade_count"],
                "top_no_trade_reasons": entry["top_no_trade_reasons"],
            },
        )
        append_event(
            events,
            "Strategy Completed",
            "Autonomous paper strategy pipeline completed.",
            details={
                "paper_trades": entry["paper_trades"],
                "notifications_sent": entry["notifications_sent"],
            },
        )
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        entry["execution_time_seconds"] = round(
            time_module.perf_counter() - execution_started,
            2,
        )
        append_event(
            events,
            "Runtime Error",
            "Strategy pipeline failed; runtime will retry next cycle.",
            severity="error",
            details={
                "exception_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    entry = json_safe(entry)
    append_execution_log(entry)
    return entry


def run_cycle(config, started_at, cycle_count):
    now = utc_now()
    cycle_started_at = now
    cycle_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{cycle_count}"
    events = []
    append_event(
        events,
        "Runtime Resumed",
        "Runtime cycle started.",
        details={"cycle_id": cycle_id},
        now=now,
    )
    save_execution_log(load_execution_log())
    tickers = load_current_holding_tickers()
    holding_markets, unknown_tickers = markets_for_holdings(tickers)
    configured_markets = set(config.get("markets", []))
    markets_checked = sorted(set(holding_markets) & configured_markets)

    if not markets_checked:
        markets_checked = sorted(configured_markets)

    markets_open = open_markets(markets_checked, now=now)
    if markets_open:
        append_event(
            events,
            "Market Session Open",
            f"{', '.join(markets_open)} session open.",
            details={"markets_open": markets_open},
            now=now,
        )
    else:
        append_event(
            events,
            "Runtime Sleeping",
            "No configured markets are open.",
            details={"markets_checked": markets_checked},
            now=now,
        )
    should_monitor = bool(markets_open)
    monitor_result = None
    notification_summary = empty_notification_summary()
    last_error = None
    execution_entry = None
    execution_log = load_execution_log()
    blocked_reason = paper_execution_blocked_reason(
        config,
        markets_open,
        execution_log=execution_log,
        now=now,
    )

    if config.get("enabled", True) and should_monitor:
        append_event(
            events,
            "Monitor Started",
            "Refreshing live monitor snapshot.",
            details={"markets_open": markets_open},
        )
        monitor_result = run_live_market_monitor(save_snapshot=True)
        alerts = monitor_result.get("alerts", [])
        append_event(
            events,
            "Monitor Completed",
            "Live holdings monitored and paper alerts checked.",
            details={
                "holdings_monitored": monitor_result.get(
                    "holdings_monitored",
                    0,
                ),
                "alerts_found": len(alerts),
            },
        )

        if config.get("send_notifications", True) and alerts:
            notification_summary = notify_alerts(alerts)
            append_event(
                events,
                "Telegram Notification Sent",
                "Sent live monitor paper alert notifications.",
                details=notification_summary,
            )

    if blocked_reason is None:
        execution_entry = run_paper_execution(
            now,
            markets_open,
            config.get("mode", "monitor_only"),
            events=events,
        )
        if execution_entry.get("status") == "error":
            last_error = execution_entry.get("error")
    else:
        append_event(
            events,
            "Paper Execution Blocked",
            "Paper execution did not run because safety controls blocked it.",
            severity="warning" if markets_open else "info",
            details={"reason": blocked_reason},
        )

    next_cycle_at = now + timedelta(
        seconds=int(config.get("cycle_seconds", 300))
    )
    holdings_monitored = (
        monitor_result.get("holdings_monitored", 0)
        if monitor_result is not None
        else 0
    )
    alerts_found = (
        len(monitor_result.get("alerts", []))
        if monitor_result is not None
        else 0
    )
    signals_generated = (
        execution_entry.get("signals_count", 0)
        if execution_entry is not None
        else 0
    )
    symbols_scanned = (
        execution_entry.get("symbols_scanned", len(tickers))
        if execution_entry is not None
        else len(tickers)
    )
    buy_signals = (
        execution_entry.get("buy_signals", 0)
        if execution_entry is not None
        else 0
    )
    sell_signals = (
        execution_entry.get("sell_signals", 0)
        if execution_entry is not None
        else 0
    )
    hold_signals = (
        execution_entry.get("hold_signals", 0)
        if execution_entry is not None
        else 0
    )
    trades_recorded = (
        execution_entry.get("trades_recorded", 0)
        if execution_entry is not None
        else 0
    )
    paper_execution_attempted = blocked_reason is None
    paper_execution_completed = (
        execution_entry is not None
        and execution_entry.get("status") == "success"
    )
    notifications_sent = (
        notification_summary.get("sent", 0)
        + (
            execution_entry.get("notifications_sent", 0)
            if execution_entry is not None
            else 0
        )
    )
    explanation = build_cycle_explanation(
        markets_open,
        config.get("mode", "monitor_only"),
        blocked_reason,
        execution_entry,
        alerts_found,
        error=last_error,
    )
    latest_event = events[-1] if events else None
    latest_paper_trade = (
        execution_entry.get("latest_paper_trade")
        if execution_entry is not None
        else None
    )
    current_stage = (
        latest_event.get("type")
        if latest_event
        else "Runtime Sleeping"
    )

    status = {
        "status": "running" if config.get("enabled", True) else "stopped",
        "mode": config.get("mode", "monitor_only"),
        "started_at": started_at,
        "last_cycle_at": iso_timestamp(now),
        "next_cycle_at": iso_timestamp(next_cycle_at),
        "cycle_count": cycle_count,
        "markets_checked": markets_checked,
        "markets_open": markets_open,
        "unknown_tickers": unknown_tickers,
        "holdings_monitored": holdings_monitored,
        "alerts_found": alerts_found,
        "notifications_sent": notifications_sent,
        "notification_summary": notification_summary,
        "current_strategy_stage": current_stage,
        "latest_runtime_event": latest_event,
        "latest_paper_trade": latest_paper_trade,
        "paper_execution_enabled": bool(
            config.get("paper_execution_enabled", False)
        ),
        "paper_execution_blocked_reason": blocked_reason,
        "last_execution_at": (
            execution_entry.get("timestamp")
            if execution_entry is not None
            else execution_log.get("last_execution_at")
        ),
        "last_execution_status": (
            execution_entry.get("status")
            if execution_entry is not None
            else None
        ),
        "trades_recorded_last_cycle": (
            execution_entry.get("trades_recorded", 0)
            if execution_entry is not None
            else 0
        ),
        "execution_summary": (
            {
                "symbols_scanned": symbols_scanned,
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "hold_signals": hold_signals,
                "paper_trades": trades_recorded,
                "portfolio_changed": bool(
                    execution_entry.get("portfolio_changed", False)
                    if execution_entry is not None
                    else False
                ),
                "decision_trace_count": (
                    execution_entry.get("decision_trace_count", 0)
                    if execution_entry is not None
                    else 0
                ),
                "no_trade_count": (
                    execution_entry.get("no_trade_count", 0)
                    if execution_entry is not None
                    else 0
                ),
                "trade_count": (
                    execution_entry.get("trade_count", 0)
                    if execution_entry is not None
                    else 0
                ),
                "top_no_trade_reasons": (
                    execution_entry.get("top_no_trade_reasons", {})
                    if execution_entry is not None
                    else {}
                ),
                "notifications_sent": (
                    execution_entry.get("notifications_sent", 0)
                    if execution_entry is not None
                    else 0
                ),
                "execution_time_seconds": (
                    execution_entry.get("execution_time_seconds", 0)
                    if execution_entry is not None
                    else 0
                ),
            }
            if execution_entry is not None
            else None
        ),
        "execution_log_count": len(execution_log.get("executions", []))
        + (1 if execution_entry is not None else 0),
        "last_error": last_error,
        "paper_only": True,
    }
    write_status(json_safe(status))

    cycle_finished_at = utc_now()
    duration_seconds = (
        cycle_finished_at - cycle_started_at
    ).total_seconds()
    append_operations_log(
        {
            "cycle_id": cycle_id,
            "started_at": iso_timestamp(cycle_started_at),
            "finished_at": iso_timestamp(cycle_finished_at),
            "duration_seconds": round(duration_seconds, 2),
            "mode": config.get("mode", "monitor_only"),
            "markets_checked": markets_checked,
            "markets_open": markets_open,
            "symbols_scanned": symbols_scanned,
            "holdings_monitored": holdings_monitored,
            "signals_generated": signals_generated,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "hold_signals": hold_signals,
            "paper_execution_attempted": paper_execution_attempted,
            "paper_execution_completed": paper_execution_completed,
            "trades_recorded": trades_recorded,
            "alerts_found": alerts_found,
            "notifications_sent": notifications_sent,
            "execution_summary": status.get("execution_summary"),
            "events": events,
            "status": "error" if last_error else "success",
            "error": last_error,
            **explanation,
        }
    )
    return status


def mark_error(started_at, cycle_count, exc, config):
    now = utc_now()
    finished_at = utc_now()
    duration_seconds = (finished_at - now).total_seconds()
    next_cycle_at = now + timedelta(
        seconds=int(config.get("cycle_seconds", 300))
    )
    error = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "stack_trace": traceback.format_exc(),
    }
    events = [
        runtime_event(
            "Runtime Error",
            "Runtime cycle failed; runtime will retry next cycle.",
            severity="error",
            details=error,
            now=now,
        )
    ]
    explanation = build_cycle_explanation(
        [],
        config.get("mode", "monitor_only"),
        None,
        None,
        0,
        error=str(exc),
    )
    append_operations_log(
        {
            "cycle_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}_{cycle_count}",
            "started_at": iso_timestamp(now),
            "finished_at": iso_timestamp(finished_at),
            "duration_seconds": round(duration_seconds, 2),
            "mode": config.get("mode", "monitor_only"),
            "markets_checked": [],
            "markets_open": [],
            "symbols_scanned": 0,
            "holdings_monitored": 0,
            "signals_generated": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "hold_signals": 0,
            "paper_execution_attempted": False,
            "paper_execution_completed": False,
            "trades_recorded": 0,
            "alerts_found": 0,
            "notifications_sent": 0,
            "execution_summary": None,
            "events": events,
            "status": "error",
            "error": error,
            **explanation,
        }
    )
    return write_status(
        {
            "status": "error",
            "mode": config.get("mode", "monitor_only"),
            "started_at": started_at,
            "last_cycle_at": iso_timestamp(now),
            "next_cycle_at": iso_timestamp(next_cycle_at),
            "cycle_count": cycle_count,
            "current_strategy_stage": "Runtime Error",
            "latest_runtime_event": events[-1],
            "last_error": str(exc),
            "paper_only": True,
        }
    )


def mark_stopped(started_at, cycle_count):
    return write_status(
        {
            "status": "stopped",
            "started_at": started_at,
            "last_cycle_at": iso_timestamp(),
            "next_cycle_at": None,
            "cycle_count": cycle_count,
            "paper_only": True,
        }
    )


def run_runtime(run_once=False):
    config = load_config()
    started_at = iso_timestamp()
    cycle_count = 0
    save_execution_log(load_execution_log())
    start_event = runtime_event(
        "Runtime Started",
        "Live runtime worker started.",
        details={"mode": config.get("mode", "monitor_only")},
    )

    write_status(
        {
            "status": "running" if config.get("enabled", True) else "stopped",
            "mode": config.get("mode", "monitor_only"),
            "started_at": started_at,
            "last_cycle_at": None,
            "next_cycle_at": started_at,
            "cycle_count": 0,
            "markets_checked": [],
            "markets_open": [],
            "holdings_monitored": 0,
            "alerts_found": 0,
            "notifications_sent": 0,
            "current_strategy_stage": "Runtime Started",
            "latest_runtime_event": start_event,
            "latest_paper_trade": None,
            "paper_execution_enabled": bool(
                config.get("paper_execution_enabled", False)
            ),
            "paper_execution_blocked_reason": None,
            "last_execution_at": load_execution_log().get("last_execution_at"),
            "last_execution_status": None,
            "trades_recorded_last_cycle": 0,
            "execution_log_count": len(load_execution_log().get("executions", [])),
            "last_error": None,
            "paper_only": True,
        }
    )

    try:
        while True:
            config = load_config()
            cycle_count += 1

            try:
                status = run_cycle(config, started_at, cycle_count)
            except Exception as exc:
                status = mark_error(started_at, cycle_count, exc, config)

            print(json.dumps(status, indent=2))

            if run_once:
                mark_stopped(started_at, cycle_count)
                break

            sleep_seconds = max(1, int(config.get("cycle_seconds", 300)))
            time_module.sleep(sleep_seconds)
    except KeyboardInterrupt:
        mark_stopped(started_at, cycle_count)
        print("Live runtime stopped.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Garner Quant live runtime worker."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle then exit. Useful for validation.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_runtime(run_once=args.once)
