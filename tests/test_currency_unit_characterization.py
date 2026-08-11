"""Characterize the current GBp/GBP and benchmark-currency defects.

This test intentionally records current defects. It must be replaced by
positive unit-conversion, FX-provenance, and benchmark-currency tests once
the primitives are integrated into active paths.
"""

import ast
from decimal import Decimal
from pathlib import Path

import config


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "main_v2.py").read_text(encoding="utf-8")
PAPER = (ROOT / "execution" / "portfolio_manager.py").read_text(encoding="utf-8")
PORTFOLIO = (ROOT / "strategy" / "portfolio.py").read_text(encoding="utf-8")


def test_lse_units_and_active_paths_are_explicitly_characterized():
    lse = [metadata for metadata in config.ASSETS.values() if metadata["exchange"] == "LSE"]
    assert lse
    assert all(metadata["listing_currency"] == "GBp" for metadata in lse)

    # Confirmed: the active paper sizing path consumes the provider price
    # directly; no explicit major-unit conversion is present at that point.
    sizing = PAPER[PAPER.index("position_value = STARTING_CASH * weight"):]
    assert "shares = position_value / price" in sizing
    assert "price_to_major_unit" not in sizing
    assert "normalize_price_to_major_unit" not in sizing

    # Percentage arithmetic is scale invariant; this test does not claim a
    # monetary error for percentage-only calculations.
    assert (Decimal("12345") / Decimal("12000")) == (Decimal("123.45") / Decimal("120"))


def test_benchmark_is_usd_against_gbp_without_visible_conversion():
    assert config.PORTFOLIO_BASE_CURRENCY == "GBP"
    assert config.BENCHMARK_TICKER == "SPY"
    assert config.ASSETS["AAPL"]["listing_currency"] == "USD"

    tree = ast.parse(MAIN)
    benchmark_exprs = [
        ast.unparse(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "benchmark_return" for target in node.targets)
    ]
    assert benchmark_exprs
    assert all("fx" not in expression.lower() and "convert" not in expression.lower() for expression in benchmark_exprs)
    assert "benchmark_return" in MAIN


def test_active_currency_provenance_is_incomplete_at_sizing_and_comparison_boundaries():
    assert "price_unit" not in PORTFOLIO
    assert "price_scale" not in PAPER
    assert "information_cutoff" not in MAIN
    assert "fx_rate" not in MAIN
    assert "benchmark_currency" not in MAIN
