from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
import json
import os
import smtplib
import sys

import requests


STATE_FILE = Path("data/notification_state.json")
DEFAULT_COOLDOWN_MINUTES = 30

PAPER_ACTION = "Would exit now if live execution was enabled."


def _now():
    return datetime.now()


def _now_iso():
    return _now().isoformat(timespec="seconds")


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_money(value):
    numeric_value = _safe_float(value)

    if numeric_value is None:
        return "Unavailable"

    return f"\u00a3{numeric_value:,.2f}"


def _format_number(value, decimals=2):
    numeric_value = _safe_float(value)

    if numeric_value is None:
        return None

    return f"{numeric_value:,.{decimals}f}"


def _format_percent(value):
    numeric_value = _safe_float(value)

    if numeric_value is None:
        return None

    return f"{numeric_value * 100:.1f}%"


def _format_time(value):
    timestamp = value or _now_iso()

    try:
        return datetime.fromisoformat(str(timestamp)).strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return str(timestamp)


def _console_log(message):
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_message = str(message).encode(
        encoding,
        errors="replace",
    ).decode(encoding, errors="replace")
    print(safe_message)


def _secret(name, default=None):
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        return st.secrets.get(name, default)
    except Exception:
        return default


def telegram_configured():
    return bool(
        _secret("TELEGRAM_BOT_TOKEN")
        and _secret("TELEGRAM_CHAT_ID")
    )


def email_configured():
    return bool(
        (_secret("EMAIL_SMTP_HOST") or _secret("SMTP_HOST"))
        and (_secret("EMAIL_SMTP_PORT") or _secret("SMTP_PORT", "587"))
        and (_secret("EMAIL_USERNAME") or _secret("SMTP_USERNAME"))
        and (_secret("EMAIL_PASSWORD") or _secret("SMTP_PASSWORD"))
        and _secret("EMAIL_TO")
    )


def _default_state():
    return {
        "sent_alerts": {},
        "sent_trades": {},
        "last_notification_sent": None,
        "last_monitor_alert_sent": None,
        "last_trade_notification_sent": None,
        "last_notification_error": None,
        "sent_log": [],
        "last_summary": None,
        "last_trade_summary": None,
    }


def load_notification_state(path=STATE_FILE):
    path = Path(path)

    if not path.exists():
        return _default_state()

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    defaults = _default_state()
    for key, value in defaults.items():
        state.setdefault(key, value)

    return state


