"""Offline, non-authoritative comparison tests."""

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.legacy_observations import parse_signal_report_csv
from research.shadow_comparison import ShadowComparisonPolicy, compare_shadow_observations
from strategy.contract import DataQualityStatus, DecisionAction, DecisionStatus, StrategyDecision


T = datetime(2025, 1, 2, 16, tzinfo=timezone.utc)
POLICY = ShadowComparisonPolicy(1, "shadow", "1", "GBP", "technical_only_historical_v1", "legacy_current_fundamental_unverified")


def decision(instrument="AAPL", action=DecisionAction.BUY, weight=Decimal("0.1")):
    return StrategyDecision("d-" + instrument, "shadow-strategy", "1", instrument, T, T, T, action, DecisionStatus.ELIGIBLE, Decimal("1"), weight, "GBP", "GBP", DataQualityStatus.VALID, (), "dataset", "universe", "params", "code")


def legacy(signal="1", weight="0.1", ticker="AAPL"):
    return parse_signal_report_csv(f"date,ticker,signal,weight,status\n2025-01-02,{ticker},{signal},{weight},buy\n", source_artifact_hash="a" * 64, parser_version="1", weight_unit="fraction").observations.signals[0]


def test_agreement_is_observation_not_validation():
    comparisons, summary = compare_shadow_observations(validated_decisions=(decision(),), legacy_signals=(legacy(),), policy=POLICY)
    outcomes = {x.dimension: x.outcome for x in comparisons[0].differences}
    assert outcomes["signal_direction"] == "agree"
    assert outcomes["target_weight"] == "agree"
    assert outcomes["methodology"] == "methodology_mismatch"
    assert summary.result_classification == "shadow_observation_unverified"


def test_difference_and_unmatched_instruments_are_explicit():
    comparisons, summary = compare_shadow_observations(validated_decisions=(decision(action=DecisionAction.SELL), decision("MSFT")), legacy_signals=(legacy(signal="1"), legacy(ticker="TSLA")), policy=POLICY)
    assert "MSFT" in summary.validated_only and "TSLA" in summary.legacy_only
    assert any(x.outcome == "differ" for x in comparisons[0].differences)


def test_missing_time_and_unit_never_become_zero_or_equal():
    comparisons, _ = compare_shadow_observations(validated_decisions=(decision(),), legacy_signals=(legacy(),), policy=POLICY)
    outcomes = {x.dimension: x.outcome for x in comparisons[0].differences}
    assert outcomes["timing"] == "unavailable"
    assert outcomes["currency_unit"] == "unavailable"


def test_ordering_and_hash_are_deterministic():
    a = compare_shadow_observations(validated_decisions=(decision("MSFT"), decision()), legacy_signals=(legacy(ticker="MSFT"), legacy()), policy=POLICY)[1]
    b = compare_shadow_observations(validated_decisions=(decision(), decision("MSFT")), legacy_signals=(legacy(), legacy(ticker="MSFT")), policy=POLICY)[1]
    assert a == b and a.canonical_hash == b.canonical_hash


def test_no_runtime_or_execution_imports():
    source_path = Path(__file__).resolve().parents[1] / "research" / "shadow_comparison.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    forbidden_roots = {"runtime", "execution", "risk_engine", "canonical_accounting", "socket", "requests", "subprocess"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(forbidden_roots)
