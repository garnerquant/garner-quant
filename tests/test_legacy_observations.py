"""Offline tests for explicit, unverified legacy observations."""

from datetime import date
from decimal import Decimal

import pytest
from dataclasses import FrozenInstanceError

from research.legacy_observations import (
    LegacyObservationSet,
    LegacyPortfolioProjection,
    LegacySignalObservation,
    LegacyWeightObservation,
    parse_signal_report_csv,
)


SOURCE = "a" * 64
CSV = "date,ticker,signal,weight,status\n2025-01-02,AAPL,1.0,0.10,buy\n2025-01-03,MSFT,-1,0,sell\n"


def test_actual_signal_schema_parses_without_inventing_time_or_units():
    result = parse_signal_report_csv(CSV, source_artifact_hash=SOURCE, parser_version="signal-v1", weight_unit="fraction")
    assert result.status == "parsed"
    assert result.observations is not None
    signal = result.observations.signals[0]
    assert signal.signal_value == Decimal("1.0")
    assert signal.observation_timestamp_utc is None
    assert signal.available_timestamp_utc is None
    assert signal.currency is None and signal.price_unit is None
    assert "availability_timestamp_missing" in result.observations.limitations
    assert signal.methodology_classification == "legacy_methodologically_invalid"


def test_missing_numeric_values_remain_unavailable():
    result = parse_signal_report_csv("date,ticker,signal,weight,status\n2025-01-02,AAPL,,0.1,buy\n", source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction")
    assert result.status == "parsed"
    assert result.observations.signals[0].signal_value is None


def test_duplicate_rows_are_rejected():
    result = parse_signal_report_csv("date,ticker,signal,weight,status\n2025-01-02,AAPL,1,0.1,buy\n2025-01-02,AAPL,1,0.1,buy\n", source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction")
    assert result.status == "rejected"


def test_malformed_decimal_is_rejected_without_coercion():
    result = parse_signal_report_csv("date,ticker,signal,weight,status\n2025-01-02,AAPL,nope,0.1,buy\n", source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction")
    assert result.status == "rejected"


def test_unknown_classification_fails_closed():
    with pytest.raises(ValueError):
        parse_signal_report_csv(CSV, source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction", methodology_classification="validated")


def test_immutable_projection_and_weight_contracts_preserve_missing_values():
    projection = LegacyPortfolioProjection(1, "paper_30_day_tracker", SOURCE, "1", date(2025, 1, 2), Decimal("100"), Decimal("20"), None, Decimal("1"), None, "GBP", "paper_observation_unverified", "parsed", ("aggregate_projection",), ())
    weight = LegacyWeightObservation(1, "weights_v2", SOURCE, "1", "AAPL", date(2025, 1, 2), None, None, Decimal("0.1"), "fraction", None, None, None, None, None, "legacy_methodologically_invalid", "parsed", ("date_only",), ())
    assert projection.canonical_hash and weight.canonical_hash
    with pytest.raises(FrozenInstanceError):
        weight.weight = Decimal("0.2")


def test_observation_set_hash_is_order_invariant():
    one = parse_signal_report_csv(CSV, source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction").observations
    two = parse_signal_report_csv("date,ticker,signal,weight,status\n2025-01-03,MSFT,-1,0,sell\n2025-01-02,AAPL,1.0,0.10,buy\n", source_artifact_hash=SOURCE, parser_version="v1", weight_unit="fraction").observations
    assert one.canonical_hash == two.canonical_hash
    assert isinstance(one.signals, tuple)


def test_no_production_or_external_imports():
    source = open("research/legacy_observations.py", encoding="utf-8").read()
    for forbidden in ("yfinance", "supabase", "runtime", "execution", "socket", "requests", "os.environ"):
        assert forbidden not in source
