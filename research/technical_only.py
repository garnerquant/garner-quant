"""Explicit exploratory technical-only historical research mode.

This module is intentionally disconnected from runtime and paper execution.
It requires a named mode and validated completed bars supplied by the caller.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from strategy.contract import (
    BarStatus, DataQualityStatus, DecisionAction, DecisionStatus,
    NormalizedMarketBar, StrategyDecision,
)


MODE = "technical_only_historical_v1"


@dataclass(frozen=True, slots=True)
class TechnicalOnlyResearchResult:
    mode: str
    classification: str
    decisions: tuple[StrategyDecision, ...]


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field} must be timezone-aware UTC")


def run_technical_only(*, mode: str, bars: tuple[NormalizedMarketBar, ...], information_cutoff_utc: datetime, strategy_id: str, strategy_version: str, parameter_version: str, universe_version: str, code_revision: str) -> TechnicalOnlyResearchResult:
    if mode != MODE:
        raise ValueError("unknown research mode; explicit technical-only mode is required")
    _utc(information_cutoff_utc, "information_cutoff_utc")
    decisions = []
    for bar in bars:
        if not isinstance(bar, NormalizedMarketBar):
            raise TypeError("bars must contain NormalizedMarketBar contracts")
        eligible = bar.bar_status is BarStatus.COMPLETED and bar.quality_status is DataQualityStatus.VALID and bar.bar_end_utc <= information_cutoff_utc
        reason = () if eligible else ("bar_not_eligible_for_historical_decision",)
        action = DecisionAction.BUY if eligible and bar.close_price > bar.open_price else DecisionAction.NO_ACTION
        status = DecisionStatus.ELIGIBLE if eligible else DecisionStatus.REJECTED
        decision_timestamp = max(bar.bar_end_utc, information_cutoff_utc)
        decisions.append(StrategyDecision(
            decision_id=f"{MODE}:{bar.source_record_id}", strategy_id=strategy_id,
            strategy_version=strategy_version, instrument_id=bar.instrument_id,
            decision_timestamp_utc=decision_timestamp,
            information_cutoff_utc=information_cutoff_utc,
            eligible_execution_timestamp_utc=decision_timestamp,
            decision_action=action, decision_status=status,
            signal_value=Decimal("1") if action is DecisionAction.BUY else Decimal("0"),
            target_weight=Decimal("0.10") if action is DecisionAction.BUY else Decimal("0"),
            currency=bar.currency, price_unit=bar.price_unit,
            quality_status=bar.quality_status, reason_codes=reason,
            dataset_version=bar.source_dataset_id, universe_version=universe_version,
            parameter_version=parameter_version, code_revision=code_revision,
        ))
    return TechnicalOnlyResearchResult(MODE, "exploratory_unverified", tuple(decisions))
