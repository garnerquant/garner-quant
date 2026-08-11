from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest

from data.fx import FxObservation
from research.returns import ReturnCalculationPolicy, calculate_gbp_benchmark, calculate_return_series, compare_returns
from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(price, end, symbol="AAPL", currency="GBP"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=end - 1)
    finish = start + timedelta(hours=1)
    return NormalizedMarketBar(symbol, start, finish, date(2026, 1, 1), price, price, price, price, Decimal("1"), currency, currency, BarStatus.COMPLETED, DataQualityStatus.VALID, "d", f"r{end}")


def policy(): return ReturnCalculationPolicy(1, "returns", "1", "adjusted_total_return_research")


def test_decimal_returns_first_observation_and_order_invariance():
    series = calculate_return_series(bars=(bar(Decimal("100"), 1), bar(Decimal("110"), 2)), policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))
    assert series.observations[0].return_value is None and series.observations[1].return_value == Decimal("0.1")
    assert series.canonical_sha256() == calculate_return_series(bars=tuple(reversed((bar(Decimal("100"), 1), bar(Decimal("110"), 2)))), policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc)).canonical_sha256()


def test_invalid_or_future_bars_fail_closed():
    with pytest.raises(ValueError): calculate_return_series(bars=(bar(Decimal("0"), 1),), policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))
    with pytest.raises(ValueError): calculate_return_series(bars=(bar(Decimal("100"), 4),), policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))


def test_gbp_benchmark_converts_at_each_timestamp_and_changes_with_fx():
    bars = (bar(Decimal("100"), 1, "SPY", "USD"), bar(Decimal("110"), 2, "SPY", "USD"))
    available = datetime(2026, 1, 1, 3, tzinfo=timezone.utc)
    fx1 = (FxObservation("USD", "GBP", Decimal("0.8"), datetime(2026, 1, 1, 1, tzinfo=timezone.utc), available, "f", "f1", "v"), FxObservation("USD", "GBP", Decimal("0.7"), datetime(2026, 1, 1, 2, tzinfo=timezone.utc), available, "f", "f2", "v"))
    # FX timestamps align with bar end timestamps in this synthetic example.
    fx1 = tuple(FxObservation(x.base_currency, x.quote_currency, x.rate, bar_item.bar_end_utc, x.available_at_utc, x.source, x.source_record_id, x.dataset_version) for x, bar_item in zip(fx1, bars))
    one = calculate_gbp_benchmark(bars=bars, fx_by_timestamp=fx1, policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))
    assert one.observations[1].return_value == Decimal("-0.0375")
    with pytest.raises(ValueError): calculate_gbp_benchmark(bars=bars, fx_by_timestamp=fx1[:1], policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))


def test_comparison_is_aligned_and_decimal():
    p = calculate_return_series(bars=(bar(Decimal("100"), 1), bar(Decimal("110"), 2)), policy=policy(), information_cutoff=datetime(2026, 1, 1, 3, tzinfo=timezone.utc))
    comparison = compare_returns(p, p)
    assert comparison.arithmetic_excess_return == Decimal("0")
