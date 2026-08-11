from datetime import datetime, timedelta, timezone

import pytest

from data.data_quality import completed_bar_eligibility, freshness_eligibility


START = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)


def test_completed_bar_requires_completed_valid_and_known_cutoff():
    result = completed_bar_eligibility(
        instrument_id="AAPL", session_id="2026-01-01", bar_status="completed", quality_status="valid",
        bar_start_utc=START, bar_end_utc=END, information_cutoff_utc=END,
        expected_session_close_utc=END,
    )
    assert result.eligible
    assert result.reason_codes == ()


@pytest.mark.parametrize("status,quality,expected", [("incomplete", "valid", "bar_not_completed"), ("completed", "stale", "bar_quality_not_valid")])
def test_invalid_bar_states_fail_closed(status, quality, expected):
    result = completed_bar_eligibility(
        instrument_id="AAPL", session_id="s", bar_status=status, quality_status=quality,
        bar_start_utc=START, bar_end_utc=END, information_cutoff_utc=END,
    )
    assert not result.eligible
    assert expected in result.reason_codes


def test_future_and_ambiguous_close_are_rejected_and_boundaries_are_explicit():
    future = completed_bar_eligibility(instrument_id="AAPL", session_id="s", bar_status="completed", quality_status="valid", bar_start_utc=START, bar_end_utc=END, information_cutoff_utc=START)
    assert not future.eligible
    wrong_close = completed_bar_eligibility(instrument_id="AAPL", session_id="s", bar_status="completed", quality_status="valid", bar_start_utc=START, bar_end_utc=END, information_cutoff_utc=END, expected_session_close_utc=END + timedelta(minutes=1))
    assert "bar_end_not_expected_session_close" in wrong_close.reason_codes
    with pytest.raises(ValueError):
        completed_bar_eligibility(instrument_id="AAPL", session_id="s", bar_status="completed", quality_status="valid", bar_start_utc=datetime(2026, 1, 1, 9), bar_end_utc=END, information_cutoff_utc=END)


def test_freshness_is_field_specific_and_fail_closed():
    fresh = freshness_eligibility(field_name="ohlc", observed_at_utc=END, information_cutoff_utc=END, maximum_age=timedelta(hours=1), use_type="decision_use", quality_status="valid")
    assert fresh.decision_eligible
    stale = freshness_eligibility(field_name="volume", observed_at_utc=START, information_cutoff_utc=END, maximum_age=timedelta(hours=1), use_type="decision_use", quality_status="valid")
    assert not stale.decision_eligible
    missing = freshness_eligibility(field_name="fx", observed_at_utc=None, information_cutoff_utc=END, maximum_age=timedelta(hours=1), use_type="decision_use", quality_status="valid")
    assert not missing.decision_eligible
    with pytest.raises(ValueError):
        freshness_eligibility(field_name="x", observed_at_utc=END, information_cutoff_utc=END, maximum_age=timedelta(seconds=-1), use_type="decision_use", quality_status="valid")


def test_forward_fill_is_rejected_for_decisions_but_stale_display_is_explicit():
    decision = freshness_eligibility(field_name="ohlc", observed_at_utc=START, information_cutoff_utc=END, maximum_age=timedelta(hours=1), use_type="decision_use", quality_status="valid", forward_filled=True)
    assert not decision.decision_eligible
    assert "forward_fill_not_allowed_for_decision" in decision.reason_codes
    display = freshness_eligibility(field_name="ohlc", observed_at_utc=START, information_cutoff_utc=END, maximum_age=timedelta(hours=1), use_type="valuation_display", quality_status="valid")
    assert not display.decision_eligible
    assert display.display_allowed
