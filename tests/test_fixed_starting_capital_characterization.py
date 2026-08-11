"""Characterization of fixed-starting-capital sizing.

FIND-005 characterization

This module records the current fixed-starting-capital sizing behaviour. It
distinguishes dimensionless target weights from the later conversion of those
weights into paper notional and shares. It is not the desired long-term
behaviour. When equity-aware allocation is implemented, replace these tests
with requirements using verified current mark-to-market equity, cash,
currency-normalized exposure and portfolio constraints.
"""

import ast
import inspect
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from config import RISK_PER_TRADE, STARTING_CASH
from strategy.portfolio import build_weights


ROOT = Path(__file__).parents[1]
PORTFOLIO_SOURCE = (ROOT / "strategy" / "portfolio.py").read_text(encoding="utf-8")
PAPER_SOURCE = (ROOT / "execution" / "portfolio_manager.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "main_v2.py").read_text(encoding="utf-8")
RISK_ENGINE_SOURCE = (ROOT / "risk_engine" / "engine.py").read_text(encoding="utf-8")
RISK_INTEGRATION_SOURCE = (ROOT / "risk_engine" / "integration.py").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class StartingCashUse:
    source: str
    expression: str
    classification: str


STARTING_CASH_USES = (
    StartingCashUse("strategy/portfolio.py:build_weights", "STARTING_CASH * RISK_PER_TRADE", "monetary/notional conversion"),
    StartingCashUse("strategy/portfolio.py:build_weights", "position_value / STARTING_CASH", "dimensionless weight construction"),
    StartingCashUse("execution/portfolio_manager.py:calculate_cash", "STARTING_CASH + realised_pnl", "cash basis"),
    StartingCashUse("execution/portfolio_manager.py:calculate_cash", "STARTING_CASH - invested + realised_pnl", "cash basis"),
    StartingCashUse("execution/portfolio_manager.py:update_portfolio", "STARTING_CASH * weight", "monetary/notional conversion"),
)


def test_sizing_interfaces_separate_weights_from_equity_conversion():
    weight_parameters = set(inspect.signature(build_weights).parameters)
    assert weight_parameters == {"signals", "prices", "risk_levels"}
    assert not weight_parameters.intersection({
        "current_equity", "portfolio_equity", "net_liquidation_value",
        "available_cash", "verified_equity", "mark_to_market_equity",
    })

    tree = ast.parse(PAPER_SOURCE)
    update = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "update_portfolio")
    paper_parameters = {argument.arg for argument in update.args.args + update.args.kwonlyargs}
    assert not paper_parameters.intersection({
        "current_equity", "portfolio_equity", "net_liquidation_value",
        "available_cash", "verified_equity", "mark_to_market_equity",
    })


def test_every_confirmed_starting_cash_use_is_classified():
    assert len(STARTING_CASH_USES) == 5
    assert all(item.expression in PORTFOLIO_SOURCE or item.expression in PAPER_SOURCE for item in STARTING_CASH_USES)
    assert any(item.classification == "dimensionless weight construction" for item in STARTING_CASH_USES)
    assert sum(item.classification == "monetary/notional conversion" for item in STARTING_CASH_USES) == 2
    assert "cash_risk = STARTING_CASH * RISK_PER_TRADE" in PORTFOLIO_SOURCE
    assert "weight = position_value / STARTING_CASH" in PORTFOLIO_SOURCE
    assert "position_value = STARTING_CASH * weight" in PAPER_SOURCE
    assert "return STARTING_CASH + realised_pnl" in PAPER_SOURCE
    assert "return STARTING_CASH - invested + realised_pnl" in PAPER_SOURCE


