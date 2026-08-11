from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import (
    AllocationItem,
    AllocationSummary,
    AvailabilityField,
    HoldingSummary,
    OverviewResponse,
    PerformancePoint,
    PerformanceSeries,
    PortfolioSummary,
    SafetySummary,
    SafetyValue,
    SignalItem,
    SignalSummary,
    SourceFile,
)

DATA_ROOT = Path(os.environ.get("DASHBOARD_API_DATA_ROOT", "/data/snapshots"))
CONFIG_ROOT = Path(os.environ.get("DASHBOARD_API_CONFIG_ROOT", "/data/config"))
FRESHNESS_THRESHOLD_SECONDS = 24 * 60 * 60


def unavailable(reason: str) -> AvailabilityField:
    return AvailabilityField(availability="unavailable", reason=reason)


def available() -> AvailabilityField:
    return AvailabilityField(availability="available")


def parse_decimal(value: str, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Decimal in {field}") from exc
    if not parsed.is_finite():
        raise ValueError(f"invalid Decimal in {field}")
    return parsed


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def parse_datetime(value: str, field: str, date_only: bool = False) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d") if date_only else datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp in {field}") from exc
    if date_only:
        return datetime.combine(parsed.date(), datetime.min.time(), tzinfo=UTC)
    if parsed.tzinfo is None:
        return datetime.combine(parsed.date(), parsed.time(), tzinfo=UTC)
    return datetime.fromtimestamp(parsed.timestamp(), tz=UTC)


def read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not required_columns.issubset(set(reader.fieldnames)):
                raise ValueError("unsupported or missing columns")
            rows = list(reader)
    except FileNotFoundError as exc:
        raise ValueError("source file is missing") from exc
    except csv.Error as exc:
        raise ValueError("malformed CSV") from exc
    if not rows:
        raise ValueError("source file is empty")
    if any(any(value is None or value == "" for value in row.values()) for row in rows):
        raise ValueError("source contains missing values")
    return rows


def source(name: str, row_count: int, as_of: datetime | None, warning: str | None = None) -> SourceFile:
    classification = "local_snapshot" if warning is None else "unavailable"
    return SourceFile(
        name=name,
        classification=classification,
        as_of_utc=as_of,
        row_count=row_count,
        completeness="available" if warning is None else "unavailable",
        warning=warning,
    )


def load_portfolio(path: Path) -> tuple[PortfolioSummary, PerformanceSeries, SourceFile, list[str]]:
    warnings: list[str] = []
    try:
        rows = read_csv(path, {"Date", "daily_return", "equity", "peak", "drawdown", "trading_cost"})
        parsed: list[tuple[datetime, Decimal, Decimal, Decimal]] = []
        seen_dates: set[datetime] = set()
        for row in rows:
            as_of = parse_datetime(row["Date"], "Date", date_only=True)
            if as_of in seen_dates:
                raise ValueError("duplicate portfolio dates")
            seen_dates.add(as_of)
            parsed.append((as_of, parse_decimal(row["equity"], "equity"), parse_decimal(row["daily_return"], "daily_return"), parse_decimal(row["drawdown"], "drawdown")))
        parsed.sort(key=lambda item: item[0])
        first, latest = parsed[0], parsed[-1]
        total_return = (latest[1] / first[1] - Decimal("1")) * Decimal("100") if first[1] != 0 else None
        points = [
            PerformancePoint(as_of_utc=as_of, equity=decimal_text(equity), daily_return_percent=decimal_text(daily * Decimal("100")), drawdown_percent=decimal_text(drawdown * Decimal("100")))
            for as_of, equity, daily, drawdown in parsed[-365:]
        ]
        summary = PortfolioSummary(
            portfolio_value=decimal_text(latest[1]),
            cash=None,
            daily_change_percent=decimal_text(latest[2] * Decimal("100")),
            total_return_percent=decimal_text(total_return) if total_return is not None else None,
            latest_recorded_change_as_of_utc=latest[0],
            availability={
                "portfolio_value": available(),
                "cash": unavailable("cash is not present in portfolio_v2.csv"),
                "daily_change_percent": available(),
                "total_return_percent": available() if total_return is not None else unavailable("initial equity is zero"),
            },
        )
        return summary, PerformanceSeries(items=points, availability=available()), source(path.name, len(rows), latest[0]), warnings
    except ValueError as exc:
        message = f"{path.name}: {exc}"
        warnings.append(message)
        summary = PortfolioSummary(portfolio_value=None, cash=None, daily_change_percent=None, total_return_percent=None, availability={key: unavailable(message) for key in ("portfolio_value", "cash", "daily_change_percent", "total_return_percent")})
        return summary, PerformanceSeries(availability=unavailable(message)), source(path.name, 0, None, message), warnings


