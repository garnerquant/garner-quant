"""Pure presentation helpers for compact operational dashboard views."""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

STATUS_META = {
    "healthy": ("Healthy", "green", "Healthy"),
    "reconciled": ("Reconciled", "green", "Reconciled"),
    "active": ("Active", "green", "Active"),
    "complete": ("Complete", "green", "Complete"),
    "information": ("Information", "blue", "Information"),
    "no_action": ("No Action", "blue", "No action"),
    "pending": ("Pending", "amber", "Pending"),
    "not_frozen": ("Not Frozen", "amber", "Not frozen"),
    "gaps_identified": ("Incomplete", "amber", "Incomplete"),
    "conflict": ("Conflict", "red", "Conflict"),
    "error": ("Problem", "red", "Problem"),
    "failed": ("Problem", "red", "Problem"),
    "inactive": ("Inactive", "grey", "Inactive"),
    "execution_blocked": ("Execution Disabled", "grey", "Execution disabled"),
    "unknown": ("Unknown", "grey", "Unknown"),
}


def _key(value):
    return str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")


def status_meta(value):
    return STATUS_META.get(_key(value), (str(value or "Unknown").replace("_", " ").title(), "grey", str(value or "Unknown")))


def compact_time(value, fallback="Unavailable"):
    if value is None or str(value).strip() in {"", "None", "nan"}: return fallback
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None: return fallback
        local = timestamp.astimezone(ZoneInfo("Europe/London"))
        return local.strftime("%H:%M" if local.date() == datetime.now(ZoneInfo("Europe/London")).date() else "%d %b")
    except (TypeError, ValueError, OverflowError):
        return fallback


def compact_date(value, fallback="Unavailable"):
    if value is None or str(value).strip() in {"", "None", "nan"}: return fallback
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None: return fallback
        return timestamp.astimezone(ZoneInfo("Europe/London")).strftime("%d %b")
    except (TypeError, ValueError, OverflowError):
        return fallback


def home_source_rows(details):
    labels = {"broker_account": "Broker", "paper_30_day_tracker": "Tracker", "holdings": "Holdings", "trade_journal": "Trades"}
    rows = []
    for key in ("broker_account", "trade_journal", "holdings", "paper_30_day_tracker"):
        detail = details.get(key, {}); source = str(detail.get("source", "unknown"))
        lowered = source.lower()
        if "reconciled" in lowered: status, tone = "Reconciled", "green"
        elif source == "Supabase": status, tone = "Remote", "blue"
        elif "fallback" in lowered: status, tone = "Fallback", "amber"
        elif "unavailable" in lowered: status, tone = "Unavailable", "red"
        else: status, tone = "Unknown", "grey"
        timestamp = detail.get("remote_timestamp") if source == "Supabase" else detail.get("local_timestamp")
        rows.append({"Source": labels[key], "Status": status, "Tone": tone, "Last Refresh": compact_time(timestamp)})
    return rows


def instrument_status_rows(instruments):
    rows = []
    for symbol, record in sorted(instruments.items()):
        raw = str(record.get("status", "UNKNOWN")); display, tone, _ = status_meta(raw)
        failure = str(record.get("failure_reason") or "").strip().lower()
        if raw == "EXECUTION_BLOCKED" and "monitor_only" in failure: reason = "Monitor-only mode"
        elif raw == "NO_ACTION": reason = "Strategy conditions"
        elif failure: reason = failure.replace("_", " ").capitalize()
        else: reason = "Completed"
        identity = record.get("identity") or {}
        rows.append({"Instrument": symbol, "Status": display, "Tone": tone, "Reason": reason,
                     "Last Bar": compact_date(identity.get("bar_close_utc"))})
    return rows


def status_table_html(rows, columns, *, caption):
    head = "".join(f"<th scope=\"col\">{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = html.escape(str(row.get(column, "Unavailable")))
            if column == "Status":
                tone = html.escape(str(row.get("Tone", "grey")))
                value = f'<span class="ops-badge ops-{tone}" aria-label="Status: {value}">{value}</span>'
            cells.append(f'<td data-label="{html.escape(column)}">{value}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="ops-table-wrap"><table class="ops-table"><caption>{html.escape(caption)}</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def summary_cards_html(cards, *, aria_label):
    values = []
    for card in cards:
        label = html.escape(str(card["label"])); value = html.escape(str(card.get("value", "Unavailable")))
        tone = html.escape(str(card.get("tone", "grey"))); help_text = html.escape(str(card.get("help", "")))
        tooltip = f' title="{help_text}" aria-label="{label}: {value}. {help_text}"' if help_text else f' aria-label="{label}: {value}"'
        values.append(f'<div class="ops-summary-card ops-card-{tone}" tabindex="0"{tooltip}><div class="ops-card-label">{label}</div><div class="ops-card-value">{value}</div></div>')
    return f'<div class="ops-summary-grid" role="group" aria-label="{html.escape(aria_label)}">{"".join(values)}</div>'


def activity_cards_html(cards):
    values = []
    for card in cards:
        icon = html.escape(str(card.get("icon", "•"))); title = html.escape(str(card["title"]))
        event = html.escape(str(card.get("event", "No activity"))); timestamp = html.escape(str(card.get("timestamp", "Unavailable")))
        values.append(f'<article class="ops-activity-card" aria-label="{title} activity"><div class="ops-activity-title"><span aria-hidden="true">{icon}</span>{title}</div><div class="ops-activity-event">{event}</div><time class="ops-activity-time">{timestamp}</time></article>')
    return '<div class="ops-activity-grid">' + "".join(values) + "</div>"


def detail_rows(values, labels):
    """Turn dense mappings into a scan-friendly label/value table."""
    return [{"Item": label, "Value": values.get(key) if values.get(key) not in (None, "") else "Unavailable"}
            for key, label in labels]
