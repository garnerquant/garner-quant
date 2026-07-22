from __future__ import annotations

from collections import defaultdict, deque
from decimal import Decimal

import pandas as pd

from canonical_accounting.currency import CurrencyError, decimal_value
from canonical_accounting.generation import LEDGER_COLUMNS, SCHEMA_VERSION


class CanonicalLedgerError(ValueError):
    pass


def validate_event(event: dict) -> dict:
    missing = [column for column in LEDGER_COLUMNS if column not in event]
    if missing:
        raise CanonicalLedgerError(f"canonical ledger fields missing: {', '.join(missing)}")
    if str(event["schema_version"]) != SCHEMA_VERSION:
        raise CanonicalLedgerError("unsupported canonical ledger schema")
    if not str(event["accounting_generation"]).strip() or not str(event["event_id"]).strip():
        raise CanonicalLedgerError("generation and event ID are required")
    timestamp = pd.Timestamp(event["timestamp"])
    if timestamp.tzinfo is None:
        raise CanonicalLedgerError("canonical event timestamp must include timezone")
    quantity = decimal_value(event["quantity"], "quantity")
    if quantity < 0:
        raise CanonicalLedgerError("quantity must not be negative")
    for field in (
        "native_execution_price", "price_scale", "normalized_native_price",
        "native_gross_amount", "fee_amount", "fx_rate_to_base",
        "base_gross_amount", "base_fee",
    ):
        if decimal_value(event[field], field) < 0:
            raise CanonicalLedgerError(f"{field} must not be negative")
    return dict(event)


def append_event(frame: pd.DataFrame, event: dict) -> pd.DataFrame:
    event = validate_event(event)
    existing = frame.copy() if frame is not None else pd.DataFrame(columns=LEDGER_COLUMNS)
    if list(existing.columns) != LEDGER_COLUMNS:
        raise CanonicalLedgerError("canonical ledger schema mismatch")
    if str(event["event_id"]) in set(existing["event_id"].astype(str)):
        raise CanonicalLedgerError("duplicate canonical event ID")
    return pd.concat([existing, pd.DataFrame([event], columns=LEDGER_COLUMNS)], ignore_index=True)


def fifo_accounting(events: pd.DataFrame) -> dict:
    if list(events.columns) != LEDGER_COLUMNS:
        raise CanonicalLedgerError("canonical ledger schema mismatch")
    lots = defaultdict(deque)
    realised = Decimal("0")
    closed = []
    seen = set()
    ordered = events.copy()
    ordered["_timestamp"] = pd.to_datetime(ordered["timestamp"], errors="coerce", utc=True)
    if ordered["_timestamp"].isna().any():
        raise CanonicalLedgerError("malformed canonical event timestamp")
    ordered = ordered.sort_values(["_timestamp", "event_id"], kind="mergesort")
    for event in ordered.to_dict("records"):
        validate_event(event)
        event_id = str(event["event_id"])
        if event_id in seen:
            raise CanonicalLedgerError("duplicate canonical event ID")
        seen.add(event_id)
        kind = str(event["event_type"]).upper()
        if kind in {"OPENING_CASH", "GENERATION_INITIALIZATION", "DEPOSIT", "WITHDRAWAL", "FEE", "DIVIDEND", "FX_ADJUSTMENT", "CORPORATE_ACTION"}:
            continue
        symbol = str(event["symbol"])
        quantity = decimal_value(event["quantity"], "quantity")
        base_gross = decimal_value(event["base_gross_amount"], "base_gross_amount")
        base_fee = decimal_value(event["base_fee"], "base_fee")
        if kind in {"BUY", "BUY_FILL", "OPENING_POSITION"}:
            lots[symbol].append({
                "event_id": event_id,
                "remaining_quantity": quantity,
                "remaining_base_cost": base_gross + base_fee,
                "entry_fx_rate": decimal_value(event["fx_rate_to_base"], "fx_rate_to_base"),
            })
            continue
        if kind not in {"SELL", "SELL_FILL"}:
            raise CanonicalLedgerError(f"unsupported canonical event type: {kind}")
        remaining = quantity
        exit_fee_remaining = base_fee
        while remaining > 0:
            if not lots[symbol]:
                raise CanonicalLedgerError(f"SELL exceeds open quantity for {symbol}")
            lot = lots[symbol][0]
            matched = min(remaining, lot["remaining_quantity"])
            entry_cost = lot["remaining_base_cost"] * matched / lot["remaining_quantity"]
            proceeds = base_gross * matched / quantity
            exit_fee = exit_fee_remaining * matched / remaining
            pnl = proceeds - exit_fee - entry_cost
            realised += pnl
            closed.append({
                "exit_event_id": event_id, "entry_event_id": lot["event_id"],
                "symbol": symbol, "quantity": matched,
                "base_entry_cost": entry_cost, "base_exit_proceeds": proceeds,
                "base_exit_fee": exit_fee, "base_realised_pnl": pnl,
            })
            lot["remaining_quantity"] -= matched
            lot["remaining_base_cost"] -= entry_cost
            remaining -= matched
            exit_fee_remaining -= exit_fee
            if lot["remaining_quantity"] == 0:
                lots[symbol].popleft()
    open_lots = [dict(symbol=symbol, **lot) for symbol, queue in lots.items() for lot in queue]
    return {"base_realised_pnl": realised, "closed_matches": closed, "open_lots": open_lots}