def load_holdings(path: Path) -> tuple[HoldingSummary, AllocationSummary, SourceFile, list[str]]:
    warnings: list[str] = []
    try:
        rows = read_csv(path, {"date", "ticker", "shares", "entry_price", "current_price", "market_value", "unrealised_pnl", "unrealised_pnl_percent"})
        timestamps = {parse_datetime(row["date"], "date") for row in rows}
        instruments = [row["ticker"] for row in rows]
        if len(instruments) != len(set(instruments)):
            raise ValueError("duplicate instruments")
        if len(timestamps) != 1:
            raise ValueError("inconsistent timestamps")
        as_of = next(iter(timestamps))
        normalized = []
        market_values: list[Decimal] = []
        for row in rows:
            value = parse_decimal(row["market_value"], "market_value")
            market_values.append(value)
            normalized.append({
                "instrument": row["ticker"], "quantity": decimal_text(parse_decimal(row["shares"], "shares")),
                "entry_price": decimal_text(parse_decimal(row["entry_price"], "entry_price")),
                "current_price": decimal_text(parse_decimal(row["current_price"], "current_price")),
                "market_value": decimal_text(value),
                "unrealised_pnl": decimal_text(parse_decimal(row["unrealised_pnl"], "unrealised_pnl")),
            })
        total = sum(market_values, Decimal("0"))
        allocations = [AllocationItem(instrument=row["instrument"], market_value=row["market_value"], weight_percent=decimal_text((Decimal(row["market_value"]) / total) * Decimal("100"))) for row in normalized] if total != 0 else []
        normalized.sort(key=lambda row: row["instrument"])
        allocations.sort(key=lambda item: item.instrument)
        return HoldingSummary(as_of_utc=as_of, holdings=normalized, availability=available()), AllocationSummary(items=allocations, availability=available()), source(path.name, len(rows), as_of), warnings
    except ValueError as exc:
        message = f"{path.name}: {exc}"
        warnings.append(message)
        return HoldingSummary(availability=unavailable(message)), AllocationSummary(availability=unavailable(message)), source(path.name, 0, None, message), warnings


def load_signals(path: Path) -> tuple[SignalSummary, SourceFile, list[str]]:
    warnings: list[str] = []
    try:
        rows = read_csv(path, {"date", "ticker", "signal", "weight", "status"})
        dates = {parse_datetime(row["date"], "date", date_only=True) for row in rows}
        instruments = [row["ticker"] for row in rows]
        if len(instruments) != len(set(instruments)):
            raise ValueError("duplicate instruments")
        if len(dates) != 1:
            raise ValueError("inconsistent timestamps")
        as_of = next(iter(dates))
        items = [SignalItem(instrument=row["ticker"], status=row["status"], signal_code=decimal_text(parse_decimal(row["signal"], "signal")), target_weight=decimal_text(parse_decimal(row["weight"], "weight")), as_of_utc=as_of) for row in rows]
        items.sort(key=lambda item: item.instrument)
        return SignalSummary(items=items, availability=available()), source(path.name, len(rows), as_of), warnings
    except ValueError as exc:
        message = f"{path.name}: {exc}"
        warnings.append(message)
        return SignalSummary(availability=unavailable(message)), source(path.name, 0, None, message), warnings