def save_notification_state(state, path=STATE_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def alert_dedup_key(alert):
    ticker = str(alert.get("ticker", "")).strip()
    alert_type = str(alert.get("alert_type", "")).strip()
    trigger_price = _safe_float(alert.get("trigger_price"))
    trigger_label = (
        "missing"
        if trigger_price is None
        else f"{trigger_price:.6f}"
    )
    return f"{ticker}|{alert_type}|{trigger_label}"


def trade_dedup_key(trade_event):
    for field in ["transaction_id", "journal_event_id", "trade_id"]:
        value = trade_event.get(field)
        if value is not None and str(value).strip():
            return f"{field}:{value}"

    timestamp = (
        trade_event.get("timestamp")
        or f"{trade_event.get('date', '')} {trade_event.get('time', '')}"
    )
    price = (
        trade_event.get("price")
        or trade_event.get("entry_price")
        or trade_event.get("exit_price")
    )
    parts = [
        trade_event.get("action"),
        trade_event.get("ticker"),
        timestamp,
        price,
        trade_event.get("shares"),
    ]
    return "trade:" + "|".join(str(part).strip() for part in parts)


def is_in_cooldown(alert, state, cooldown_minutes=DEFAULT_COOLDOWN_MINUTES):
    key = alert_dedup_key(alert)
    last_sent = state.get("sent_alerts", {}).get(key)

    if not last_sent:
        return False

    try:
        last_sent_at = datetime.fromisoformat(last_sent)
    except ValueError:
        return False

    return _now() - last_sent_at < timedelta(minutes=cooldown_minutes)


def build_alert_message(alert):
    ticker = alert.get("ticker", "Unknown")
    alert_type = alert.get("alert_type", "ALERT")

    return (
        "\U0001f534 Garner Quant Paper Alert\n\n"
        f"Ticker: {ticker}\n"
        f"Alert: {alert_type}\n"
        f"Current Price: {_format_money(alert.get('current_price'))}\n"
        f"Trigger Price: {_format_money(alert.get('trigger_price'))}\n"
        f"Unrealised PnL: {_format_money(alert.get('unrealised_pnl'))}\n\n"
        "Action:\n"
        f"{PAPER_ACTION}\n\n"
        "Time:\n"
        f"{_format_time(alert.get('timestamp'))}"
    )


def _append_optional(lines, label, value):
    if value is not None and value != "Unavailable" and str(value).strip():
        lines.append(f"{label}: {value}")


def build_trade_message(trade_event):
    action = str(trade_event.get("action", "")).upper()
    ticker = trade_event.get("ticker", "Unknown")
    timestamp = _format_time(
        trade_event.get("timestamp")
        or " ".join(
            str(part)
            for part in [
                trade_event.get("date", ""),
                trade_event.get("time", ""),
            ]
            if str(part).strip()
        )
    )

    if action == "BUY":
        lines = [
            "\U0001f7e2 Garner Quant Trade Alert",
            "",
            "Action: BUY",
            f"Ticker: {ticker}",
        ]
        _append_optional(
            lines,
            "Entry Price",
            _format_money(trade_event.get("entry_price", trade_event.get("price"))),
        )
        _append_optional(lines, "Shares", _format_number(trade_event.get("shares")))
        _append_optional(
            lines,
            "Position Value",
            _format_money(
                trade_event.get("position_value", trade_event.get("value"))
            ),
        )
        _append_optional(lines, "Stop Loss", _format_money(trade_event.get("stop_loss")))
        _append_optional(
            lines,
            "Take Profit",
            _format_money(trade_event.get("take_profit")),
        )
        reason = (
            trade_event.get("reason_detail")
            or "Strategy generated a BUY/HOLD signal and portfolio allocation "
            "approved the position."
        )
        justification = trade_event.get("justification") or [
            "Signal passed",
            "Weight assigned",
            "Risk level available",
            "Position added to paper portfolio",
        ]
    else:
        lines = [
            "\U0001f534 Garner Quant Trade Alert",
            "",
            "Action: SELL",
            f"Ticker: {ticker}",
        ]
        _append_optional(
            lines,
            "Exit Price",
            _format_money(trade_event.get("exit_price", trade_event.get("price"))),
        )
        _append_optional(lines, "Shares", _format_number(trade_event.get("shares")))
        _append_optional(
            lines,
            "Realised PnL",
            _format_money(trade_event.get("pnl")),
        )
        _append_optional(
            lines,
            "Return",
            _format_percent(
                trade_event.get("return", trade_event.get("pnl_percent"))
            ),
        )
        _append_optional(lines, "Holding Period", trade_event.get("holding_period"))
        reason = (
            trade_event.get("reason_detail")
            or "Position was closed by sell signal / stop loss / take profit "
            "/ rebalance."
        )
        justification = trade_event.get("justification") or [
            "Exit condition triggered",
            "Trade recorded in journal",
            "Portfolio updated",
        ]

    lines.extend(["", "Reason:", reason, "", "Justification:"])

    if isinstance(justification, str):
        lines.append(justification)
    else:
        for item in justification:
            if str(item).strip():
                lines.append(f"- {item}")

    lines.extend(["", "Time:", timestamp])
    return "\n".join(lines)


def _send_telegram_message(message, label):
    token = _secret("TELEGRAM_BOT_TOKEN")
    chat_id = _secret("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        _console_log("Telegram not configured.")
        _console_log(f"{label} fallback:")
        _console_log(message)
        return {
            "channel": "telegram",
            "sent": False,
            "skipped": True,
            "reason": "missing_credentials",
        }

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message,
            },
            timeout=10,
        )
        response.raise_for_status()
        return {
            "channel": "telegram",
            "sent": True,
            "skipped": False,
            "reason": None,
        }
    except Exception as exc:
        return {
            "channel": "telegram",
            "sent": False,
            "skipped": False,
            "reason": str(exc),
        }


