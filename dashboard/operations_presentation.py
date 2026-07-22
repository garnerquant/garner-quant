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
    "approved": ("Approved", "green", "Approved"),
    "information": ("Information", "blue", "Information"),
    "recent": ("Recent", "blue", "Recent"),
    "observing": ("Observing", "blue", "Observing"),
    "no_action": ("No action", "blue", "No action"),
    "pending": ("Pending", "amber", "Pending"),
    "pending_review": ("Pending review", "amber", "Pending review"),
    "not_ready": ("Not ready", "amber", "Not ready"),
    "stale": ("Stale", "amber", "Stale"),
    "awaiting": ("Awaiting", "amber", "Awaiting"),
    "not_frozen": ("Not Frozen", "amber", "Not frozen"),
    "gaps_identified": ("Incomplete", "amber", "Incomplete"),
    "conflict": ("Conflict", "red", "Conflict"),
    "rejected": ("Rejected", "red", "Rejected"),
    "critical": ("Critical", "red", "Critical"),
    "error": ("Problem", "red", "Problem"),
    "failed": ("Problem", "red", "Problem"),
    "failed_final": ("Failed", "red", "Failed"),
    "failed_retryable": ("Failed", "red", "Failed"),
    "executed": ("Executed", "green", "Executed"),
    "inactive": ("Inactive", "grey", "Inactive"),
    "disabled": ("Disabled", "grey", "Disabled"),
    "monitor_only": ("Monitor-only", "grey", "Monitor-only"),
    "unsupported": ("Unsupported", "grey", "Unsupported"),
    "not_configured": ("Not configured", "grey", "Not configured"),
    "absent": ("Absent", "grey", "Absent"),
    "valid": ("Valid", "green", "Valid"),
    "live": ("Live", "green", "Live"),
    "execution_blocked": ("Execution disabled", "grey", "Execution disabled"),
    "unknown": ("Unknown", "grey", "Unknown"),
}


def _key(value):
    return str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")


def status_meta(value):
    return STATUS_META.get(_key(value), (str(value or "Unknown").replace("_", " ").title(), "grey", str(value or "Unknown")))


def badge_color(tone):
    return {"green": "green", "blue": "blue", "amber": "orange", "red": "red", "grey": "gray"}.get(str(tone), "gray")


def compact_time(value, fallback="Not available"):
    if value is None or str(value).strip() in {"", "None", "nan"}: return fallback
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None: return fallback
        local = timestamp.astimezone(ZoneInfo("Europe/London"))
        return local.strftime("%H:%M" if local.date() == datetime.now(ZoneInfo("Europe/London")).date() else "%d %b")
    except (TypeError, ValueError, OverflowError):
        return fallback


def compact_date(value, fallback="Not available"):
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
        if "reconciled" in lowered: status, tone, tooltip = "Reconciled", "green", "This source agrees with the authoritative local report."
        elif source == "Supabase": status, tone, tooltip = "Remote", "blue", "This source is currently read from the remote data service."
        elif "fallback" in lowered: status, tone, tooltip = "Fallback", "amber", "The primary source is unavailable and the local fallback is displayed."
        elif "unavailable" in lowered: status, tone, tooltip = "Not available", "red", "No readable source is currently available."
        else: status, tone, tooltip = "Unknown", "grey", "The source status is not configured."
        timestamp = detail.get("remote_timestamp") if source == "Supabase" else detail.get("local_timestamp")
        rows.append({"Source": labels[key], "Status": status, "Tone": tone, "Tooltip": tooltip, "Last Refresh": compact_time(timestamp)})
    return rows


def instrument_status_rows(instruments):
    rows = []
    for symbol, record in sorted(instruments.items()):
        raw = str(record.get("status", "UNKNOWN")); display, tone, _ = status_meta(raw)
        failure = str(record.get("failure_reason") or "").strip().lower()
        if raw == "EXECUTION_BLOCKED" and "monitor_only" in failure:
            reason = "Monitor-only mode"
            tooltip = "Execution is disabled because monitor-only mode evaluates without submitting orders."
        elif raw == "NO_ACTION": reason = "Strategy conditions"
        elif failure: reason = failure.replace("_", " ").capitalize()
        else: reason = "Completed"
        if not (raw == "EXECUTION_BLOCKED" and "monitor_only" in failure):
            tooltip = "The status reflects the recorded scheduler outcome for this completed bar."
        identity = record.get("identity") or {}
        rows.append({"Instrument": symbol, "Status": display, "Tone": tone, "Tooltip": tooltip, "Reason": reason,
                     "Last Bar": compact_date(identity.get("bar_close_utc"))})
    return rows


