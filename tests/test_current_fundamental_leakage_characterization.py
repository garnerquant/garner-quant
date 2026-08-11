"""Characterization of the current historical-fundamental leakage.

FIND-001 characterization

This test intentionally records the current defective behaviour in which one
present-day fundamental result is applied across historical signal dates. It
is not desired behaviour. When point-in-time fundamentals are implemented,
replace this test with requirements enforcing available_timestamp <=
information_cutoff.
"""

import inspect
from hashlib import sha256
from pathlib import Path

import pandas as pd

from strategy import signals


HISTORICAL_DATES = pd.to_datetime(["2024-01-02", "2024-06-03", "2025-01-02"])


def _historical_prices():
    return pd.DataFrame({"AAPL": [100.0, 101.0, 102.0]}, index=HISTORICAL_DATES)


def _assert_no_time_context(function):
    forbidden = {
        "as_of", "as_of_date", "effective_at", "available_at",
        "publication_timestamp", "information_cutoff",
    }
    assert not forbidden.intersection(inspect.signature(function).parameters)


def test_current_scalar_fundamentals_are_applied_to_all_historical_rows(tmp_path, monkeypatch):
    fundamental_pass_calls = []
    fundamental_score_calls = []

    def fake_fundamental_pass(*args, **kwargs):
        fundamental_pass_calls.append((args, kwargs))
        return True

    def fake_fundamental_score(*args, **kwargs):
        fundamental_score_calls.append((args, kwargs))
        return 7

    monkeypatch.setattr(signals, "fundamental_pass", fake_fundamental_pass)
    monkeypatch.setattr(signals, "get_fundamental_score", fake_fundamental_score)
    monkeypatch.setattr(
        signals,
        "technical_score",
        lambda ticker, price, volume=None: pd.Series(3, index=price.index),
    )
    repository_report = Path(__file__).parents[1] / "fundamental_scores.csv"
    before_hash = sha256(repository_report.read_bytes()).hexdigest()

    monkeypatch.chdir(tmp_path)
    result = signals.build_signals(_historical_prices())

    assert len(fundamental_pass_calls) == 1
    assert len(fundamental_score_calls) == 1
    assert fundamental_pass_calls == [(('AAPL', 'equity'), {})]
    assert fundamental_score_calls == [(('AAPL', 'equity'), {})]
    _assert_no_time_context(signals.fundamental_pass)
    _assert_no_time_context(signals.get_fundamental_score)
    assert list(result.index) == list(HISTORICAL_DATES)
    assert result["AAPL"].tolist() == [1, 1, 1]
    assert sha256(repository_report.read_bytes()).hexdigest() == before_hash


def test_one_failing_current_scalar_suppresses_all_historical_rows(tmp_path, monkeypatch):
    fundamental_pass_calls = []
    fundamental_score_calls = []

    def fake_fundamental_pass(*args, **kwargs):
        fundamental_pass_calls.append((args, kwargs))
        return False

    def fake_fundamental_score(*args, **kwargs):
        fundamental_score_calls.append((args, kwargs))
        return 1

    monkeypatch.setattr(signals, "fundamental_pass", fake_fundamental_pass)
    monkeypatch.setattr(signals, "get_fundamental_score", fake_fundamental_score)
    monkeypatch.setattr(
        signals,
        "technical_score",
        lambda ticker, price, volume=None: pd.Series(3, index=price.index),
    )
    monkeypatch.chdir(tmp_path)

    result = signals.build_signals(_historical_prices())

    assert len(fundamental_pass_calls) == 1
    assert len(fundamental_score_calls) == 1
    assert all(not kwargs for _, kwargs in fundamental_pass_calls + fundamental_score_calls)
    assert result["AAPL"].tolist() == [0, 0, 0]
