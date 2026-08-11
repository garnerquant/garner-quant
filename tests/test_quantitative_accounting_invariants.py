"""Exact Decimal conservation identities for the isolated research engine."""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from data.fx import FxObservation, convert_currency
from data.instrument_metadata import InstrumentMetadata
from data.point_in_time import CorporateAction, CorporateActionType
from research.corporate_actions import ResearchPosition, apply_corporate_action
from research.execution_model import FeePolicy, SlippagePolicy, simulate_next_bar_entry
from research.portfolio_simulation import PortfolioPosition, PortfolioState, calculate_metrics, mark_to_market, size_target
from research.returns import ReturnCalculationPolicy, calculate_return_series
from strategy.contract import BarStatus, DataQualityStatus, DecisionAction, DecisionStatus, NormalizedMarketBar, StrategyDecision


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(hour, price, symbol="AAPL", currency="GBP"):
    start = datetime(2026, 1, 1, hour, tzinfo=timezone.utc)
    return NormalizedMarketBar(symbol, start, start + timedelta(hours=1), date(2026, 1, 1), price, price, price, price, Decimal("1"), currency, currency, BarStatus.COMPLETED, DataQualityStatus.VALID, "d", f"r{hour}")


def test_return_product_identity():
    policy = ReturnCalculationPolicy(1, "p", "1", "adjusted_total_return_research")
    series = calculate_return_series(bars=(bar(0, Decimal("100")), bar(1, Decimal("110")), bar(2, Decimal("99"))), policy=policy, information_cutoff=datetime(2026, 1, 1, 4, tzinfo=timezone.utc))
    product = Decimal("1")
    for item in series.observations:
        if item.return_value is not None: product *= Decimal("1") + item.return_value
    assert product - Decimal("1") == Decimal("-0.01")


def test_fx_round_trip_and_gbp_value_identity():
    obs = FxObservation("USD", "GBP", Decimal("0.8"), T0, T0, "fx", "fx1", "v")
    amount = Decimal("100")
    assert convert_currency(convert_currency(amount, "USD", "GBP", observation=obs, information_cutoff_utc=T0), "GBP", "USD", observation=obs, information_cutoff_utc=T0, direction="inverse") == amount
    usd = InstrumentMetadata("SPY", "SPY", "ETF", "NYSE", "USD", "USD", Decimal("1"), 0)
    from research.portfolio_simulation import value_in_gbp
    assert value_in_gbp(price=Decimal("100"), metadata=usd, fx_observation=obs, information_cutoff=T0) == Decimal("80")


def test_split_dividend_and_symbol_conservation():
    position = ResearchPosition("AAPL", Decimal("10"), Decimal("1000"), "GBP", "equity", 0)
    split_action = CorporateAction(1, "s", "AAPL", CorporateActionType.STOCK_SPLIT, date(2026, 1, 1), T0, ratio=Decimal("2"), source_name="x", source_record_id="s")
    split = apply_corporate_action(position=position, action=split_action, research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert split.post_position.quantity * Decimal("50") == position.quantity * Decimal("100")
    dividend_action = CorporateAction(1, "d", "AAPL", CorporateActionType.CASH_DIVIDEND, date(2026, 1, 1), T0, cash_amount=Decimal("2"), currency="GBP", source_name="x", source_record_id="d")
    dividend = apply_corporate_action(position=position, action=dividend_action, research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert dividend.cash_movement == position.quantity * Decimal("2")
    symbol_action = CorporateAction(1, "c", "AAPL", CorporateActionType.SYMBOL_CHANGE, date(2026, 1, 1), T0, successor_instrument_id="NEW", source_name="x", source_record_id="c")
    changed = apply_corporate_action(position=position, action=symbol_action, research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert changed.post_position.quantity == position.quantity and changed.post_position.cost_basis == position.cost_basis


def test_execution_gross_fee_and_cash_sign_identities():
    decision = StrategyDecision("d", "s", "v", "AAPL", T0, T0, T0, DecisionAction.BUY, DecisionStatus.ELIGIBLE, Decimal("1"), Decimal(".1"), "GBP", "GBP", DataQualityStatus.VALID, (), "d", "u", "p", "c")
    fee = FeePolicy("f", Decimal(".01")); slip = SlippagePolicy("s", Decimal("0"))
    fill = simulate_next_bar_entry(decision=decision, decision_bar=bar(0, Decimal("100")), next_bar=bar(1, Decimal("100")), quantity=Decimal("2"), quantity_precision=0, fee_policy=fee, slippage_policy=slip)
    assert fill.gross_notional == fill.quantity * fill.fill_price
    assert fill.net_cash_impact == -(fill.gross_notional + fill.fee)


def test_cash_equity_sizing_precision_and_drawdown_identities():
    state = PortfolioState(1, "s", T0, "GBP", Decimal("9000"), (PortfolioPosition("AAPL", Decimal("10"), Decimal("1000")),), Decimal("0"), Decimal("0"), Decimal("10000"), Decimal("1000"))
    meta = {"AAPL": InstrumentMetadata("AAPL", "AAPL", "Equity", "NASDAQ", "GBP", "GBP", Decimal("1"), 0)}
    marked = mark_to_market(state=state, prices={"AAPL": Decimal("110")}, metadata=meta, fx_by_currency={}, information_cutoff=T0)
    assert marked.total_equity_gbp == marked.cash_gbp + Decimal("1100")
    assert size_target(state=PortfolioState(1, "s", T0, "GBP", Decimal("8000"), (), Decimal("0"), Decimal("0"), Decimal("8000"), Decimal("0")), instrument_id="AAPL", target_weight=Decimal(".1"), price=Decimal("100"), metadata=meta["AAPL"], available_cash_gbp=Decimal("8000"), information_cutoff=T0).target_notional_gbp == Decimal("800")
    metrics = calculate_metrics(equity_series=(Decimal("10000"), Decimal("8000"), Decimal("12000")), realized_pnl_gbp=Decimal("0"), unrealized_pnl_gbp=Decimal("0"), fees_gbp=Decimal("3"), turnover_gbp=Decimal("100"))
    assert metrics.drawdown == Decimal("0") and metrics.maximum_drawdown == Decimal("-.2")


def test_current_equity_basis_is_not_starting_cash_based():
    root = Path(__file__).parents[1]
    source = (root / "research" / "portfolio_simulation.py").read_text(encoding="utf-8")
    assert "STARTING_CASH" not in source and "config import" not in source