def status_table_html(rows, columns, *, caption):
    head = "".join(f"<th scope=\"col\">{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = []
        for column in columns:
            raw_value = row.get(column)
            value = html.escape("Not available" if raw_value in (None, "", "Unavailable") else str(raw_value))
            if column == "Status":
                tone = html.escape(str(row.get("Tone", "grey")))
                tooltip = html.escape(str(row.get("Tooltip", "")))
                tooltip_attributes = f' tabindex="0" title="{tooltip}" aria-label="Status: {value}. {tooltip}"' if tooltip else f' aria-label="Status: {value}"'
                value = f'<span class="ops-badge ops-{tone}"{tooltip_attributes}>{value}</span>'
            cells.append(f'<td data-label="{html.escape(column)}">{value}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="ops-table-wrap"><table class="ops-table"><caption>{html.escape(caption)}</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def summary_cards_html(cards, *, aria_label):
    values = []
    for card in cards:
        label = html.escape(str(card["label"])); raw_value = card.get("value")
        value = html.escape("Not available" if raw_value in (None, "", "Unavailable") else str(raw_value))
        tone = html.escape(str(card.get("tone", "grey"))); help_text = html.escape(str(card.get("help", "")))
        context = html.escape(str(card.get("context", "")))
        tooltip = f' title="{help_text}" aria-label="{label}: {value}. {help_text}"' if help_text else f' aria-label="{label}: {value}"'
        context_markup = f'<div class="ops-card-context">{context}</div>' if context else ""
        values.append(f'<div class="ops-summary-card ops-card-{tone}" tabindex="0"{tooltip}><div class="ops-card-label">{label}</div><div class="ops-card-value">{value}</div>{context_markup}</div>')
    return f'<div class="ops-summary-grid" role="group" aria-label="{html.escape(aria_label)}">{"".join(values)}</div>'


def activity_cards_html(cards):
    values = []
    for card in cards:
        icon = html.escape(str(card.get("icon", "•"))); title = html.escape(str(card["title"]))
        event = html.escape(str(card.get("event", "No activity"))); context = html.escape(str(card.get("context", "")))
        timestamp = html.escape("Not available" if card.get("timestamp") in (None, "", "Unavailable") else str(card.get("timestamp")))
        tone = html.escape(str(card.get("tone", "grey")))
        context_markup = f'<div class="ops-activity-context">{context}</div>' if context else ""
        values.append(f'<article class="ops-activity-card ops-card-{tone}" aria-label="{title} activity"><div class="ops-activity-title"><span aria-hidden="true">{icon}</span>{title}</div><div class="ops-activity-event">{event}</div>{context_markup}<time class="ops-activity-time">{timestamp}</time></article>')
    return '<div class="ops-activity-grid">' + "".join(values) + "</div>"


def operational_summary_html(title, status, description, details, *, tone="grey", help_text=""):
    """Render a concise home-page answer while preserving detail elsewhere."""
    safe_title = html.escape(str(title)); safe_status = html.escape(str(status))
    safe_description = html.escape(str(description)); safe_tone = html.escape(str(tone))
    tooltip = html.escape(str(help_text))
    attributes = (
        f' tabindex="0" title="{tooltip}" aria-label="{safe_title}: {safe_status}. {tooltip}"'
        if tooltip else f' aria-label="{safe_title}: {safe_status}"'
    )
    detail_markup = "".join(
        f'<div class="ops-summary-detail"><span>{html.escape(str(label))}</span>'
        f'<strong>{html.escape("Not available" if value in (None, "", "Unavailable") else str(value))}</strong></div>'
        for label, value in details
    )
    return (
        f'<section class="ops-home-summary ops-card-{safe_tone}"{attributes}>'
        f'<div class="ops-home-summary-heading">{safe_title}</div>'
        f'<div class="ops-home-summary-status">{safe_status}</div>'
        f'<p>{safe_description}</p><div class="ops-summary-details">{detail_markup}</div></section>'
    )


def data_health_summary(rows):
    total = len(rows); healthy = sum(row.get("Status") == "Reconciled" for row in rows)
    refreshes = sorted(row.get("Last Refresh") for row in rows if row.get("Last Refresh") not in (None, "", "Not available"))
    return {
        "status": "All sources reconciled" if total and healthy == total else "Source attention required",
        "tone": "green" if total and healthy == total else "amber",
        "healthy": f"{healthy} / {total} healthy",
        "last_updated": refreshes[-1] if refreshes else "Not available",
    }


def trading_status_summary(rows, *, unavailable=False):
    total = len(rows)
    waiting = sum(row.get("Status") == "Execution disabled" for row in rows)
    no_action = sum(row.get("Status") == "No action" for row in rows)
    errors = sum(row.get("Tone") == "red" for row in rows)
    return {
        "status": "Not available" if unavailable else "Monitor-only",
        "tone": "red" if unavailable or errors else "grey",
        "monitored": total,
        "waiting": waiting,
        "no_action": no_action,
        "errors": errors,
    }


def detail_rows(values, labels):
    """Turn dense mappings into a scan-friendly label/value table."""
    rows = []
    for key, label in labels:
        value = values.get(key)
        if value in (None, "", "Unavailable"):
            value = "Not available"
        elif not isinstance(value, str):
            value = str(value)
        rows.append({"Item": label, "Value": value})
    return rows
