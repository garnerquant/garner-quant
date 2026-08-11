"""Immutable point-in-time evidence contracts and deterministic serialization."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import unicodedata


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")
    return value


def _utc(value, field, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value


def _decimal(value, field, positive=False):
    if isinstance(value, (bool, float)) or not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{field} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    schema_version: int
    instrument_id: str
    field_name: str
    value: Decimal | str | int | bool
    value_type: str
    currency: str | None
    period_start: date | None
    period_end: date | None
    reported_at: datetime | None
    observed_at: datetime
    available_at: datetime | None
    source_name: str
    source_record_id: str
    collection_run_id: str
    quality_status: str = "valid"
    source_revision_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field in ("instrument_id", "field_name", "value_type", "source_name", "source_record_id", "collection_run_id", "quality_status"):
            _text(getattr(self, field), field)
        if isinstance(self.value, float):
            raise TypeError("fundamental value cannot be float")
        _utc(self.observed_at, "observed_at")
        _utc(self.available_at, "available_at", optional=True)
        _utc(self.reported_at, "reported_at", optional=True)
        if self.available_at is not None and self.available_at > self.observed_at:
            raise ValueError("available_at cannot be later than observed_at")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        if self.currency is not None:
            if not isinstance(self.currency, str) or self.currency != self.currency.upper() or len(self.currency) != 3:
                raise ValueError("currency must be uppercase ISO-style text")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.metadata):
            raise ValueError("metadata must contain string pairs")

    def eligibility(self, information_cutoff: datetime) -> EvidenceDecision:
        _utc(information_cutoff, "information_cutoff")
        if self.available_at is None:
            return EvidenceDecision(False, "availability_missing")
        if self.available_at > information_cutoff:
            return EvidenceDecision(False, "not_available_by_information_cutoff")
        if self.quality_status != "valid":
            return EvidenceDecision(False, "quality_not_valid")
        return EvidenceDecision(True, "eligible")


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    schema_version: int
    universe_id: str
    universe_version: str
    instrument_id: str
    valid_from: date
    valid_to: date | None
    available_at: datetime
    included: bool
    reason: str
    source_record_id: str
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        for field in ("universe_id", "universe_version", "instrument_id", "reason", "source_record_id"):
            _text(getattr(self, field), field)
        _utc(self.available_at, "available_at")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")


def resolve_membership(records, *, universe_id, universe_version, decision_date, information_cutoff):
    _text(universe_id, "universe_id"); _text(universe_version, "universe_version"); _utc(information_cutoff, "information_cutoff")
    eligible = []
    for record in records:
        if record.universe_id != universe_id or record.universe_version != universe_version or not record.included:
            continue
        if record.valid_from > decision_date or (record.valid_to is not None and decision_date >= record.valid_to):
            continue
        if record.available_at <= information_cutoff:
            eligible.append(record.instrument_id)
    return tuple(sorted(set(eligible)))


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    SYMBOL_CHANGE = "symbol_change"
    MERGER = "merger_acquisition"
    DELISTING = "delisting"


@dataclass(frozen=True, slots=True)
class CorporateAction:
    schema_version: int
    action_id: str
    instrument_id: str
    action_type: CorporateActionType
    effective_date: date
    available_at: datetime
    ratio: Decimal | None = None
    cash_amount: Decimal | None = None
    currency: str | None = None
    predecessor_instrument_id: str | None = None
    successor_instrument_id: str | None = None
    source_name: str = ""
    source_record_id: str = ""
    status: str = "valid"

    def __post_init__(self):
        for field in ("action_id", "instrument_id", "source_name", "source_record_id", "status"):
            _text(getattr(self, field), field)
        _utc(self.available_at, "available_at")
        if self.ratio is not None:
            _decimal(self.ratio, "ratio", positive=True)
        if self.cash_amount is not None:
            _decimal(self.cash_amount, "cash_amount")
        if self.action_type in {CorporateActionType.STOCK_SPLIT, CorporateActionType.REVERSE_SPLIT} and self.ratio is None:
            raise ValueError("split actions require ratio")


def _canonical(value):
    if value is None or isinstance(value, (str, int, bool)):
        return None if value is None else (unicodedata.normalize("NFC", value) if isinstance(value, str) else value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal")
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, datetime):
        _utc(value, "datetime")
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("canonical mappings require string keys")
        return {unicodedata.normalize("NFC", k): _canonical(v) for k, v in value.items()}
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_point_in_time_payload(value):
    if not isinstance(value, (FundamentalObservation, UniverseMembership, CorporateAction)):
        raise TypeError("unsupported point-in-time contract")
    return {"contract_type": type(value).__name__, "schema_version": 1, "payload": _canonical(value)}


def canonical_point_in_time_bytes(value):
    return json.dumps(canonical_point_in_time_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_point_in_time_sha256(value):
    return hashlib.sha256(canonical_point_in_time_bytes(value)).hexdigest()
