from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from canonical_accounting.events import AccountingEventType
from canonical_accounting.instruments import get_instrument_metadata
from risk_engine.models import OrderProposal, RiskContext, RiskDecision
from risk_engine.configuration import load_risk_configuration
from runtime.locks import acquire_runtime_write_lock


SCHEMA_VERSION = "1.0"
DEFAULT_STORE = Path("data/accounting_observations/envelopes.jsonl")
DEFAULT_FAILURE_STORE = Path("data/accounting_observations/validation_failures.jsonl")


class AccountingObservationError(ValueError):
    pass


@dataclass(frozen=True)
class ReplayInstrumentMetadata:
    instrument_id: str
    price_precision: int
    quantity_precision: int
    minimum_lot: Decimal
    lot_increment: Decimal
    fractional_support: bool
    market_calendar: str
    timezone: str


# Explicit replay policy. Nothing here is inferred from ticker suffixes.
REPLAY_METADATA = {
    "GBP-CASH": ReplayInstrumentMetadata("instrument:GBP-CASH", 8, 8, Decimal("0.00000001"), Decimal("0.00000001"), True, "24/7", "UTC"),
    "EUR-CASH": ReplayInstrumentMetadata("instrument:EUR-CASH", 8, 8, Decimal("0.00000001"), Decimal("0.00000001"), True, "24/7", "UTC"),
    "BTC-GBP": ReplayInstrumentMetadata("instrument:BTC-GBP", 8, 12, Decimal("0.00000001"), Decimal("0.00000001"), True, "24/7", "UTC"),
    "ETH-GBP": ReplayInstrumentMetadata("instrument:ETH-GBP", 8, 12, Decimal("0.00000001"), Decimal("0.00000001"), True, "24/7", "UTC"),
    "IUSA.L": ReplayInstrumentMetadata("instrument:IUSA.L", 4, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XLON", "Europe/London"),
    "VWRL.L": ReplayInstrumentMetadata("instrument:VWRL.L", 4, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XLON", "Europe/London"),
    "SGLN.L": ReplayInstrumentMetadata("instrument:SGLN.L", 4, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XLON", "Europe/London"),
    "AAPL": ReplayInstrumentMetadata("instrument:AAPL", 6, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XNAS", "America/New_York"),
    "MSFT": ReplayInstrumentMetadata("instrument:MSFT", 6, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XNAS", "America/New_York"),
    "NVDA": ReplayInstrumentMetadata("instrument:NVDA", 6, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XNAS", "America/New_York"),
    "TSLA": ReplayInstrumentMetadata("instrument:TSLA", 6, 12, Decimal("0.000001"), Decimal("0.000001"), True, "XNAS", "America/New_York"),
}


def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingObservationError(f"{field} is invalid") from exc
    if not result.is_finite():
        raise AccountingObservationError(f"{field} must be finite")
    return result


def _utc(value, field):
    if value is None:
        raise AccountingObservationError(f"{field} is required")
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AccountingObservationError(f"{field} is invalid") from exc
    if result.tzinfo is None:
        raise AccountingObservationError(f"{field} must be timezone-aware")
    return result.astimezone(timezone.utc)


def _json(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict): return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [_json(item) for item in value]
    if hasattr(value, "value"): return value.value
    if isinstance(value, float) and not math.isfinite(value): raise AccountingObservationError("non-finite serialization value")
    return value


@dataclass(frozen=True)
class AccountingObservationEnvelope:
    schema_version: str
    event_id: str
    proposal_id: str
    decision_id: str
    strategy_id: str
    strategy_version: str
    instrument_id: str
    symbol: str
    market: str
    venue: str
    asset_class: str
    side: str
    event_type: str
    quantity: Decimal
    native_price: Decimal
    price_units: str
    native_currency: str
    base_currency: str
    fx_rate_to_base: Decimal
    fx_timestamp: datetime
    fx_source: str
    market_data_timestamp: datetime
    valuation_timestamp: datetime
    planned_execution_timestamp: datetime
    fees_base: Decimal
    estimated_costs_base: Decimal
    cash_impact_base: Decimal
    position_impact: Decimal
    expected_exposure: dict[str, Any]
    risk_decision: dict[str, Any]
    configuration_version: str
    accounting_generation_version: str
    scheduler_bar: dict[str, str]
    runtime_mode: str
    monitor_only: bool
    created_at: datetime
    instrument_metadata: dict[str, Any]
    observation_metadata: dict[str, Any]

    def validate(self):
        required = (self.event_id, self.proposal_id, self.decision_id, self.strategy_id, self.strategy_version,
                    self.instrument_id, self.symbol, self.market, self.venue, self.asset_class, self.side,
                    self.event_type, self.price_units, self.native_currency, self.base_currency, self.fx_source,
                    self.configuration_version, self.scheduler_bar.get("identity"), self.runtime_mode)
        if any(not str(value).strip() for value in required): raise AccountingObservationError("required envelope field is missing")
        if self.schema_version != SCHEMA_VERSION: raise AccountingObservationError("unknown envelope schema version")
        if self.event_type not in {item.value for item in AccountingEventType}: raise AccountingObservationError("unknown accounting event type")
        fills = {AccountingEventType.BUY_FILL.value, AccountingEventType.SELL_FILL.value}
        if self.event_type in fills:
            if self.side not in {"BUY", "SELL"} or self.quantity <= 0 or self.native_price <= 0:
                raise AccountingObservationError("fill side and quantity are invalid")
        elif self.side != "NONE" or self.quantity != 0:
            raise AccountingObservationError("non-fill observations require side NONE and zero quantity")
        if self.native_price < 0 or self.fx_rate_to_base <= 0: raise AccountingObservationError("price/amount and FX are invalid")
        if min(self.fees_base, self.estimated_costs_base) < 0: raise AccountingObservationError("costs cannot be negative")
        for name in ("fx_timestamp", "market_data_timestamp", "valuation_timestamp", "planned_execution_timestamp", "created_at"):
            _utc(getattr(self, name), name)
        if self.runtime_mode != "monitor_only" or self.monitor_only is not True:
            raise AccountingObservationError("accounting observations are monitor-only")
        if self.accounting_generation_version not in {"INACTIVE", "PENDING"}:
            raise AccountingObservationError("observation cannot reference an active accounting generation")
        metadata_required = {"price_precision", "quantity_precision", "minimum_lot", "lot_increment", "fractional_support", "market_calendar", "timezone", "metadata_source", "price_scale"}
        if not metadata_required.issubset(self.instrument_metadata): raise AccountingObservationError("instrument replay metadata is incomplete")
        policy = REPLAY_METADATA.get(self.symbol)
        if policy is None or self.instrument_id != policy.instrument_id:
            raise AccountingObservationError("unknown instrument replay policy")
        expected_policy = _json(asdict(policy))
        if any(self.instrument_metadata.get(key) != value for key, value in expected_policy.items()):
            raise AccountingObservationError("instrument replay metadata does not match authoritative policy")
        if self.configuration_version != load_risk_configuration().configuration_version:
            raise AccountingObservationError("unknown configuration version")
        observation_required = {"producer_id", "producer_version", "source_system", "source_reference", "authority_method"}
        if not observation_required.issubset(self.observation_metadata) or any(
            not str(self.observation_metadata.get(key, "")).strip() for key in observation_required
        ):
            raise AccountingObservationError("observation producer authority metadata is incomplete")
        return self

    def to_dict(self):
        self.validate()
        return _json(asdict(self))

    def serialize(self):
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def envelope_hash(self):
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()


def envelope_from_risk_evaluation(proposal: OrderProposal, context: RiskContext, decision: RiskDecision, *, created_at=None):
    metadata = get_instrument_metadata(proposal.symbol)
    replay = REPLAY_METADATA.get(proposal.symbol)
    if replay is None: raise AccountingObservationError("authoritative replay metadata is missing")
    fx_source = str(proposal.metadata.get("fx_source") or "").strip()
    if not fx_source: raise AccountingObservationError("authoritative FX source is required")
    reference_price = _decimal(context.reference_price, "reference_price")
    quantity = _decimal(proposal.quantity, "quantity")
    if metadata.instrument_currency == "GBP":
        if context.fx_rate_to_base not in {None, Decimal("1")}:
            raise AccountingObservationError("GBP identity FX must equal one")
        fx = Decimal("1")
        fx_timestamp = context.fx_timestamp or context.reference_price_timestamp
    else:
        if context.fx_rate_to_base is None or context.fx_timestamp is None:
            raise AccountingObservationError("authoritative FX rate and timestamp are required")
        fx = _decimal(context.fx_rate_to_base, "fx_rate_to_base")
        fx_timestamp = context.fx_timestamp
    native_notional = reference_price * metadata.price_scale * quantity
    fees = _decimal(context.estimated_fees_base, "estimated_fees_base")
    base_notional = native_notional * fx
    event_type = "BUY_FILL" if proposal.side.upper() == "BUY" else "SELL_FILL"
    sign = Decimal("-1") if proposal.side.upper() == "BUY" else Decimal("1")
    observed = decision.observed_values
    exposure = {key: observed.get(key) for key in (
        "projected_gross_exposure_base", "projected_net_exposure_base", "projected_concentration",
    )}
    instrument = {**_json(asdict(replay)), "metadata_source": metadata.metadata_source,
                  "price_scale": str(metadata.price_scale), "provider": metadata.provider,
                  "provider_symbol": metadata.provider_symbol, "listing_unit": metadata.listing_unit}
    envelope = AccountingObservationEnvelope(
        SCHEMA_VERSION, decision.decision_id, proposal.proposal_id, decision.decision_id,
        proposal.strategy_id, str(proposal.metadata.get("strategy_version") or proposal.strategy_id), replay.instrument_id,
        proposal.symbol, proposal.market, metadata.exchange, metadata.asset_class, proposal.side.upper(), event_type,
        quantity, reference_price, metadata.provider_price_unit, metadata.instrument_currency, "GBP", fx,
        _utc(fx_timestamp, "fx_timestamp"), fx_source,
        _utc(proposal.source_bar_timestamp, "market_data_timestamp"),
        _utc(context.reference_price_timestamp, "valuation_timestamp"), _utc(decision.timestamp, "planned_execution_timestamp"),
        fees, fees, sign * (base_notional + fees if sign < 0 else base_notional - fees), sign * quantity,
        exposure, decision.to_dict(), decision.configuration_version, "INACTIVE",
        {"identity": proposal.signal_id, "timestamp": proposal.source_bar_timestamp.isoformat()},
        context.runtime_mode, context.shadow_mode, _utc(created_at or decision.timestamp, "created_at"), instrument,
        {"producer_id": "risk-monitor-fill-observer", "producer_version": "1.0", "source_system": "central-risk-engine",
         "source_reference": decision.decision_id, "authority_method": "validated risk proposal and scheduler bar"},
    )
    return envelope.validate()


class AccountingObservationStore:
    def __init__(self, path=DEFAULT_STORE, failure_path=DEFAULT_FAILURE_STORE):
        self.path = Path(path); self.failure_path = Path(failure_path); self.lock_path = self.path.with_suffix(".lock")

    def records(self):
        if not self.path.exists(): return []
        try: return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception as exc: raise AccountingObservationError("observation store is unreadable or malformed") from exc

    def append(self, envelope):
        serialized = envelope.serialize(); digest = envelope.envelope_hash
        with acquire_runtime_write_lock(path=self.lock_path, context="accounting_observation"):
            records = self.records()
            matches = [row for row in records if row.get("event_id") == envelope.event_id]
            if matches:
                if matches[0].get("envelope_hash") != digest: raise AccountingObservationError("duplicate envelope ID has different content")
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {**json.loads(serialized), "envelope_hash": digest}
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"); handle.flush(); os.fsync(handle.fileno())
        return True

    def append_failure(self, proposal, decision, reason):
        payload = {"schema_version": SCHEMA_VERSION, "proposal_id": proposal.proposal_id,
                   "decision_id": decision.decision_id, "timestamp": decision.timestamp.isoformat(),
                   "validation_result": "FAILED", "reason": str(reason)}
        self.failure_path.parent.mkdir(parents=True, exist_ok=True)
        with acquire_runtime_write_lock(path=self.lock_path, context="accounting_observation_failure"):
            with self.failure_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"); handle.flush(); os.fsync(handle.fileno())

    def append_invalid(self, *, source_event_id, event_type, producer_id, reason, received_timestamp):
        payload = {"schema_version": SCHEMA_VERSION, "source_event_id": str(source_event_id),
                   "event_type": str(event_type), "producer_id": str(producer_id),
                   "timestamp": _utc(received_timestamp, "received_timestamp").isoformat(),
                   "validation_result": "FAILED", "reason": str(reason)}
        self.failure_path.parent.mkdir(parents=True, exist_ok=True)
        with acquire_runtime_write_lock(path=self.lock_path, context="accounting_observation_invalid"):
            with self.failure_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"); handle.flush(); os.fsync(handle.fileno())


def observe_monitor_only_evaluation(proposal, context, decision, *, store=None):
    if context.runtime_mode != "monitor_only" or context.shadow_mode is not True:
        raise AccountingObservationError("observer accepts monitor-only evaluations only")
    target = store or AccountingObservationStore()
    try:
        envelope = envelope_from_risk_evaluation(proposal, context, decision)
        target.append(envelope)
        return {"status": "VALID", "event_id": envelope.event_id, "envelope_hash": envelope.envelope_hash}
    except Exception as exc:
        target.append_failure(proposal, decision, exc)
        return {"status": "INVALID", "reason": str(exc)}
