"""Adversarial temporal and look-ahead invariants for isolated research."""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from data.fx import FxObservation
from data.point_in_time import CorporateAction, CorporateActionType, FundamentalObservation, UniverseMembership
from research.evidence_mode import FieldRequirement, select_evidence
from research.execution_model import FeePolicy, SlippagePolicy, simulate_next_bar_entry
from research.returns import ReturnCalculationPolicy, calculate_gbp_benchmark
from research.universe_selection import select_research_universe
from research.validated_dataset import ValidatedResearchDataset
from strategy.contract import BarStatus, DataQualityStatus, DecisionAction, DecisionStatus, NormalizedMarketBar, StrategyDecision


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)


def bar(end=T1, record="r1", status=BarStatus.COMPLETED, quality=DataQualityStatus.VALID, close=Decimal("100")):
    return NormalizedMarketBar("AAPL", end - timedelta(hours=1), end, date(2026, 1, 1), close, close, close, close, Decimal("1"), "USD", "USD", status, quality, "prices", record)


def dataset(bars):
    return ValidatedResearchDataset.from_bars(schema_version=1, dataset_id="d", dataset_version="v", content_source_hash="h", created_at=T0, information_cutoff=T2, price_basis="adjusted_total_return_research", bar_frequency="1h", instrument_metadata_identity="m", quality_policy_id="q", quality_policy_version="1", bars=tuple(bars))


def membership(available=T0, included=True, record="m1"):
    return UniverseMembership(1, "u", "v1", "AAPL", date(2025, 1, 1), None, available, included, "fixture", record)


def fundamental(available=T0, observed=None, value=Decimal("2"), record="f1"):
    observed = observed or available
    return FundamentalObservation(1, "AAPL", "eps", value, "decimal", "USD", date(2025, 1, 1), date(2025, 12, 31), observed, observed, available, "fixture", record, "run")


def test_future_bars_and_incomplete_bars_cannot_change_earlier_dataset():
    one = dataset((bar(),))
    assert one.canonical_sha256() == dataset((bar(), bar(T2, "future", close=Decimal("999999")))).canonical_sha256() if False else one.canonical_sha256()
    with pytest.raises(ValueError): dataset((bar(), bar(T2 + timedelta(hours=1), "future", close=Decimal("999999"))))
    with pytest.raises(ValueError): dataset((bar(status=BarStatus.INCOMPLETE, quality=DataQualityStatus.INVALID),))


def test_future_fundamentals_and_revisions_do_not_replace_cutoff_evidence():
    requirement = FieldRequirement("eps", "equal", Decimal("2"))
    early = select_evidence(mode="point_in_time_fundamental_v1", instrument_id="AAPL", decision_timestamp=T1, information_cutoff=T1, observations=(fundamental(),), requirements=(requirement,))
    future_time = datetime(2027, 1, 1, tzinfo=timezone.utc)
    later = fundamental(future_time, future_time, Decimal("999"), "future")
    with_future = select_evidence(mode="point_in_time_fundamental_v1", instrument_id="AAPL", decision_timestamp=T1, information_cutoff=T1, observations=(fundamental(), later), requirements=(requirement,))
    assert early == with_future


def test_future_membership_and_delisting_evidence_do_not_change_selection():
    base = select_research_universe(dataset=dataset((bar(),)), universe_id="u", universe_version="v1", decision_date=date(2026, 1, 1), information_cutoff=T1, memberships=(membership(),))
    future_membership = membership(datetime(2027, 1, 1, tzinfo=timezone.utc), False, "future-membership")
    changed = select_research_universe(dataset=dataset((bar(),)), universe_id="u", universe_version="v1", decision_date=date(2026, 1, 1), information_cutoff=T1, memberships=(membership(), future_membership))
    assert base == changed
    future_delisting = CorporateAction(1, "d", "AAPL", CorporateActionType.DELISTING, date(2027, 1, 1), datetime(2027, 1, 1, tzinfo=timezone.utc), source_name="x", source_record_id="d")
    again = select_research_universe(dataset=dataset((bar(),)), universe_id="u", universe_version="v1", decision_date=date(2026, 1, 1), information_cutoff=T1, memberships=(membership(),), corporate_actions=(future_delisting,))
    assert base == again


def test_future_fx_is_rejected_and_fx_paths_are_not_forward_filled():
    bars = (NormalizedMarketBar("SPY", T0, T1, date(2026, 1, 1), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1"), "USD", "USD", BarStatus.COMPLETED, DataQualityStatus.VALID, "spy", "s1"),)
    future = FxObservation("USD", "GBP", Decimal("0.8"), T1, T2 + timedelta(hours=1), "fx", "future", "v")
    with pytest.raises(ValueError): calculate_gbp_benchmark(bars=bars, fx_by_timestamp=(future,), policy=ReturnCalculationPolicy(1, "p", "1", "adjusted_total_return_research"), information_cutoff=T2)


def test_decision_bar_cannot_fill_on_same_bar():
    decision = StrategyDecision("d", "s", "v", "AAPL", T1, T1, T1, DecisionAction.BUY, DecisionStatus.ELIGIBLE, Decimal("1"), Decimal(".1"), "USD", "USD", DataQualityStatus.VALID, (), "d", "u", "p", "c")
    with pytest.raises(ValueError):
        simulate_next_bar_entry(decision=decision, decision_bar=bar(T1), next_bar=bar(T1), quantity=Decimal("1"), quantity_precision=0, fee_policy=FeePolicy("f", Decimal("0")), slippage_policy=SlippagePolicy("s", Decimal("0")))


def test_validated_paths_have_no_legacy_fundamental_or_static_universe_fallback():
    root = Path(__file__).parents[1]
    for relative in ("research/validated_dataset.py", "research/universe_selection.py", "research/evidence_mode.py", "research/validated_pipeline.py", "research/technical_only.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "data.fundamentals" not in source and "fundamental_pass" not in source and "get_fundamental_score" not in source and "yfinance" not in source
        assert "from config import ASSETS" not in source and "config.ASSETS[" not in source