def load_runtime_safety(path: Path) -> tuple[dict[str, SafetyValue], SourceFile, list[str]]:
    warnings: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("unsupported configuration document")
        mode = config.get("mode")
        paper = config.get("paper_execution_enabled")
        if not isinstance(mode, str) or not isinstance(paper, bool):
            raise ValueError("unsupported or missing configuration fields")
        return {
            "mode": SafetyValue(value="Monitor only" if mode == "monitor_only" else mode, availability=available()),
            "paper_execution_enabled": SafetyValue(value="Disabled" if paper is False else "Enabled", availability=available()),
        }, source(path.name, 1, None), warnings
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        message = f"{path.name}: {exc}"
        warnings.append(message)
        return {
            "mode": SafetyValue(availability=unavailable(message)),
            "paper_execution_enabled": SafetyValue(availability=unavailable(message)),
        }, source(path.name, 0, None, message), warnings


def load_risk_safety(path: Path) -> tuple[dict[str, SafetyValue], SourceFile, list[str]]:
    warnings: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("unsupported configuration document")
        trading_enabled = config.get("trading_enabled")
        limits_approved = config.get("limits_approved")
        if not isinstance(trading_enabled, bool) or not isinstance(limits_approved, bool):
            raise ValueError("unsupported or missing configuration fields")
        return {
            "trading_enabled": SafetyValue(value="Enabled" if trading_enabled else "Disabled", availability=available()),
            "limits_approved": SafetyValue(value="Yes" if limits_approved else "No", availability=available()),
        }, source(path.name, 1, None), warnings
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        message = f"{path.name}: {exc}"
        warnings.append(message)
        return {
            "trading_enabled": SafetyValue(availability=unavailable(message)),
            "limits_approved": SafetyValue(availability=unavailable(message)),
        }, source(path.name, 0, None, message), warnings


def build_overview(generated_at: datetime | None = None, data_root: Path = DATA_ROOT, config_root: Path = CONFIG_ROOT) -> OverviewResponse:
    portfolio, performance, portfolio_source, portfolio_warnings = load_portfolio(data_root / "portfolio_v2.csv")
    holdings, allocation, holdings_source, holdings_warnings = load_holdings(data_root / "holdings_report.csv")
    signals, signals_source, signals_warnings = load_signals(data_root / "signal_report_v2.csv")
    runtime_safety, runtime_source, runtime_warnings = load_runtime_safety(config_root / "live_runtime_config.json")
    risk_safety, risk_source, risk_warnings = load_risk_safety(config_root / "risk_config.json")
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    source_as_of = portfolio_source.as_of_utc if portfolio_source.classification == "local_snapshot" else None
    if source_as_of is None:
        freshness_status, snapshot_age_seconds = "unavailable", None
    elif generated < source_as_of:
        freshness_status, snapshot_age_seconds = "unavailable", None
        portfolio_warnings.append("portfolio_v2.csv: source timestamp is later than response generation time")
    else:
        snapshot_age_seconds = int((generated - source_as_of).total_seconds())
        freshness_status = "stale" if snapshot_age_seconds > FRESHNESS_THRESHOLD_SECONDS else "fresh"
    warnings = portfolio_warnings + holdings_warnings + signals_warnings + runtime_warnings + risk_warnings
    sources = [portfolio_source, holdings_source, signals_source, runtime_source, risk_source]
    classification = "local_snapshot" if not warnings else "partial"
    return OverviewResponse(
        schema_version="overview.v1",
        generated_at_utc=generated,
        source_as_of_utc=source_as_of,
        snapshot_freshness={
            "source_as_of_utc": source_as_of,
            "snapshot_age_seconds": snapshot_age_seconds,
            "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS,
            "status": freshness_status,
        },
        source_classification=classification,
        source_files=sources,
        source_freshness=sources,
        warnings=warnings,
        portfolio_summary=portfolio,
        holdings_summary=holdings,
        allocation=allocation,
        recent_signals=signals,
        performance_series=performance,
        risk_safety_summary=SafetySummary(**runtime_safety, **risk_safety),
    )