def test_pure_weight_builder_is_dimensionless_and_starting_cash_cancels():
    signals = pd.DataFrame({"AAPL": [1]}, index=["2026-01-05"])
    prices = pd.DataFrame({"AAPL": [100.0]}, index=signals.index)
    risk_levels = {
        "stop_loss": pd.DataFrame({"AAPL": [90.0]}, index=signals.index),
        "take_profit": pd.DataFrame({"AAPL": [120.0]}, index=signals.index),
    }
    weights = build_weights(signals, prices, risk_levels)
    expected = min(float(RISK_PER_TRADE * 100 / (100 - 90)), 0.25)
    assert weights.loc["2026-01-05", "AAPL"] == expected

    cash_risk = Decimal(str(STARTING_CASH)) * Decimal(str(RISK_PER_TRADE))
    position_value = cash_risk / (Decimal("10") / Decimal("100"))
    dimensionless_weight = position_value / Decimal(str(STARTING_CASH))
    assert dimensionless_weight == Decimal(str(RISK_PER_TRADE)) * Decimal("100") / Decimal("10")
    assert dimensionless_weight == Decimal(str(expected))


def test_fixed_paper_notional_differs_from_equity_aware_notional():
    target_weight = Decimal("0.10")
    fixed_notional = Decimal(str(STARTING_CASH)) * target_weight
    scenarios = {
        Decimal("8000"): Decimal("800"),
        Decimal("10000"): Decimal("1000"),
        Decimal("12000"): Decimal("1200"),
    }
    for current_equity, equity_aware_notional in scenarios.items():
        assert fixed_notional == Decimal("1000")
        assert equity_aware_notional == current_equity * target_weight
        assert fixed_notional / current_equity == {
            Decimal("8000"): Decimal("0.125"),
            Decimal("10000"): Decimal("0.10"),
            Decimal("12000"): Decimal("0.08333333333333333333333333333"),
        }[current_equity]
        assert fixed_notional - equity_aware_notional == {
            Decimal("8000"): Decimal("200"),
            Decimal("10000"): Decimal("0"),
            Decimal("12000"): Decimal("-200"),
        }[current_equity]


def test_paper_shares_cash_and_existing_position_behaviour_are_source_confirmed():
    assert "shares = position_value / price" in PAPER_SOURCE
    assert "if position_value > cash:" in PAPER_SOURCE
    assert "position_value = cash" in PAPER_SOURCE
    assert "ticker not in held_tickers" in PAPER_SOURCE
    assert "round(" not in PAPER_SOURCE
    assert "currency" not in PAPER_SOURCE[PAPER_SOURCE.index("position_value = STARTING_CASH * weight"):PAPER_SOURCE.index("position_value = STARTING_CASH * weight") + 700]


def test_downstream_risk_validates_supplied_notional_and_does_not_recompute_sizing():
    assert "risk_decision = central_risk.evaluate(proposal, risk_context)" in PAPER_SOURCE
    assert "notional = proposal.quantity * price * fx" in RISK_ENGINE_SOURCE
    assert "concentration = projected_position / equity" in RISK_ENGINE_SOURCE
    assert "portfolio_equity_base" in RISK_INTEGRATION_SOURCE
    assert "STARTING_CASH * weight" not in RISK_ENGINE_SOURCE
    assert "build_weights(signals" in MAIN_SOURCE or "build_weights(" in MAIN_SOURCE
    assert MAIN_SOURCE.index("build_weights(signals, prices, risk_levels)") < MAIN_SOURCE.index("update_portfolio(")


def test_no_verified_equity_reaches_the_sizing_calculation():
    assert "portfolio_equity" not in PORTFOLIO_SOURCE
    assert "portfolio_equity" not in PAPER_SOURCE[PAPER_SOURCE.index("def update_portfolio"):PAPER_SOURCE.index("def portfolio_summary")]
    assert "build_production_risk_context" in PAPER_SOURCE
    assert "portfolio_equity_base" in RISK_INTEGRATION_SOURCE
    assert "current mark-to-market equity" not in PORTFOLIO_SOURCE
    assert "current mark-to-market equity" not in PAPER_SOURCE
