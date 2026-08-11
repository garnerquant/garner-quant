"""Deterministic in-memory builders for the approved strategy contracts."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import fields

from strategy.contract import (
    BarStatus,
    DataQualityStatus,
    DecisionAction,
    DecisionStatus,
    NormalizedMarketBar,
    StrategyDecision,
)


def _overridden(defaults, contract_type, overrides):
    field_names = {field.name for field in fields(contract_type)}
    unknown = set(overrides) - field_names
    if unknown:
        raise TypeError(f"unknown fixture fields: {', '.join(sorted(unknown))}")
    values = dict(defaults)
    values.update(overrides)
    return values


def make_market_bar(**overrides) -> NormalizedMarketBar:
    defaults = {
        "instrument_id": "SYNTHETIC-EQUITY",
        "bar_start_utc": datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
        "bar_end_utc": datetime(2026, 1, 5, 14, 31, tzinfo=timezone.utc),
        "session_date": date(2026, 1, 5),
        "open_price": Decimal("100"),
        "high_price": Decimal("105"),
        "low_price": Decimal("95"),
        "close_price": Decimal("102"),
        "volume": Decimal("1000"),
        "currency": "USD",
        "price_unit": "USD",
        "bar_status": BarStatus.COMPLETED,
        "quality_status": DataQualityStatus.VALID,
        "source_dataset_id": "synthetic-dataset-v1",
        "source_record_id": "synthetic-row-1",
    }
    return NormalizedMarketBar(**_overridden(defaults, NormalizedMarketBar, overrides))


def make_strategy_decision(**overrides) -> StrategyDecision:
    defaults = {
        "decision_id": "synthetic-decision-1",
        "strategy_id": "synthetic-strategy",
        "strategy_version": "synthetic-strategy-v1",
        "instrument_id": "SYNTHETIC-EQUITY",
        "decision_timestamp_utc": datetime(2026, 1, 5, 14, 31, tzinfo=timezone.utc),
        "information_cutoff_utc": datetime(2026, 1, 5, 14, 31, tzinfo=timezone.utc),
        "eligible_execution_timestamp_utc": datetime(2026, 1, 5, 14, 36, tzinfo=timezone.utc),
        "decision_action": DecisionAction.BUY,
        "decision_status": DecisionStatus.ELIGIBLE,
        "signal_value": Decimal("0.75"),
        "target_weight": Decimal("0.10"),
        "currency": "USD",
        "price_unit": "USD",
        "quality_status": DataQualityStatus.VALID,
        "reason_codes": (),
        "dataset_version": "synthetic-dataset-v1",
        "universe_version": "synthetic-universe-v1",
        "parameter_version": "synthetic-parameters-v1",
        "code_revision": "synthetic-code-v1",
    }
    return StrategyDecision(**_overridden(defaults, StrategyDecision, overrides))


def make_market_bar_series(count: int, **overrides) -> tuple[NormalizedMarketBar, ...]:
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("count must be a positive integer")
    if count <= 0:
        raise ValueError("count must be a positive integer")
    if overrides:
        unknown = set(overrides) - {field.name for field in fields(NormalizedMarketBar)}
        if unknown:
            raise TypeError(f"unknown fixture fields: {', '.join(sorted(unknown))}")
    bars = []
    for index in range(count):
        start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc) + timedelta(days=index)
        base = Decimal(100 + index)
        values = {
            "bar_start_utc": start,
            "bar_end_utc": start + timedelta(minutes=1),
            "session_date": date(2026, 1, 5) + timedelta(days=index),
            "open_price": base,
            "high_price": base + Decimal("5"),
            "low_price": base - Decimal("5"),
            "close_price": base + Decimal("2"),
            "volume": Decimal(1000 + index),
            "source_record_id": f"synthetic-row-{index + 1}",
            "instrument_id": "SYNTHETIC-EQUITY",
        }
        values.update(overrides)
        bars.append(make_market_bar(**values))
    return tuple(bars)
