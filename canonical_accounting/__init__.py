"""Prospective, GBP-normalized accounting generation support."""

from canonical_accounting.currency import (
    ConversionResult,
    CurrencyError,
    FxQuote,
    InstrumentMetadata,
    convert_amount_to_base,
    normalize_price_to_major_unit,
)

__all__ = [
    "ConversionResult",
    "CurrencyError",
    "FxQuote",
    "InstrumentMetadata",
    "convert_amount_to_base",
    "normalize_price_to_major_unit",
]
