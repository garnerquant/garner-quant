from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Availability = Literal["available", "partial", "unavailable"]
SourceClassification = Literal["local_snapshot", "partial", "unavailable"]


class AvailabilityField(BaseModel):
    availability: Availability
    reason: str | None = None


class SourceFile(BaseModel):
    name: str
    classification: SourceClassification
    as_of_utc: datetime | None = None
    row_count: int = Field(ge=0)
    completeness: Availability
    warning: str | None = None


class PortfolioSummary(BaseModel):
    portfolio_value: str | None = None
    cash: str | None = None
    daily_change_percent: str | None = None
    total_return_percent: str | None = None
    latest_recorded_change_as_of_utc: datetime | None = None
    availability: dict[str, AvailabilityField]


class HoldingSummary(BaseModel):
    as_of_utc: datetime | None = None
    holdings: list[dict[str, str]] = []
    availability: AvailabilityField


class AllocationItem(BaseModel):
    instrument: str
    market_value: str
    weight_percent: str


class AllocationSummary(BaseModel):
    items: list[AllocationItem] = []
    availability: AvailabilityField


class SignalItem(BaseModel):
    instrument: str
    status: str
    signal_code: str
    target_weight: str
    as_of_utc: datetime


class SignalSummary(BaseModel):
    items: list[SignalItem] = []
    availability: AvailabilityField


class PerformancePoint(BaseModel):
    as_of_utc: datetime
    equity: str
    daily_return_percent: str
    drawdown_percent: str


class PerformanceSeries(BaseModel):
    items: list[PerformancePoint] = []
    availability: AvailabilityField


class SafetyValue(BaseModel):
    value: str | None = None
    availability: AvailabilityField


class SafetySummary(BaseModel):
    mode: SafetyValue
    paper_execution_enabled: SafetyValue
    trading_enabled: SafetyValue
    limits_approved: SafetyValue


class SnapshotFreshness(BaseModel):
    source_as_of_utc: datetime | None = None
    snapshot_age_seconds: int | None = Field(default=None, ge=0)
    freshness_threshold_seconds: int = Field(ge=0)
    status: Literal["fresh", "stale", "unavailable"]


class OverviewResponse(BaseModel):
    schema_version: Literal["overview.v1"]
    generated_at_utc: datetime
    source_as_of_utc: datetime | None = None
    snapshot_freshness: SnapshotFreshness
    source_classification: SourceClassification
    source_files: list[SourceFile]
    source_freshness: list[SourceFile]
    warnings: list[str]
    portfolio_summary: PortfolioSummary
    holdings_summary: HoldingSummary
    allocation: AllocationSummary
    recent_signals: SignalSummary
    performance_series: PerformanceSeries
    risk_safety_summary: SafetySummary
