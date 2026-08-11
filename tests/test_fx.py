from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from data.fx import FxObservation, convert_currency


OBSERVED = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def quote(base="USD", quote="GBP", rate=Decimal("0.8"), available=OBSERVED):
    return FxObservation(base, quote, rate, OBSERVED, available, "fixture", "fx-1", "dataset-1")


def test_direct_inverse_and_same_currency_conversion():
    assert convert_currency(Decimal("10"), "USD", "GBP", observation=quote(), information_cutoff_utc=OBSERVED) == Decimal("8.0")
    assert convert_currency(Decimal("8"), "GBP", "USD", observation=quote(), information_cutoff_utc=OBSERVED, direction="inverse") == Decimal("10")
    assert convert_currency(Decimal("10"), "GBP", "GBP") == Decimal("10")


def test_availability_pair_quality_and_rate_are_fail_closed():
    with pytest.raises(ValueError):
        convert_currency(Decimal("1"), "USD", "GBP", observation=quote(available=OBSERVED + timedelta(seconds=1)), information_cutoff_utc=OBSERVED)
    with pytest.raises(ValueError):
        convert_currency(Decimal("1"), "EUR", "GBP", observation=quote(), information_cutoff_utc=OBSERVED)
    with pytest.raises(ValueError):
        FxObservation("USD", "GBP", Decimal("0"), OBSERVED, OBSERVED, "x", "r", "d")
    stale = FxObservation("USD", "GBP", Decimal("1"), OBSERVED, OBSERVED, "x", "r", "d", "stale")
    with pytest.raises(ValueError):
        convert_currency(Decimal("1"), "USD", "GBP", observation=stale, information_cutoff_utc=OBSERVED)


def test_observation_requires_utc_provenance_and_decimal_amount():
    assert quote().source_record_id == "fx-1"
    with pytest.raises(TypeError):
        convert_currency(1.0, "USD", "GBP", observation=quote(), information_cutoff_utc=OBSERVED)
    with pytest.raises(ValueError):
        FxObservation("USD", "GBP", Decimal("1"), datetime(2026, 1, 1, 12), OBSERVED, "x", "r", "d")
