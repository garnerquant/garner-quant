from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pandas as pd

from execution.atomic_io import atomic_write_csv_frames


LEDGER_FILE = "trade_ledger_v1.csv"

LEDGER_COLUMNS = [
    "event_id",
    "timestamp",
    "trade_date",
    "trade_time",
    "ticker",
    "action",
    "shares",
    "price",
    "value",
    "fees",
    "currency",
    "source",
    "mode",
    "status",
    "reason",
    "legacy_trade_id",
    "run_id",
    "position_id",
    "pnl",
    "pnl_percent",
    "created_at",
    "legacy_source_file",
    "legacy_row_number",
    "migration_status",
    "quarantine_reason",
]

REQUIRED_EVENT_FIELDS = [
    "event_id",
    "timestamp",
    "ticker",
    "action",
    "shares",
    "price",
    "value",
    "fees",
    "currency",
    "source",
    "mode",
    "status",
]


class TradeLedgerError(ValueError):
    pass


def _clean_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _safe_float(value, default=0.0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


def event_signature(event):
    parts = [
        _clean_text(event.get("mode")),
        _clean_text(event.get("source")),
        _clean_text(event.get("ticker")).upper(),
        _clean_text(event.get("action")).upper(),
        _clean_text(event.get("timestamp")),
        f"{_safe_float(event.get('shares')):.12f}",
        f"{_safe_float(event.get('price')):.12f}",
        f"{_safe_float(event.get('value')):.12f}",
        f"{_safe_float(event.get('fees')):.12f}",
        _clean_text(event.get("currency")).upper(),
        _clean_text(event.get("legacy_trade_id")),
    ]
    return "|".join(parts)


def build_event_id(event):
    digest = sha256(event_signature(event).encode("utf-8")).hexdigest()
    return f"te_{digest[:24]}"


def normalise_trade_event(event):
    normalised = {column: event.get(column, "") for column in LEDGER_COLUMNS}
    normalised["ticker"] = _clean_text(normalised["ticker"]).upper()
    normalised["action"] = _clean_text(normalised["action"]).upper()
    normalised["source"] = _clean_text(normalised["source"]) or "unknown"
    normalised["mode"] = _clean_text(normalised["mode"]) or "paper"
    normalised["status"] = _clean_text(normalised["status"]) or "RECORDED"
    normalised["currency"] = _clean_text(normalised["currency"]) or "UNKNOWN"
    normalised["shares"] = _safe_float(normalised["shares"])
    normalised["price"] = _safe_float(normalised["price"])
    normalised["value"] = _safe_float(normalised["value"])
    normalised["fees"] = _safe_float(normalised["fees"])
    normalised["pnl"] = _safe_float(normalised["pnl"])
    normalised["pnl_percent"] = _safe_float(normalised["pnl_percent"])

    if not _clean_text(normalised["created_at"]):
        normalised["created_at"] = datetime.now().isoformat(timespec="seconds")

    if not _clean_text(normalised["event_id"]):
        normalised["event_id"] = build_event_id(normalised)

    validate_trade_event(normalised)
    return normalised


def build_trade_event(
    *,
    timestamp,
    trade_date,
    trade_time,
    ticker,
    action,
    shares,
    price,
    value,
    currency,
    reason,
    legacy_trade_id,
    run_id,
    position_id="",
    fees=0.0,
    source="portfolio_manager",
    mode="paper",
    status="RECORDED",
    pnl=0.0,
    pnl_percent=0.0,
    legacy_source_file="",
    legacy_row_number="",
    migration_status="LIVE",
    quarantine_reason="",
):
    return normalise_trade_event(
        {
            "timestamp": timestamp,
            "trade_date": trade_date,
            "trade_time": trade_time,
            "ticker": ticker,
            "action": action,
            "shares": shares,
            "price": price,
            "value": value,
            "fees": fees,
            "currency": currency,
            "source": source,
            "mode": mode,
            "status": status,
            "reason": reason,
            "legacy_trade_id": legacy_trade_id,
            "run_id": run_id,
            "position_id": position_id,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "legacy_source_file": legacy_source_file,
            "legacy_row_number": legacy_row_number,
            "migration_status": migration_status,
            "quarantine_reason": quarantine_reason,
        }
    )


def validate_trade_event(event):
    missing = [
        field
        for field in REQUIRED_EVENT_FIELDS
        if not _clean_text(event.get(field))
    ]
    if missing:
        raise TradeLedgerError(
            "Trade event is missing required fields: " + ", ".join(missing)
        )

    action = _clean_text(event.get("action")).upper()
    if action not in {"BUY", "SELL"}:
        raise TradeLedgerError(f"Unsupported trade action: {action}")

    status = _clean_text(event.get("status")).upper()
    if status not in {"RECORDED", "CANCELLED", "REJECTED", "ERROR"}:
        raise TradeLedgerError(f"Unsupported trade status: {status}")

    for field in ["shares", "price", "value", "fees"]:
        value = _safe_float(event.get(field))
        if value < 0:
            raise TradeLedgerError(f"Trade event field {field} cannot be negative")

    if _safe_float(event.get("shares")) <= 0:
        raise TradeLedgerError("Trade event shares must be positive")
    if _safe_float(event.get("price")) <= 0:
        raise TradeLedgerError("Trade event price must be positive")
    if _safe_float(event.get("value")) <= 0:
        raise TradeLedgerError("Trade event value must be positive")


def load_trade_ledger(path=LEDGER_FILE):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    try:
        ledger = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    for column in LEDGER_COLUMNS:
        if column not in ledger.columns:
            ledger[column] = ""

    return ledger[LEDGER_COLUMNS]


def _duplicate_reasons(existing, events):
    reasons = []
    event_ids = set(existing.get("event_id", pd.Series(dtype=str)).dropna().astype(str))
    legacy_trade_ids = {
        _clean_text(value)
        for value in existing.get("legacy_trade_id", pd.Series(dtype=str)).dropna()
        if _clean_text(value)
    }
    signatures = {
        event_signature(row)
        for _, row in existing.iterrows()
        if _clean_text(row.get("event_id"))
    }
    batch_ids = set()
    batch_legacy_trade_ids = set()
    batch_signatures = set()

    for event in events:
        event_id = _clean_text(event.get("event_id"))
        legacy_trade_id = _clean_text(event.get("legacy_trade_id"))
        signature = event_signature(event)

        if event_id in event_ids or event_id in batch_ids:
            reasons.append(f"duplicate event_id {event_id}")
        if legacy_trade_id and (
            legacy_trade_id in legacy_trade_ids
            or legacy_trade_id in batch_legacy_trade_ids
        ):
            reasons.append(f"duplicate legacy_trade_id {legacy_trade_id}")
        if signature in signatures or signature in batch_signatures:
            reasons.append(f"duplicate event signature for {event_id}")

        batch_ids.add(event_id)
        if legacy_trade_id:
            batch_legacy_trade_ids.add(legacy_trade_id)
        batch_signatures.add(signature)

    return reasons


def prepare_trade_ledger_append(events, path=LEDGER_FILE):
    normalised_events = [normalise_trade_event(event) for event in events]
    if not normalised_events:
        return load_trade_ledger(path)

    existing = load_trade_ledger(path)
    duplicate_reasons = _duplicate_reasons(existing, normalised_events)
    if duplicate_reasons:
        raise TradeLedgerError(
            "Trade ledger duplicate protection refused write: "
            + "; ".join(duplicate_reasons)
        )

    updated = pd.concat(
        [existing, pd.DataFrame(normalised_events, columns=LEDGER_COLUMNS)],
        ignore_index=True,
    )
    return updated[LEDGER_COLUMNS]


def append_trade_events(events, path=LEDGER_FILE):
    updated = prepare_trade_ledger_append(events, path=path)
    atomic_write_csv_frames({Path(path): updated})
    return updated
