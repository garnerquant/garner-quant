from datetime import datetime, timezone
from decimal import Decimal

import pytest

from data.fx import FxObservation
from data.instrument_metadata import InstrumentMetadata
from research.portfolio_simulation import PortfolioPosition, PortfolioState, calculate_metrics, mark_to_market, size_target, value_in_gbp


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def state(equity): return PortfolioState(1, "sim", NOW, "GBP", equity, (), Decimal("0"), Decimal("0"), equity, Decimal("0"))


def gbp(): return InstrumentMetadata("AAPL", "AAPL", "Equity", "NASDAQ", "GBP", "GBP", Decimal("1"), 0)


def test_current_equity_sizing_changes_after_gain_or_loss():
    assert size_target(state=state(Decimal("10000")), instrument_id="AAPL", target_weight=Decimal("0.10"), price=Decimal("100"), metadata=gbp(), available_cash_gbp=Decimal("10000"), information_cutoff=NOW).target_notional_gbp == Decimal("1000")
    assert size_target(state=state(Decimal("8000")), instrument_id="AAPL", target_weight=Decimal("0.10"), price=Decimal("100"), metadata=gbp(), available_cash_gbp=Decimal("8000"), information_cutoff=NOW).target_notional_gbp == Decimal("800")
    assert size_target(state=state(Decimal("12000")), instrument_id="AAPL", target_weight=Decimal("0.10"), price=Decimal("100"), metadata=gbp(), available_cash_gbp=Decimal("12000"), information_cutoff=NOW).target_notional_gbp == Decimal("1200")


def test_whole_share_crypto_precision_gbp_and_foreign_fx():
    equity = size_target(state=state(10000), instrument_id="AAPL", target_weight=Decimal("0.10"), price=Decimal("33"), metadata=gbp(), available_cash_gbp=Decimal("1000"), information_cutoff=NOW)
    assert equity.quantity == Decimal("30")
    crypto = InstrumentMetadata("BTC-GBP", "BTC-GBP", "Crypto", "Crypto", "GBP", "GBP", Decimal("1"), 8)
    assert size_target(state=state(10000), instrument_id="BTC-GBP", target_weight=Decimal("0.10"), price=Decimal("30000"), metadata=crypto, available_cash_gbp=Decimal("1000"), information_cutoff=NOW).quantity == Decimal("0.03333333")
    usd = InstrumentMetadata("SPY", "SPY", "ETF", "NYSE", "USD", "USD", Decimal("1"), 0)
    fx = FxObservation("USD", "GBP", Decimal("0.8"), NOW, NOW, "f", "fx", "v")
    assert value_in_gbp(price=Decimal("100"), metadata=usd, fx_observation=fx, information_cutoff=NOW) == Decimal("80")
    with pytest.raises(ValueError): value_in_gbp(price=Decimal("100"), metadata=usd, fx_observation=None, information_cutoff=NOW)


def test_mark_to_market_metrics_and_fee_cash_constraint():
    position = PortfolioPosition("AAPL", Decimal("10"), Decimal("1000"))
    marked = mark_to_market(state=PortfolioState(1, "sim", NOW, "GBP", Decimal("9000"), (position,), Decimal("0"), Decimal("0"), Decimal("10000"), Decimal("1000")), prices={"AAPL": Decimal("110")}, metadata={"AAPL": gbp()}, fx_by_currency={}, information_cutoff=NOW)
    assert marked.total_equity_gbp == Decimal("10100")
    sized = size_target(state=state(10000), instrument_id="AAPL", target_weight=Decimal("0.10"), price=Decimal("100"), metadata=gbp(), available_cash_gbp=Decimal("105"), information_cutoff=NOW, fee_rate=Decimal("0.01"))
    assert sized.quantity == Decimal("1") and sized.fee_gbp == Decimal("1")
    metrics = calculate_metrics(equity_series=(Decimal("10000"), Decimal("8000"), Decimal("12000")), realized_pnl_gbp=Decimal("0"), unrealized_pnl_gbp=Decimal("0"), fees_gbp=Decimal("1"), turnover_gbp=Decimal("1000"), benchmark_cumulative_return=Decimal("0.05"))
    assert metrics.cumulative_return == Decimal("0.2") and metrics.maximum_drawdown == Decimal("-0.2")
