"""Offline contract and isolation tests for the non-authoritative shadow runner."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from research.legacy_observations import LegacyObservationSet, parse_signal_report_csv
from research.shadow_comparison import ShadowComparisonPolicy
from research.shadow_runner import (
    ShadowRunRequest,
    ShadowRunResult,
    RESULT_CLASSIFICATION,
    run_shadow_comparison,
    validated_evidence_identity,
)
from strategy.contract import DataQualityStatus, DecisionAction, DecisionStatus, StrategyDecision


ROOT = Path(__file__).resolve().parents[1]
T = datetime(2025, 1, 2, 16, tzinfo=timezone.utc)
POLICY = ShadowComparisonPolicy(1, "shadow", "1", "GBP", "technical_only_historical_v1", "legacy_current_fundamental_unverified")


def decision(instrument="AAPL", action=DecisionAction.BUY, weight=Decimal("0.1"), when=T):
    return StrategyDecision(
        "decision-" + instrument, "shadow-strategy", "1", instrument, when, when, when,
        action, DecisionStatus.ELIGIBLE, Decimal("1"), weight, "GBP", "GBP",
        DataQualityStatus.VALID, (), "dataset", "universe", "parameters", "code",
    )


def legacy(ticker="AAPL", signal="1", weight="0.1", *, complete=False, day="2025-01-02"):
    value = parse_signal_report_csv(
        f"date,ticker,signal,weight,status\n{day},{ticker},{signal},{weight},buy\n",
        source_artifact_hash="a" * 64, parser_version="1", weight_unit="fraction",
    ).observations.signals[0]
    if complete:
        value = replace(value, observation_timestamp_utc=T, available_timestamp_utc=T, currency="GBP", price_unit="GBP")
    return value


def observation_set(*signals, weights=(), limitations=("caller-supplied",)):
    return LegacyObservationSet(1, tuple(signals), tuple(weights), (), "legacy_methodologically_invalid", tuple(limitations))


def request(decisions=(decision(),), observations=None, cutoff=T, **changes):
    identity = validated_evidence_identity(decisions)
    values = dict(
        schema_version=1, shadow_run_id="shadow-1", created_at=T + timedelta(hours=1),
        information_cutoff=cutoff, validated_decisions=tuple(decisions),
        validated_evidence_identity=identity, legacy_observations=observations,
        comparison_policy=POLICY, strategy_id="shadow-strategy", strategy_version="1",
        parameter_set_id="parameters", code_version="code", warnings=("caller warning",),
        limitations=("caller limitation",),
    )
    values.update(changes)
    return ShadowRunRequest(**values)


def test_valid_agree_and_differing_signal_comparisons():
    agreeing = run_shadow_comparison(request(observations=observation_set(legacy(complete=True))))
    differences = run_shadow_comparison(request(observations=observation_set(legacy(signal="-1", complete=True))))
    assert dict((x.dimension, x.outcome) for x in agreeing.comparisons[0].differences)["signal_direction"] == "agree"
    assert dict((x.dimension, x.outcome) for x in differences.comparisons[0].differences)["signal_direction"] == "differ"


def test_validated_only_and_legacy_only_instruments_are_explicit():
    result = run_shadow_comparison(request(decisions=(decision("AAPL"), decision("MSFT")), observations=observation_set(legacy("TSLA"))))
    assert result.comparison_summary.validated_only == ("AAPL", "MSFT")
    assert result.comparison_summary.legacy_only == ("TSLA",)


def test_missing_legacy_field_stays_unavailable():
    result = run_shadow_comparison(request(observations=observation_set(legacy())))
    outcomes = {item.dimension: item.outcome for item in result.comparisons[0].differences}
    assert outcomes["timing"] == "unavailable"
    assert outcomes["currency_unit"] == "unavailable"
    assert outcomes["target_weight"] == "agree"


def test_invalid_validated_input_cannot_fall_back_to_legacy():
    with pytest.raises((TypeError, ValueError)):
        request(decisions=(object(),), observations=observation_set(legacy()))
    with pytest.raises((TypeError, ValueError)):
        run_shadow_comparison(request(observations=observation_set(legacy()), validated_evidence_identity="b" * 64))


def test_invalid_or_conflicting_legacy_identity_fails_closed():
    one = legacy("AAPL")
    conflicting = replace(one, source_row_id="different")
    with pytest.raises(ValueError):
        run_shadow_comparison(request(observations=observation_set(one, conflicting)))
    with pytest.raises((TypeError, ValueError)):
        run_shadow_comparison(request(observations=observation_set(legacy("AAPL")), legacy_observations=object()))


def test_future_legacy_evidence_is_excluded_and_future_validated_evidence_rejected():
    future = legacy(day="2025-01-03")
    result = run_shadow_comparison(request(observations=observation_set(future)))
    assert result.comparisons[0].differences[0].outcome == "validated_only"
    assert any("future_after_information_cutoff" in item for item in result.unavailable_inputs)
    future_decision = decision(when=T + timedelta(days=1))
    with pytest.raises(ValueError):
        run_shadow_comparison(request(decisions=(future_decision,), observations=None))


def test_same_and_reordered_inputs_have_identical_result_and_hash():
    first = run_shadow_comparison(request(decisions=(decision("MSFT"), decision("AAPL")), observations=observation_set(legacy("MSFT"), legacy("AAPL"))))
    second = run_shadow_comparison(request(decisions=(decision("AAPL"), decision("MSFT")), observations=observation_set(legacy("AAPL"), legacy("MSFT"))))
    assert first == second
    assert first.canonical_hash == second.canonical_hash


def test_cutoff_is_part_of_result_identity_and_hash():
    one = run_shadow_comparison(request(observations=observation_set(legacy()), cutoff=T))
    two = run_shadow_comparison(request(observations=observation_set(legacy()), cutoff=T + timedelta(hours=1)))
    assert one.information_cutoff != two.information_cutoff
    assert one.canonical_hash != two.canonical_hash


def test_result_safety_fields_are_fixed_and_classification_is_fixed():
    result = run_shadow_comparison(request())
    assert result.result_classification == RESULT_CLASSIFICATION == "shadow_observation_unverified"
    assert result.execution_authorized is False
    assert result.publication_authorized is False
    assert result.runtime_effect is False
    assert result.paper_effect is False
    assert result.accounting_effect is False
    with pytest.raises(TypeError):
        ShadowRunResult(
            1, "id", T, T, result.validated_evidence_identity, None, (),
            result.comparison_summary, (), (), (), execution_authorized=True,
        )


def test_request_and_result_are_immutable():
    req = request()
    result = run_shadow_comparison(req)
    with pytest.raises(FrozenInstanceError):
        req.shadow_run_id = "changed"
    with pytest.raises(FrozenInstanceError):
        result.runtime_effect = True


def test_canonical_json_and_hash_are_stable():
    result = run_shadow_comparison(request(observations=observation_set(legacy(complete=True))))
    assert result.canonical_bytes() == result.canonical_json.encode("utf-8")
    assert json.loads(result.canonical_json)["payload"]["result_classification"] == RESULT_CLASSIFICATION
    assert result.canonical_hash == hashlib.sha256(result.canonical_bytes()).hexdigest()
    assert result.canonical_json == run_shadow_comparison(request(observations=observation_set(legacy(complete=True)))).canonical_json


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return tree, roots


def _repository_python_files():
    excluded = {".git", "venv", ".venv", "__pycache__"}
    return tuple(
        path for path in ROOT.rglob("*.py")
        if not any(part in excluded or part.startswith(".scanner-") for part in path.parts)
    )


def test_ast_import_and_capability_audit_is_offline_only():
    source = ROOT / "research" / "shadow_runner.py"
    tree, imports = _imports(source)
    assert imports.isdisjoint({"execution", "runtime", "risk_engine", "socket", "requests", "urllib", "subprocess", "os", "pathlib"})
    forbidden_calls = {"open", "write_text", "write_bytes", "mkdir", "unlink", "replace", "run", "Popen", "create_connection"}
    assert all(not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls) for node in ast.walk(tree))


def test_no_active_production_module_imports_runner():
    for path in _repository_python_files():
        if "\\tests\\" in str(path) or path == ROOT / "research" / "shadow_runner.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "research.shadow_runner"
            elif isinstance(node, ast.Import):
                assert all(alias.name != "research.shadow_runner" for alias in node.names)


def test_runner_has_no_environment_or_filesystem_dependency_and_does_not_change_files():
    before = {path: path.read_bytes() for path in _repository_python_files() if "\\tests\\" not in str(path)}
    result = run_shadow_comparison(request())
    after = {path: path.read_bytes() for path in before}
    assert result.runtime_effect is False
    assert before == after


def test_unknown_schema_and_policy_fail_closed():
    with pytest.raises(ValueError):
        request(schema_version=2)
    unknown = ShadowComparisonPolicy(1, "unknown", "1", "GBP", "m1", "m2")
    with pytest.raises(ValueError):
        request(comparison_policy=unknown)


def test_bundle_alias_is_caller_supplied_and_conflicts_fail():
    decisions = (decision(),)
    result = run_shadow_comparison(request(validated_decisions=None, validated_evidence_bundle=decisions))
    assert result.validated_evidence_identity == validated_evidence_identity(decisions)
    with pytest.raises(ValueError):
        request(validated_evidence_bundle=(decision("MSFT"),))
