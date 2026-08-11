from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.point_in_time import (
    CorporateAction, CorporateActionType, FundamentalObservation, UniverseMembership,
    canonical_point_in_time_bytes, canonical_point_in_time_sha256, resolve_membership,
)


OBS = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def fundamental(**overrides):
    values = dict(schema_version=1, instrument_id="AAPL", field_name="eps", value=Decimal("1.00"), value_type="decimal", currency="USD", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), reported_at=OBS, observed_at=OBS, available_at=OBS, source_name="fixture", source_record_id="r1", collection_run_id="run1")
    values.update(overrides)
    return FundamentalObservation(**values)


def membership(**overrides):
    values = dict(schema_version=1, universe_id="u", universe_version="v1", instrument_id="AAPL", valid_from=date(2025, 1, 1), valid_to=None, available_at=OBS, included=True, reason="eligible", source_record_id="m1")
    values.update(overrides)
    return UniverseMembership(**values)


def test_fundamental_cutoff_missing_availability_and_revision():
    assert fundamental().eligibility(OBS).eligible
    assert not fundamental(available_at=None).eligibility(OBS).eligible
    assert not fundamental(available_at=datetime(2026, 2, 1, tzinfo=timezone.utc), observed_at=datetime(2026, 2, 1, tzinfo=timezone.utc)).eligibility(OBS).eligible
    assert fundamental(source_revision_id="rev2", source_record_id="r2") != fundamental()


def test_fundamental_validation_and_immutability():
    with pytest.raises(ValueError):
        fundamental(observed_at=datetime(2026, 1, 1, 12))
    with pytest.raises(ValueError):
        fundamental(available_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    with pytest.raises(TypeError):
        fundamental(value=1.5)
    item = fundamental()
    with pytest.raises(AttributeError):
        item.value = Decimal("2")


def test_membership_resolution_is_versioned_deterministic_and_supports_exclusion():
    records = [membership(instrument_id="MSFT", source_record_id="2"), membership(instrument_id="AAPL", source_record_id="1"), membership(instrument_id="TSLA", included=False, source_record_id="3")]
    assert resolve_membership(records, universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS) == ("AAPL", "MSFT")
    assert resolve_membership([membership(valid_from=date(2027, 1, 1))], universe_id="u", universe_version="v1", decision_date=date(2025, 6, 1), information_cutoff=OBS) == ()
    with pytest.raises(ValueError):
        membership(valid_to=date(2025, 1, 1))


def test_corporate_actions_and_delisting_are_explicit_decimal_records():
    split = CorporateAction(1, "a1", "AAPL", CorporateActionType.STOCK_SPLIT, date(2026, 2, 1), OBS, ratio=Decimal("4"), source_name="fixture", source_record_id="ca1")
    dividend = CorporateAction(1, "a2", "AAPL", CorporateActionType.CASH_DIVIDEND, date(2026, 2, 1), OBS, cash_amount=Decimal("0.25"), currency="USD", source_name="fixture", source_record_id="ca2")
    delisting = CorporateAction(1, "a3", "OLD", CorporateActionType.DELISTING, date(2026, 2, 1), OBS, source_name="fixture", source_record_id="ca3")
    assert split.ratio == Decimal("4") and dividend.cash_amount == Decimal("0.25") and delisting.action_type.value == "delisting"
    with pytest.raises(ValueError):
        CorporateAction(1, "a4", "AAPL", CorporateActionType.STOCK_SPLIT, date(2026, 2, 1), OBS, ratio=Decimal("0"), source_name="x", source_record_id="x")


def test_point_in_time_serialization_is_deterministic_and_does_not_change_strategy_serialization():
    item = fundamental(value=Decimal("1.0"))
    other = fundamental(value=Decimal("1.00"))
    assert canonical_point_in_time_bytes(item) == canonical_point_in_time_bytes(other)
    assert canonical_point_in_time_sha256(item) == canonical_point_in_time_sha256(other)
    assert canonical_point_in_time_bytes(item).endswith(b"}")
    assert b"\n" not in canonical_point_in_time_bytes(item)
    assert len(canonical_point_in_time_sha256(item)) == 64
    with pytest.raises(TypeError):
        canonical_point_in_time_bytes(object())