def _send_email_message(message_text, subject):
    host = _secret("EMAIL_SMTP_HOST") or _secret("SMTP_HOST")
    port = _secret("EMAIL_SMTP_PORT") or _secret("SMTP_PORT", "587")
    username = _secret("EMAIL_USERNAME") or _secret("SMTP_USERNAME")
    password = _secret("EMAIL_PASSWORD") or _secret("SMTP_PASSWORD")
    sender = _secret("EMAIL_FROM") or username
    recipient = _secret("EMAIL_TO")

    if not all([host, port, username, password, sender, recipient]):
        return {
            "channel": "email",
            "sent": False,
            "skipped": True,
            "reason": "missing_credentials",
        }

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(message_text)

    try:
        with smtplib.SMTP(host, int(port), timeout=10) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)

        return {
            "channel": "email",
            "sent": True,
            "skipped": False,
            "reason": None,
        }
    except Exception as exc:
        return {
            "channel": "email",
            "sent": False,
            "skipped": False,
            "reason": str(exc),
        }


def send_telegram_alert(alert):
    return _send_telegram_message(build_alert_message(alert), "Paper alert")


def send_email_alert(alert):
    return _send_email_message(
        build_alert_message(alert),
        "Garner Quant Paper Alert",
    )


def send_telegram_trade_event(trade_event):
    return _send_telegram_message(build_trade_message(trade_event), "Trade alert")


def notify_plain_message(message, label="Telegram message"):
    result = _send_telegram_message(message, label)

    return {
        "sent": 1 if result["sent"] else 0,
        "skipped": 1 if result["skipped"] else 0,
        "errors": [] if result["sent"] or result["skipped"] else [result["reason"]],
        "channel": result["channel"],
        "reason": result["reason"],
    }


def send_email_trade_event(trade_event):
    return _send_email_message(
        build_trade_message(trade_event),
        "Garner Quant Trade Alert",
    )


def _notifications_sent_today(state):
    today = _now().date()
    sent_today = 0

    for row in state.get("sent_log", []):
        timestamp = row.get("timestamp")
        try:
            if datetime.fromisoformat(timestamp).date() == today:
                sent_today += 1
        except Exception:
            continue

    return sent_today


def notification_status(path=STATE_FILE):
    state = load_notification_state(path)
    return {
        "telegram_configured": telegram_configured(),
        "email_configured": email_configured(),
        "last_notification_sent": state.get("last_notification_sent"),
        "last_monitor_alert_sent": state.get("last_monitor_alert_sent"),
        "last_trade_notification_sent": state.get("last_trade_notification_sent"),
        "last_notification_error": state.get("last_notification_error"),
        "notifications_sent_today": _notifications_sent_today(state),
        "last_summary": state.get("last_summary") or {},
        "last_trade_summary": state.get("last_trade_summary") or {},
    }


def _empty_summary(state):
    return {
        "sent": 0,
        "skipped": 0,
        "errors": [],
        "last_notification_sent": state.get("last_notification_sent"),
        "notifications_sent_today": _notifications_sent_today(state),
        "skipped_due_to_cooldown": 0,
        "skipped_due_to_deduplication": 0,
    }


def _deliver(message, telegram_sender, email_sender, item_label):
    channel_results = [
        telegram_sender(),
        email_sender(),
    ]
    channel_sent = any(result["sent"] for result in channel_results)
    fallback_sent = (
        not channel_sent
        and channel_results
        and all(result["skipped"] for result in channel_results)
    )
    errors = []

    for result in channel_results:
        if result["sent"] or result["skipped"]:
            continue

        errors.append(f"{result['channel']}: {result['reason']}")

    if not channel_sent and not fallback_sent:
        _console_log(f"No notification channel delivered {item_label}. Fallback:")
        _console_log(message)

    return channel_sent, fallback_sent, errors


