"""Decimal total-return calculations and per-observation GBP benchmark conversion."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from data.fx import FxObservation, convert_currency
from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value): raise ValueError(f"{field} must be UTC")


def _decimal(value, field):
    if not isinstance(value, Decimal) or not value.is_finite(): raise TypeError(f"{field} must be finite Decimal")


@dataclass(frozen=True, slots=True)
class ReturnCalculationPolicy:
    schema_version: int
    policy_id: str
    policy_version: str
    price_basis: str
    base_currency: str = "GBP"


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    schema_version: int
    instrument_id: str
    observation_timestamp: datetime
    information_cutoff: datetime
    price_basis: str
    prior_price: Decimal | None
    current_price: Decimal
    return_value: Decimal | None
    source_dataset_id: str
    source_record_id: str
    status: str
    reason: str
    fx_observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    schema_version: int
    instrument_id: str
    observations: tuple[ReturnObservation, ...]
    policy: ReturnCalculationPolicy

    def canonical_bytes(self):
        def d(value): return None if value is None else ("0" if value == 0 else format(value.normalize(), "f"))
        payload = {"schema_version": self.schema_version, "instrument_id": self.instrument_id, "policy": {"schema_version": self.policy.schema_version, "policy_id": self.policy.policy_id, "policy_version": self.policy.policy_version, "price_basis": self.policy.price_basis, "base_currency": self.policy.base_currency}, "observations": [{"schema_version": x.schema_version, "instrument_id": x.instrument_id, "observation_timestamp": x.observation_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "information_cutoff": x.information_cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "price_basis": x.price_basis, "prior_price": d(x.prior_price), "current_price": d(x.current_price), "return_value": d(x.return_value), "source_dataset_id": x.source_dataset_id, "source_record_id": x.source_record_id, "status": x.status, "reason": x.reason, "fx_observation_id": x.fx_observation_id} for x in self.observations]}
        return json.dumps({"contract_type": "return_series", "schema_version": 1, "payload": payload}, sort_keys=True, separators=(",", ":")).encode()

    def canonical_sha256(self): return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    schema_version: int
    portfolio_cumulative_return: Decimal
    benchmark_cumulative_return: Decimal
    arithmetic_excess_return: Decimal
    aligned_observation_count: int
    comparison_start: datetime
    comparison_end: datetime
    exclusions: tuple[str, ...]
    result_classification: str = "exploratory_unverified"
    warnings: tuple[str, ...] = ()

    def canonical_sha256(self):
        raw = json.dumps({"portfolio": str(self.portfolio_cumulative_return), "benchmark": str(self.benchmark_cumulative_return), "excess": str(self.arithmetic_excess_return), "count": self.aligned_observation_count, "start": self.comparison_start.isoformat(), "end": self.comparison_end.isoformat(), "exclusions": list(self.exclusions)}, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def _validate_bar(bar, cutoff):
    if not isinstance(bar, NormalizedMarketBar): raise TypeError("return inputs must be NormalizedMarketBar")
    if bar.bar_status is not BarStatus.COMPLETED or bar.quality_status is not DataQualityStatus.VALID: raise ValueError("bar is not eligible")
    if bar.bar_end_utc > cutoff: raise ValueError("bar is after information cutoff")
    if bar.close_price <= 0: raise ValueError("price must be positive")


def calculate_return_series(*, bars: tuple[NormalizedMarketBar, ...], policy: ReturnCalculationPolicy, information_cutoff: datetime) -> ReturnSeries:
    _utc(information_cutoff, "information_cutoff")
    ordered = sorted(bars, key=lambda b: b.bar_end_utc)
    if len({b.bar_end_utc for b in ordered}) != len(ordered): raise ValueError("duplicate return timestamps")
    if not ordered: raise ValueError("no return observations")
    result, prior = [], None
    for bar in ordered:
        _validate_bar(bar, information_cutoff)
        value = None if prior is None else bar.close_price / prior - Decimal("1")
        result.append(ReturnObservation(1, bar.instrument_id, bar.bar_end_utc, information_cutoff, policy.price_basis, prior, bar.close_price, value, bar.source_dataset_id, bar.source_record_id, "unavailable" if value is None else "eligible", "no_prior_observation" if value is None else "calculated"))
        prior = bar.close_price
    return ReturnSeries(1, ordered[0].instrument_id, tuple(result), policy)


def calculate_gbp_benchmark(*, bars: tuple[NormalizedMarketBar, ...], fx_by_timestamp: tuple[FxObservation, ...], policy: ReturnCalculationPolicy, information_cutoff: datetime) -> ReturnSeries:
    fx = {item.observed_at_utc: item for item in fx_by_timestamp}
    converted = []
    for bar in sorted(bars, key=lambda b: b.bar_end_utc):
        _validate_bar(bar, information_cutoff)
        observation = fx.get(bar.bar_end_utc)
        if observation is None: raise ValueError("missing FX observation for benchmark timestamp")
        converted_value = convert_currency(bar.close_price, "USD", "GBP", observation=observation, information_cutoff_utc=information_cutoff)
        converted.append((bar, converted_value, observation.source_record_id))
    synthetic = tuple(NormalizedMarketBar(b.instrument_id, b.bar_start_utc, b.bar_end_utc, b.session_date, b.open_price * (converted_value / b.close_price), b.high_price * (converted_value / b.close_price), b.low_price * (converted_value / b.close_price), converted_value, b.volume, "GBP", "GBP", b.bar_status, b.quality_status, b.source_dataset_id, b.source_record_id) for b, converted_value, _ in converted)
    series = calculate_return_series(bars=synthetic, policy=policy, information_cutoff=information_cutoff)
    return ReturnSeries(series.schema_version, series.instrument_id, tuple(ReturnObservation(x.schema_version, x.instrument_id, x.observation_timestamp, x.information_cutoff, x.price_basis, x.prior_price, x.current_price, x.return_value, x.source_dataset_id, x.source_record_id, x.status, x.reason, fx[x.observation_timestamp].source_record_id) for x in series.observations), series.policy)


def compare_returns(portfolio: ReturnSeries, benchmark: ReturnSeries) -> BenchmarkComparison:
    p = {x.observation_timestamp: x for x in portfolio.observations if x.return_value is not None}; b = {x.observation_timestamp: x for x in benchmark.observations if x.return_value is not None}; aligned = sorted(set(p) & set(b))
    if not aligned: raise ValueError("no aligned eligible returns")
    portfolio_cumulative = (Decimal("1") + p[aligned[0]].return_value)
    benchmark_cumulative = (Decimal("1") + b[aligned[0]].return_value)
    for timestamp in aligned[1:]: portfolio_cumulative *= Decimal("1") + p[timestamp].return_value; benchmark_cumulative *= Decimal("1") + b[timestamp].return_value
    portfolio_cumulative -= Decimal("1"); benchmark_cumulative -= Decimal("1")
    return BenchmarkComparison(1, portfolio_cumulative, benchmark_cumulative, portfolio_cumulative - benchmark_cumulative, len(aligned), aligned[0], aligned[-1], ())
