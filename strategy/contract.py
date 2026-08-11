"""Immutable structural contracts for normalized data and strategy decisions."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class BarStatus(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class DataQualityStatus(str, Enum):
    VALID = "valid"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


class DecisionAction(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    EXIT = "exit"
    NO_ACTION = "no_action"


class DecisionStatus(str, Enum):
    ELIGIBLE = "eligible"
    REJECTED = "rejected"


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must represent UTC")
    return value


def _decimal(value: Decimal, field_name: str, *, non_negative: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class NormalizedMarketBar:
    instrument_id: str
    bar_start_utc: datetime
    bar_end_utc: datetime
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Optional[Decimal]
    currency: str
    price_unit: str
    bar_status: BarStatus
    quality_status: DataQualityStatus
    source_dataset_id: str
    source_record_id: str

    def __post_init__(self) -> None:
        _required_text(self.instrument_id, "instrument_id")
        start = _utc_timestamp(self.bar_start_utc, "bar_start_utc")
        end = _utc_timestamp(self.bar_end_utc, "bar_end_utc")
        if end <= start:
            raise ValueError("bar_end_utc must be later than bar_start_utc")
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        prices = {
            "open_price": _decimal(self.open_price, "open_price", non_negative=True),
            "high_price": _decimal(self.high_price, "high_price", non_negative=True),
            "low_price": _decimal(self.low_price, "low_price", non_negative=True),
            "close_price": _decimal(self.close_price, "close_price", non_negative=True),
        }
        if prices["high_price"] < max(prices["open_price"], prices["low_price"], prices["close_price"]):
            raise ValueError("high_price must be at least open, low, and close")
        if prices["low_price"] > min(prices["open_price"], prices["high_price"], prices["close_price"]):
            raise ValueError("low_price must be at most open, high, and close")
        if self.volume is not None:
            _decimal(self.volume, "volume", non_negative=True)
        currency = _required_text(self.currency, "currency")
        if currency != currency.upper():
            raise ValueError("currency must be uppercase")
        _required_text(self.price_unit, "price_unit")
        if not isinstance(self.bar_status, BarStatus):
            raise TypeError("bar_status must be a BarStatus")
        if not isinstance(self.quality_status, DataQualityStatus):
            raise TypeError("quality_status must be a DataQualityStatus")
        if self.bar_status is BarStatus.COMPLETED and self.quality_status is DataQualityStatus.MISSING:
            raise ValueError("a completed bar cannot have missing quality")
        if self.bar_status is BarStatus.INCOMPLETE and self.quality_status is DataQualityStatus.VALID:
            raise ValueError("an incomplete bar cannot have valid quality")
        _required_text(self.source_dataset_id, "source_dataset_id")
        _required_text(self.source_record_id, "source_record_id")


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    decision_id: str
    strategy_id: str
    strategy_version: str
    instrument_id: str
    decision_timestamp_utc: datetime
    information_cutoff_utc: datetime
    eligible_execution_timestamp_utc: datetime
    decision_action: DecisionAction
    decision_status: DecisionStatus
    signal_value: Optional[Decimal]
    target_weight: Optional[Decimal]
    currency: str
    price_unit: str
    quality_status: DataQualityStatus
    reason_codes: tuple[str, ...]
    dataset_version: str
    universe_version: str
    parameter_version: str
    code_revision: str

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id", "strategy_id", "strategy_version", "instrument_id",
            "dataset_version", "universe_version", "parameter_version", "code_revision",
        ):
            _required_text(getattr(self, field_name), field_name)
        decision_time = _utc_timestamp(self.decision_timestamp_utc, "decision_timestamp_utc")
        cutoff = _utc_timestamp(self.information_cutoff_utc, "information_cutoff_utc")
        eligible = _utc_timestamp(self.eligible_execution_timestamp_utc, "eligible_execution_timestamp_utc")
        if cutoff > decision_time:
            raise ValueError("information_cutoff_utc cannot be later than decision_timestamp_utc")
        if eligible < decision_time:
            raise ValueError("eligible_execution_timestamp_utc cannot be earlier than decision_timestamp_utc")
        if not isinstance(self.decision_action, DecisionAction):
            raise TypeError("decision_action must be a DecisionAction")
        if not isinstance(self.decision_status, DecisionStatus):
            raise TypeError("decision_status must be a DecisionStatus")
        if self.signal_value is not None:
            _decimal(self.signal_value, "signal_value")
        if self.target_weight is not None:
            _decimal(self.target_weight, "target_weight")
        currency = _required_text(self.currency, "currency")
        if currency != currency.upper():
            raise ValueError("currency must be uppercase")
        _required_text(self.price_unit, "price_unit")
        if not isinstance(self.quality_status, DataQualityStatus):
            raise TypeError("quality_status must be a DataQualityStatus")
        if not isinstance(self.reason_codes, tuple):
            raise TypeError("reason_codes must be an immutable tuple")
        if any(not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank strings")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must not contain duplicates")
        if self.decision_status is DecisionStatus.REJECTED and not self.reason_codes:
            raise ValueError("rejected decisions require at least one reason code")
