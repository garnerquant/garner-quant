"""Pure completed-bar eligibility and field-specific freshness policies."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field} must be timezone-aware UTC")


def _reasons(values):
    return tuple(values)


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason_codes: tuple[str, ...]
    instrument_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    decision_eligible: bool
    display_allowed: bool
    reason_codes: tuple[str, ...]
    field_name: str
    use_type: str


def completed_bar_eligibility(*, instrument_id: str, session_id: str, bar_status: str, quality_status: str, bar_start_utc: datetime, bar_end_utc: datetime, information_cutoff_utc: datetime, expected_session_close_utc: datetime | None = None) -> EligibilityDecision:
    if not instrument_id or not session_id:
        raise ValueError("instrument_id and session_id must be nonblank")
    _utc(bar_start_utc, "bar_start_utc")
    _utc(bar_end_utc, "bar_end_utc")
    _utc(information_cutoff_utc, "information_cutoff_utc")
    if expected_session_close_utc is not None:
        _utc(expected_session_close_utc, "expected_session_close_utc")
    reasons = []
    if bar_end_utc <= bar_start_utc:
        reasons.append("invalid_bar_interval")
    if bar_status != "completed":
        reasons.append("bar_not_completed")
    if quality_status != "valid":
        reasons.append("bar_quality_not_valid")
    if bar_end_utc > information_cutoff_utc:
        reasons.append("bar_after_information_cutoff")
    if expected_session_close_utc is not None and bar_end_utc != expected_session_close_utc:
        reasons.append("bar_end_not_expected_session_close")
    return EligibilityDecision(not reasons, _reasons(reasons), instrument_id, session_id)


def freshness_eligibility(*, field_name: str, observed_at_utc: datetime | None, information_cutoff_utc: datetime, maximum_age: timedelta, use_type: str, quality_status: str, forward_filled: bool = False) -> FreshnessDecision:
    if not field_name:
        raise ValueError("field_name must be nonblank")
    _utc(information_cutoff_utc, "information_cutoff_utc")
    if maximum_age.total_seconds() < 0:
        raise ValueError("maximum_age cannot be negative")
    if use_type not in {"decision_use", "valuation_display", "monitoring_display"}:
        raise ValueError("unsupported use_type")
    reasons = []
    if observed_at_utc is None:
        reasons.append("observation_missing")
    else:
        _utc(observed_at_utc, "observed_at_utc")
        if observed_at_utc > information_cutoff_utc:
            reasons.append("observation_after_information_cutoff")
        elif information_cutoff_utc - observed_at_utc > maximum_age:
            reasons.append("observation_stale")
    if quality_status != "valid":
        reasons.append("quality_not_valid")
    if forward_filled and use_type == "decision_use":
        reasons.append("forward_fill_not_allowed_for_decision")
    decision_ok = not reasons and not forward_filled
    display_ok = decision_ok or (use_type in {"valuation_display", "monitoring_display"} and bool(observed_at_utc) and "observation_after_information_cutoff" not in reasons and "observation_missing" not in reasons)
    return FreshnessDecision(decision_ok, display_ok, _reasons(reasons), field_name, use_type)
