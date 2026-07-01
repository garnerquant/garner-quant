import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_STATUS = ROOT / "data" / "live_runtime_status.json"

load_dotenv()


def _supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


def _load_supabase_runtime_status():
    client = _supabase_client()
    if client is None:
        return {}

    try:
        response = (
            client.table("runtime_status")
            .select("*")
            .eq("id", "live")
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def _load_local_runtime_status(path=LOCAL_RUNTIME_STATUS):
    path = Path(path)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_runtime_status():
    status = _load_supabase_runtime_status()
    if status:
        status["_runtime_source"] = "supabase"
        return status

    status = _load_local_runtime_status()
    status["_runtime_source"] = "local_json"
    return status


def runtime_status_updated_at(status):
    if status.get("_runtime_source") == "supabase":
        value = status.get("updated_at")
        if not value:
            return ""
        try:
            return pd.to_datetime(value, utc=True).tz_convert(None)
        except Exception:
            return value

    if LOCAL_RUNTIME_STATUS.exists():
        return pd.Timestamp.fromtimestamp(LOCAL_RUNTIME_STATUS.stat().st_mtime)

    return ""


def _parse_time(value):
    if not value:
        return None

    try:
        if isinstance(value, pd.Timestamp):
            timestamp = value
        else:
            timestamp = pd.to_datetime(value, utc=True)

        if timestamp.tzinfo is None:
            return timestamp.tz_localize("Europe/London")

        return timestamp.tz_convert("Europe/London")
    except Exception:
        return None

def _latest_timestamp(*values):
    parsed = [timestamp for timestamp in (_parse_time(value) for value in values) if timestamp is not None]
    return max(parsed) if parsed else None


def _duration_label(seconds):
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


def freshness_for_timestamp(value):
    timestamp = _parse_time(value)
    if timestamp is None:
        return {
            "label": "Missing",
            "badge": "Missing",
            "level": "missing",
            "age": "Missing",
            "age_seconds": None,
            "timestamp": None,
        }

    now = pd.Timestamp.now(tz="Europe/London")
    age_seconds = max(0, int((now - timestamp).total_seconds()))
    age = f"{_duration_label(age_seconds)} ago"

    if age_seconds <= 60:
        label = "Live"
        level = "live"
    elif age_seconds <= 5 * 60:
        label = "Recent"
        level = "recent"
    elif age_seconds <= 15 * 60:
        label = "Slightly stale"
        level = "slightly-stale"
    elif age_seconds <= 60 * 60:
        label = "Stale"
        level = "stale"
    else:
        label = "Very stale"
        level = "very-stale"

    return {
        "label": label,
        "badge": label,
        "level": level,
        "age": age,
        "age_seconds": age_seconds,
        "timestamp": timestamp,
    }


def runtime_freshness(status):
    latest_event = status.get("latest_runtime_event") or {}
    candidates = [
        status.get("updated_at"),
        status.get("last_cycle_at"),
        latest_event.get("timestamp"),
    ]

    if status.get("_runtime_source") == "local_json":
        candidates.append(runtime_status_updated_at(status))

    return freshness_for_timestamp(_latest_timestamp(*candidates))


def runtime_heartbeat(status):
    last_cycle_at = _parse_time(status.get("last_cycle_at"))
    if last_cycle_at is None:
        return {
            "label": "No heartbeat",
            "healthy": False,
            "level": "missing",
            "age": "Unknown",
            "age_seconds": None,
        }

    now = pd.Timestamp.now(tz="Europe/London")
    age_seconds = max(0, int((now - last_cycle_at).total_seconds()))
    cycle_seconds = int(status.get("cycle_seconds", 300) or 300)
    next_cycle_at = _parse_time(status.get("next_cycle_at"))
    delayed_after_seconds = max(cycle_seconds * 3, 900)
    overdue_after_seconds = max(cycle_seconds * 6, 1800)

    if age_seconds >= overdue_after_seconds:
        label = "Overdue"
        level = "overdue"
        healthy = False
    elif age_seconds >= delayed_after_seconds:
        label = "Delayed"
        level = "delayed"
        healthy = True
    else:
        label = "Healthy"
        level = "healthy"
        healthy = True

    return {
        "label": label,
        "display": label,
        "healthy": healthy,
        "level": level,
        "age": _duration_label(age_seconds),
        "age_seconds": age_seconds,
        "delayed_after_seconds": delayed_after_seconds,
        "overdue_after_seconds": overdue_after_seconds,
        "next_cycle_seconds": (
            int((next_cycle_at - now).total_seconds())
            if next_cycle_at is not None
            else None
        ),
    }


def runtime_stage(status):
    stage_text = " ".join(
        [
            str(status.get("current_strategy_stage") or ""),
            str((status.get("latest_runtime_event") or {}).get("type") or ""),
        ]
    ).lower()

    if "strategy completed" in stage_text or "completed" in stage_text:
        return "Sleep"
    if "runtime started" in stage_text or "resumed" in stage_text:
        return "Market Check"
    if "download" in stage_text or "price" in stage_text:
        return "Price Download"
    if "signal" in stage_text:
        return "Signal Generation"
    if "portfolio" in stage_text:
        return "Portfolio Decision"
    if "paper" in stage_text or "trade" in stage_text:
        return "Paper Execution"
    if "telegram" in stage_text or "notification" in stage_text:
        return "Telegram"
    if "market" in stage_text or "monitor" in stage_text:
        return "Market Check"
    if "sleep" in stage_text or "blocked" in stage_text:
        return "Sleep"
    return status.get("current_strategy_stage") or "Sleeping"


def runtime_next_cycle(status):
    next_cycle_at = _parse_time(status.get("next_cycle_at"))
    if next_cycle_at is None:
        return {
            "time": "None",
            "delta": "Not scheduled",
            "scan": "Not scheduled",
            "seconds": None,
        }

    now = pd.Timestamp.now(tz="Europe/London")
    seconds = int((next_cycle_at - now).total_seconds())
    stage = runtime_stage(status)
    active_stages = {
        "Market Check",
        "Price Download",
        "Signal Generation",
        "Portfolio Decision",
        "Paper Execution",
        "Telegram",
        "Running",
        "Scanning",
    }
    if seconds <= 0 and stage not in active_stages:
        scan = next_cycle_at.strftime("%H:%M:%S")
        delta = "Due now"
    elif seconds <= 0:
        scan = "Scanning..."
        delta = "Scanning..."
    else:
        minutes, remainder = divmod(seconds, 60)
        scan = (
            _duration_label(seconds)
            if minutes >= 60
            else f"{minutes:02d}m {remainder:02d}s"
        )
        delta = f"in {_duration_label(seconds)}"

    return {
        "time": next_cycle_at.strftime("%H:%M:%S"),
        "delta": delta,
        "scan": scan,
        "seconds": seconds,
    }


def runtime_state(status):
    raw_status = str(status.get("status") or "not started").lower()
    heartbeat = runtime_heartbeat(status)
    stage = runtime_stage(status)
    next_cycle = runtime_next_cycle(status)
    last_error = status.get("last_error")
    running = raw_status == "running"
    error = raw_status == "error" or bool(last_error)
    active_activity = {
        "Market Check": "Checking markets",
        "Price Download": "Downloading prices",
        "Signal Generation": "Generating signals",
        "Portfolio Decision": "Reviewing portfolio decisions",
        "Paper Execution": "Running paper execution",
        "Telegram": "Sending notifications",
        "Running": "Running",
        "Scanning": "Scanning",
    }

    if error:
        level = "error"
        title = "Runtime Error"
        banner = "Garner Quant Needs Attention"
        health = "Error"
        healthy = False
        activity = "Runtime reported an error."
        display_stage = "Runtime reported an error"
        next_scan_display = next_cycle["scan"]
    elif running:
        healthy = heartbeat["healthy"]
        if heartbeat["level"] == "overdue":
            health = "Runtime needs attention"
        elif heartbeat["level"] == "delayed":
            health = "Runtime delayed"
        else:
            health = "Running normally"
        if stage in {"Sleep", "Sleeping", "Strategy Completed", "Waiting", "Idle", "Market Closed"}:
            level = "idle"
            title = "Runtime Running"
            banner = "Garner Quant Sleeping"
            if next_cycle["delta"] == "Due now":
                activity = "Waiting for next cycle."
            elif next_cycle["time"] != "None":
                activity = "Sleeping until next scan."
            else:
                activity = "Running and waiting for the next scan."
            display_stage = activity.rstrip(".")
            next_scan_display = next_cycle["time"] if next_cycle["time"] != "None" else next_cycle["scan"]
        else:
            level = "live"
            title = "Runtime Running"
            banner = "Garner Quant Running"
            activity = f"{active_activity.get(stage, stage)}."
            display_stage = activity.rstrip(".")
            next_scan_display = next_cycle["scan"]
    else:
        level = "offline"
        title = "Runtime Offline"
        banner = "Garner Quant Offline"
        health = "Stopped"
        healthy = False
        activity = "Runtime is not running."
        display_stage = "Runtime stopped"
        next_scan_display = next_cycle["scan"]

    return {
        "raw_status": raw_status,
        "running": running,
        "level": level,
        "title": title,
        "banner": banner,
        "health": health,
        "healthy": healthy,
        "stage": stage,
        "display_stage": display_stage,
        "activity": activity,
        "heartbeat": heartbeat,
        "next_cycle": next_cycle,
        "next_scan_display": next_scan_display,
        "freshness": runtime_freshness(status),
        "last_cycle_at": status.get("last_cycle_at"),
        "next_cycle_at": status.get("next_cycle_at"),
        "last_error": last_error,
    }
