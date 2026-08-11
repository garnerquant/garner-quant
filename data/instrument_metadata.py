"""Immutable instrument metadata and explicit price-unit conversion."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math


def _decimal(value, field):
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field} must be Decimal")
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")
    return value


def _utc(value, field):
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field} must be UTC")
    return value


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    instrument_id: str
    provider_symbol: str
    asset_class: str
    exchange_or_market: str
    listing_currency: str
    price_unit: str
    price_scale_to_major: Decimal
    quantity_precision: int
    active_from: datetime | None = None
    active_to: datetime | None = None
    metadata_version: str = "1"

    def __post_init__(self):
        for name in ("instrument_id", "provider_symbol", "asset_class", "exchange_or_market", "price_unit", "metadata_version"):
            _text(getattr(self, name), name)
        if not isinstance(self.listing_currency, str) or self.listing_currency != self.listing_currency.upper() or len(self.listing_currency) != 3:
            raise ValueError("listing_currency must be uppercase ISO-style text")
        scale = _decimal(self.price_scale_to_major, "price_scale_to_major")
        if scale <= 0:
            raise ValueError("price_scale_to_major must be positive")
        if isinstance(self.quantity_precision, bool) or not isinstance(self.quantity_precision, int) or self.quantity_precision < 0:
            raise ValueError("quantity_precision must be a nonnegative integer")
        start, end = _utc(self.active_from, "active_from"), _utc(self.active_to, "active_to")
        if start is not None and end is not None and end <= start:
            raise ValueError("active_to must be later than active_from")


def price_to_major_unit(price: Decimal, metadata: InstrumentMetadata) -> Decimal:
    value = _decimal(price, "price")
    if value < 0:
        raise ValueError("price must be nonnegative")
    return value * metadata.price_scale_to_major


def price_from_major_unit(price: Decimal, metadata: InstrumentMetadata) -> Decimal:
    value = _decimal(price, "price")
    if value < 0:
        raise ValueError("price must be nonnegative")
    return value / metadata.price_scale_to_major
