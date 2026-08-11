from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.point_in_time import FundamentalObservation
from research.evidence_mode import FieldRequirement, select_evidence


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def observation(value=Decimal("2"), record="r1", available=OBS, observed=OBS):
    return FundamentalObservation(1, "AAPL", "eps", value, "decimal", "USD", date(2025, 1, 1), date(2025, 12, 31), observed, observed, available, "fixture", record, "run")


def args(mode):
    return dict(mode=mode, instrument_id="AAPL", decision_timestamp=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), information_cutoff=OBS)


def test_explicit_modes_and_unknown_rejection():
    technical = select_evidence(**args("technical_only_historical_v1"))
    assert technical.status == "eligible" and technical.result_classification == "exploratory_unverified"
    with pytest.raises(ValueError): select_evidence(**args("legacy"))
    with pytest.raises(ValueError): select_evidence(**args(""))


def test_point_in_time_predicates_and_revision_selection():
    requirement = FieldRequirement("eps", "greater_than_or_equal", Decimal("1"))
    result = select_evidence(**args("point_in_time_fundamental_v1"), observations=(observation(), observation(Decimal("3"), "r2")), requirements=(requirement,))
    assert result.status == "eligible" and result.selected_observation_ids == ("r2",)
    changed = select_evidence(**args("point_in_time_fundamental_v1"), observations=(observation(Decimal("0")),), requirements=(requirement,))
    assert changed.status == "ineligible"


def test_later_or_missing_evidence_is_unavailable_not_zero():
    requirement = FieldRequirement("eps", "greater_than", Decimal("0"))
    late_time = datetime(2027, 1, 1, tzinfo=timezone.utc)
    late = select_evidence(**args("point_in_time_fundamental_v1"), observations=(observation(available=late_time, observed=late_time),), requirements=(requirement,))
    missing = select_evidence(**args("point_in_time_fundamental_v1"), requirements=(requirement,))
    assert late.status == missing.status == "unavailable"
    assert "unavailable" in dict(missing.field_outcomes).values()


def test_determinism_and_provider_isolation():
    requirement = FieldRequirement("eps", "equal", Decimal("2"))
    one = select_evidence(**args("point_in_time_fundamental_v1"), observations=(observation(),), requirements=(requirement,))
    two = select_evidence(**args("point_in_time_fundamental_v1"), observations=(observation(),), requirements=(requirement,))
    assert one.canonical_sha256() == two.canonical_sha256()
    from pathlib import Path
    source = (Path(__file__).parents[1] / "research" / "evidence_mode.py").read_text(encoding="utf-8")
    assert "data.fundamentals" not in source and "yfinance" not in source and "fundamental_pass" not in source
