from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


BASE_CURRENCY = "GBP"
SUPPORTED_CURRENCIES = frozenset({"GBP", "USD", "EUR"})
SUPPORTED_PRICE_UNITS = frozenset({"GBP", "GBp", "USD", "EUR"})


class CurrencyError(ValueError):
    """Raised when money cannot be normalized or converted safely."""


def decimal_value(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CurrencyError(f"{field} must be a finite number") from exc
    if not result.is_finite():
        raise CurrencyError(f"{field} must be a finite number")
    return result


def canonical_currency(value: str) -> str:
    currency = str(value or "").strip().upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise CurrencyError(f"unsupported currency: {value!r}")
    return currency


@dataclass(frozen=True)
class InstrumentMetadata:
    symbol: str
    asset_class: str
    provider: str
    provider_symbol: str
    instrument_currency: str
    provider_price_unit: str
    listing_unit: str
    price_scale: Decimal
    exchange: str
    market_calendar: str
    fx_required: bool
    supported: bool
    metadata_source: str
    metadata_version: str = "1"

    def validate(self) -> None:
        if not self.symbol or not self.provider_symbol:
            raise CurrencyError("instrument symbol metadata is required")
        canonical_currency(self.instrument_currency)
        if self.provider_price_unit not in SUPPORTED_PRICE_UNITS:
            raise CurrencyError(
                f"ambiguous provider price unit for {self.symbol}: "
                f"{self.provider_price_unit!r}"
            )
        scale = decimal_value(self.price_scale, "price_scale")
        if scale <= 0:
            raise CurrencyError("price_scale must be positive")
        unit_currency = "GBP" if self.provider_price_unit == "GBp" else self.provider_price_unit
        if unit_currency != self.instrument_currency:
            raise CurrencyError(
                f"provider price unit does not match instrument currency for {self.symbol}"
            )
        if self.fx_required != (self.instrument_currency != BASE_CURRENCY):
            raise CurrencyError(f"fx_required is inconsistent for {self.symbol}")
        if not self.metadata_source:
            raise CurrencyError(f"metadata source is required for {self.symbol}")


@dataclass(frozen=True)
class FxQuote:
    source_currency: str
    target_currency: str
    rate: Decimal
    timestamp: datetime
    source: str
    direction: str


@dataclass(frozen=True)
class ConversionResult:
    source_amount: Decimal
    source_currency: str
    target_currency: str
    converted_amount: Decimal
    fx_rate: Decimal
    fx_timestamp: datetime
    fx_source: str
    conversion_direction: str


def normalize_price_to_major_unit(raw_price, metadata: InstrumentMetadata) -> Decimal:
    metadata.validate()
    price = decimal_value(raw_price, "native_price")
    if price <= 0:
        raise CurrencyError("native_price must be positive")
    return price * decimal_value(metadata.price_scale, "price_scale")


def validate_fx_quote(
    quote: FxQuote,
    *,
    as_of: datetime,
    max_age: timedelta,
    future_tolerance: timedelta,
) -> FxQuote:
    source = canonical_currency(quote.source_currency)
    target = canonical_currency(quote.target_currency)
    rate = decimal_value(quote.rate, "fx_rate")
    if rate <= 0:
        raise CurrencyError("fx_rate must be positive")
    if source == target:
        if rate != Decimal("1"):
            raise CurrencyError("identity FX quote must have rate 1")
    if not quote.source or not quote.direction:
        raise CurrencyError("FX source and conversion direction are required")
    if quote.timestamp.tzinfo is None or as_of.tzinfo is None:
        raise CurrencyError("FX timestamps must be timezone-aware")
    age = as_of.astimezone(timezone.utc) - quote.timestamp.astimezone(timezone.utc)
    if age > max_age:
        raise CurrencyError("FX quote is stale")
    if age < -future_tolerance:
        raise CurrencyError("FX quote is unreasonably future-dated")
    return quote


def inverse_fx_quote(quote: FxQuote) -> FxQuote:
    rate = decimal_value(quote.rate, "fx_rate")
    if rate <= 0:
        raise CurrencyError("fx_rate must be positive")
    return FxQuote(
        source_currency=quote.target_currency,
        target_currency=quote.source_currency,
        rate=Decimal("1") / rate,
        timestamp=quote.timestamp,
        source=quote.source,
        direction=f"inverse({quote.direction})",
    )


def convert_amount_to_base(
    amount,
    source_currency: str,
    *,
    quote: FxQuote | None,
    as_of: datetime,
    max_age: timedelta,
    future_tolerance: timedelta,
    base_currency: str = BASE_CURRENCY,
) -> ConversionResult:
    native = decimal_value(amount, "amount")
    source = canonical_currency(source_currency)
    target = canonical_currency(base_currency)
    if source == target:
        if quote is not None:
            validate_fx_quote(
                quote, as_of=as_of, max_age=max_age, future_tolerance=future_tolerance
            )
        return ConversionResult(
            native, source, target, native, Decimal("1"), as_of,
            "identity", f"{source}->{target}",
        )
    if quote is None:
        raise CurrencyError(f"missing FX quote for {source}->{target}")
    validate_fx_quote(
        quote, as_of=as_of, max_age=max_age, future_tolerance=future_tolerance
    )
    if canonical_currency(quote.source_currency) != source or canonical_currency(
        quote.target_currency
    ) != target:
        raise CurrencyError(f"FX quote direction does not match {source}->{target}")
    return ConversionResult(
        native, source, target, native * quote.rate, quote.rate,
        quote.timestamp, quote.source, quote.direction,
    )


def base_market_value(quantity, raw_price, metadata: InstrumentMetadata, **conversion) -> ConversionResult:
    quantity_value = decimal_value(quantity, "quantity")
    if quantity_value < 0:
        raise CurrencyError("quantity must not be negative")
    normalized = normalize_price_to_major_unit(raw_price, metadata)
    return convert_amount_to_base(
        quantity_value * normalized,
        metadata.instrument_currency,
        **conversion,
    )
