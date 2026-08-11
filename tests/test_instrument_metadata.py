from decimal import Decimal
from datetime import datetime, timezone

import pytest

from data.instrument_metadata import InstrumentMetadata, price_from_major_unit, price_to_major_unit


def gbp_pence():
    return InstrumentMetadata("VWRL.L", "VWRL.L", "ETF", "LSE", "GBP", "GBp", Decimal("0.01"), 0, metadata_version="test-1")


def test_metadata_is_immutable_and_explicit():
    item = gbp_pence()
    assert item.quantity_precision == 0
    with pytest.raises((AttributeError, TypeError)):
        item.price_unit = "GBP"


@pytest.mark.parametrize("currency,unit", [("GBP", "GBP"), ("USD", "USD"), ("GBP", "BTC-GBP")])
def test_major_unit_scale_one(currency, unit):
    item = InstrumentMetadata(unit, unit, "Crypto" if unit == "BTC-GBP" else "Equity", "TEST", currency, unit, Decimal("1"), 8 if unit == "BTC-GBP" else 0)
    assert price_to_major_unit(Decimal("12.34"), item) == Decimal("12.34")


def test_gbp_pence_conversion_is_exact_and_round_trips():
    item = gbp_pence()
    assert price_to_major_unit(Decimal("12345"), item) == Decimal("123.45")
    assert price_from_major_unit(Decimal("123.45"), item) == Decimal("12345")


def test_invalid_values_and_precision_policy_are_rejected_or_distinct():
    with pytest.raises(TypeError):
        price_to_major_unit(1.0, gbp_pence())
    with pytest.raises(ValueError):
        InstrumentMetadata("x", "x", "Equity", "TEST", "GBP", "GBP", Decimal("0"), 0)
    with pytest.raises(ValueError):
        InstrumentMetadata("x", "x", "Equity", "TEST", "gbp", "GBP", Decimal("1"), 0)
    with pytest.raises(ValueError):
        InstrumentMetadata("x", "x", "Equity", "TEST", "GBP", "GBP", Decimal("1"), True)
    crypto = InstrumentMetadata("BTC-GBP", "BTC-GBP", "Crypto", "Crypto", "GBP", "GBP", Decimal("1"), 8)
    equity = InstrumentMetadata("AAPL", "AAPL", "Equity", "NASDAQ", "USD", "USD", Decimal("1"), 0)
    assert crypto.quantity_precision != equity.quantity_precision
