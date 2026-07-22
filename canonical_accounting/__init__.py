"""Prospective, GBP-normalized accounting generation support."""

from canonical_accounting.currency import (
    ConversionResult,
    CurrencyError,
    FxQuote,
    InstrumentMetadata,
    convert_amount_to_base,
    normalize_price_to_major_unit,
)
from canonical_accounting.events import AccountingEvent, AccountingEventType
from canonical_accounting.snapshot import CanonicalPortfolioSnapshot
from canonical_accounting.successor import SuccessorGenerationWriter
from canonical_accounting.observation import AccountingObservationEnvelope, AccountingObservationStore

__all__ = [
    "ConversionResult",
    "CurrencyError",
    "FxQuote",
    "InstrumentMetadata",
    "convert_amount_to_base",
    "normalize_price_to_major_unit",
    "AccountingEvent",
    "AccountingEventType",
    "CanonicalPortfolioSnapshot",
    "SuccessorGenerationWriter",
    "AccountingObservationEnvelope",
    "AccountingObservationStore",
]
