"""Pure timestamped FX observations and explicit currency conversion."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


def _currency(value, field):
    if not isinstance(value, str) or len(value) != 3 or value != value.upper():
        raise ValueError(f"{field} must be uppercase currency code")
    return value


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field} must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class FxObservation:
    base_currency: str
    quote_currency: str
    rate: Decimal
    observed_at_utc: datetime
    available_at_utc: datetime
    source: str
    source_record_id: str
    dataset_version: str
    quality_status: str = "valid"

    def __post_init__(self):
        _currency(self.base_currency, "base_currency")
        _currency(self.quote_currency, "quote_currency")
        if self.base_currency == self.quote_currency:
            raise ValueError("FX observation currencies must differ")
        if not isinstance(self.rate, Decimal) or not self.rate.is_finite() or self.rate <= 0:
            raise ValueError("rate must be a positive finite Decimal")
        _utc(self.observed_at_utc, "observed_at_utc")
        _utc(self.available_at_utc, "available_at_utc")
        if self.available_at_utc < self.observed_at_utc:
            raise ValueError("available_at_utc cannot precede observed_at_utc")
        for field in ("source", "source_record_id", "dataset_version", "quality_status"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} must be nonblank")


def convert_currency(amount: Decimal, from_currency: str, to_currency: str, *, observation: FxObservation | None = None, information_cutoff_utc: datetime | None = None, direction: str = "direct") -> Decimal:
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise TypeError("amount must be a finite Decimal")
    _currency(from_currency, "from_currency")
    _currency(to_currency, "to_currency")
    if from_currency == to_currency:
        return amount
    if observation is None:
        raise ValueError("an FX observation is required for different currencies")
    if information_cutoff_utc is None:
        raise ValueError("information_cutoff_utc is required")
    _utc(information_cutoff_utc, "information_cutoff_utc")
    if observation.available_at_utc > information_cutoff_utc:
        raise ValueError("FX observation is not available by the information cutoff")
    if observation.quality_status != "valid":
        raise ValueError("FX observation is not valid")
    if direction == "direct":
        if (observation.base_currency, observation.quote_currency) != (from_currency, to_currency):
            raise ValueError("FX observation does not match the direct currency pair")
        return amount * observation.rate
    if direction == "inverse":
        if (observation.base_currency, observation.quote_currency) != (to_currency, from_currency):
            raise ValueError("FX observation does not match the inverse currency pair")
        return amount / observation.rate
    raise ValueError("direction must be explicit: direct or inverse")
