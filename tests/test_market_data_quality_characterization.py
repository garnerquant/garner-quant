"""Characterize stale, incomplete, and forward-filled active market data.

TKT-024 characterization: these tests preserve current defects rather than
defining desired behavior. They must be replaced by positive, field-specific
freshness and completed-bar tests when the active path is migrated.
"""

import ast
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parents[1]
MARKET = (ROOT / "data" / "market_data.py").read_text(encoding="utf-8")
SIGNALS = (ROOT / "strategy" / "signals.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main_v2.py").read_text(encoding="utf-8")


def test_active_market_data_unconditionally_forward_fills():
    assert ".ffill()" in MARKET
    source_tree = ast.parse(MARKET)
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "ffill" for node in ast.walk(source_tree))

    raw = pd.DataFrame({"Close": [100.0, None, None]}, index=pd.date_range("2026-01-01", periods=3, tz="UTC"))
    propagated = raw.ffill()
    assert propagated["Close"].tolist() == [100.0, 100.0, 100.0]
    # This demonstrates propagation only; it does not estimate financial impact.


def test_active_signal_path_has_no_data_quality_or_timestamp_contract():
    forbidden = {"observed_at", "available_at", "completed_at", "information_cutoff", "freshness", "forward_fill_provenance"}
    signal_functions = [node for node in ast.walk(ast.parse(SIGNALS)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    parameters = {arg.arg for node in signal_functions for arg in node.args.args + node.args.kwonlyargs}
    assert not parameters.intersection(forbidden)
    assert not any(token in SIGNALS for token in forbidden)
    assert "bar_timestamps" in MAIN  # orchestration has timestamps, but not a quality decision contract.


def test_missing_and_stale_fields_are_not_distinguished_by_active_pipeline():
    assert "dropna" in MARKET
    assert "quality_status" not in MARKET
    assert "field-specific" not in MARKET
    assert "bar_status" not in SIGNALS
    assert "data_quality" not in SIGNALS


def test_phase_a_quality_primitives_are_disconnected_from_production():
    production = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("data/market_data.py", "strategy/signals.py", "main_v2.py")
    )
    assert "data.data_quality" not in production
    assert "from data.data_quality" not in production
    assert "data_quality import" not in production