def notify_alerts(
    alerts,
    cooldown_minutes=DEFAULT_COOLDOWN_MINUTES,
    state_path=STATE_FILE,
):
    state = load_notification_state(state_path)
    summary = _empty_summary(state)

    if not alerts:
        state["last_summary"] = summary
        save_notification_state(state, state_path)
        return summary

    for alert in alerts:
        key = alert_dedup_key(alert)

        if is_in_cooldown(alert, state, cooldown_minutes):
            summary["skipped"] += 1
            summary["skipped_due_to_cooldown"] += 1
            continue

        message = build_alert_message(alert)
        channel_sent, fallback_sent, errors = _deliver(
            message,
            lambda alert=alert: send_telegram_alert(alert),
            lambda alert=alert: send_email_alert(alert),
            "paper alert",
        )

        for error in errors:
            summary["errors"].append(
                f"{alert.get('ticker', 'Unknown')} {error}"
            )

        if channel_sent or fallback_sent:
            sent_at = _now_iso()
            state["sent_alerts"][key] = sent_at
            state["last_notification_sent"] = sent_at
            state["last_monitor_alert_sent"] = sent_at
            state.setdefault("sent_log", []).append(
                {
                    "timestamp": sent_at,
                    "type": "monitor_alert",
                    "ticker": alert.get("ticker"),
                    "alert_type": alert.get("alert_type"),
                    "trigger_price": alert.get("trigger_price"),
                    "delivery": "channel" if channel_sent else "fallback",
                }
            )
            summary["sent"] += 1
        else:
            summary["skipped"] += 1

    if summary["errors"]:
        state["last_notification_error"] = summary["errors"][-1]

    summary["last_notification_sent"] = state.get("last_notification_sent")
    summary["notifications_sent_today"] = _notifications_sent_today(state)
    state["last_summary"] = summary
    save_notification_state(state, state_path)
    return summary


def notify_trade_event(trade_event, state_path=STATE_FILE):
    return notify_trade_events([trade_event], state_path=state_path)


def notify_trade_events(trade_events, state_path=STATE_FILE):
    state = load_notification_state(state_path)
    summary = _empty_summary(state)

    if not trade_events:
        state["last_trade_summary"] = summary
        save_notification_state(state, state_path)
        return summary

    for trade_event in trade_events:
        key = trade_dedup_key(trade_event)

        if key in state.get("sent_trades", {}):
            summary["skipped"] += 1
            summary["skipped_due_to_deduplication"] += 1
            continue

        message = build_trade_message(trade_event)
        channel_sent, fallback_sent, errors = _deliver(
            message,
            lambda trade_event=trade_event: send_telegram_trade_event(trade_event),
            lambda trade_event=trade_event: send_email_trade_event(trade_event),
            "trade alert",
        )

        for error in errors:
            summary["errors"].append(
                f"{trade_event.get('ticker', 'Unknown')} {error}"
            )

        if channel_sent or fallback_sent:
            sent_at = _now_iso()
            state["sent_trades"][key] = sent_at
            state["last_notification_sent"] = sent_at
            state["last_trade_notification_sent"] = sent_at
            state.setdefault("sent_log", []).append(
                {
                    "timestamp": sent_at,
                    "type": "trade_event",
                    "action": trade_event.get("action"),
                    "ticker": trade_event.get("ticker"),
                    "trade_key": key,
                    "delivery": "channel" if channel_sent else "fallback",
                }
            )
            summary["sent"] += 1
        else:
            summary["skipped"] += 1

    if summary["errors"]:
        state["last_notification_error"] = summary["errors"][-1]

    summary["last_notification_sent"] = state.get("last_notification_sent")
    summary["notifications_sent_today"] = _notifications_sent_today(state)
    state["last_trade_summary"] = summary
    save_notification_state(state, state_path)
    return summary
