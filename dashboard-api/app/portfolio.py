from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .models import (
    AllocationItem,
    AllocationSummary,
    AvailabilityField,
    CashSummary,
    PortfolioHolding,
    PortfolioHoldings,
    PortfolioResponse,
    PortfolioValueSummary,
    SnapshotSelectionPolicy,
)
from .overview import DATA_ROOT, FRESHNESS_THRESHOLD_SECONDS, decimal_text, parse_datetime, parse_decimal, read_csv

HOLDINGS_COLUMNS = {
    "date",
    "ticker",
    "shares",
    "entry_price",
    "current_price",
    "market_value",
    "unrealised_pnl",
    "unrealised_pnl_percent",
}
PORTFOLIO_COLUMNS = {"Date", "daily_return", "equity", "peak", "drawdown", "trading_cost"}


def unavailable(reason: str) -> AvailabilityField:
    return AvailabilityField(availability="unavailable", reason=reason)


def available() -> AvailabilityField:
    return AvailabilityField(availability="available")


def snapshot_policy() -> SnapshotSelectionPolicy:
    return SnapshotSelectionPolicy(
        identity_field="ticker",
        timestamp_field="date",
        required_columns=sorted(HOLDINGS_COLUMNS),
        completeness_rule="A timestamp group must contain every observed instrument identity exactly once with valid UTC timestamps and finite Decimal values.",
        selection_rule="Select the latest complete timestamp group; never combine rows from different timestamps.",
    )


def load_portfolio_value(path: Path) -> tuple[Decimal | None, datetime | None, AvailabilityField, list[str]]:
    try:
        rows = read_csv(path, PORTFOLIO_COLUMNS)
        parsed: list[tuple[datetime, Decimal]] = []
        seen: set[datetime] = set()
        for row in rows:
            as_of = parse_datetime(row["Date"], "Date", date_only=True)
            if as_of in seen:
                raise ValueError("duplicate portfolio dates")
            seen.add(as_of)
            parsed.append((as_of, parse_decimal(row["equity"], "equity")))
        as_of, value = max(parsed, key=lambda item: item[0])
        return value, as_of, available(), []
    except ValueError as exc:
        reason = f"Portfolio value is unavailable: {exc}."
        return None, None, unavailable(reason), [reason]


def load_complete_holdings(path: Path) -> tuple[PortfolioHoldings, AllocationSummary, Decimal | None, list[str]]:
    try:
        rows = read_csv(path, HOLDINGS_COLUMNS)
        groups: dict[datetime, list[tuple[str, dict[str, Decimal]]]] = defaultdict(list)
        observed_instruments: set[str] = set()
        for row in rows:
            instrument = row["ticker"].strip()
            if not instrument:
                raise ValueError("missing instrument identity")
            observed_instruments.add(instrument)
            as_of = parse_datetime(row["date"], "date")
            values = {
                "shares": parse_decimal(row["shares"], "shares"),
                "entry_price": parse_decimal(row["entry_price"], "entry_price"),
                "current_price": parse_decimal(row["current_price"], "current_price"),
                "market_value": parse_decimal(row["market_value"], "market_value"),
                "unrealised_pnl": parse_decimal(row["unrealised_pnl"], "unrealised_pnl"),
                "unrealised_pnl_percent": parse_decimal(row["unrealised_pnl_percent"], "unrealised_pnl_percent"),
            }
            groups[as_of].append((instrument, values))

        candidates: list[tuple[datetime, list[tuple[str, dict[str, Decimal]]]]] = []
        for as_of, group in groups.items():
            instruments = [item[0] for item in group]
            if len(instruments) != len(set(instruments)):
                continue
            if set(instruments) == observed_instruments:
                candidates.append((as_of, group))
        if not candidates:
            reason = "No complete holdings snapshot is available; the observed instrument universe is split across multiple timestamps or contains invalid rows."
            return PortfolioHoldings(availability=unavailable(reason)), AllocationSummary(availability=unavailable(reason)), None, [reason]

        as_of, selected = max(candidates, key=lambda item: item[0])
        items = [
            PortfolioHolding(
                instrument=instrument,
                quantity=decimal_text(values["shares"]),
                entry_price=decimal_text(values["entry_price"]),
                current_price=decimal_text(values["current_price"]),
                market_value=decimal_text(values["market_value"]),
                unrealised_pnl=decimal_text(values["unrealised_pnl"]),
                unrealised_pnl_percent=decimal_text(values["unrealised_pnl_percent"]),
            )
            for instrument, values in selected
        ]
        items.sort(key=lambda item: item.instrument)
        total = sum((Decimal(item.market_value) for item in items), Decimal("0"))
        allocation_items = [
            AllocationItem(
                instrument=item.instrument,
                market_value=item.market_value,
                weight_percent=decimal_text((Decimal(item.market_value) / total) * Decimal("100")),
            )
            for item in items
        ] if total else []
        return PortfolioHoldings(as_of_utc=as_of, items=items, availability=available()), AllocationSummary(items=allocation_items, availability=available()), total, []
    except ValueError as exc:
        reason = f"Holdings are unavailable: {exc}."
        return PortfolioHoldings(availability=unavailable(reason)), AllocationSummary(availability=unavailable(reason)), None, [reason]


def freshness(generated: datetime, source_as_of: datetime | None) -> dict[str, object]:
    if source_as_of is None or generated < source_as_of:
        return {"source_as_of_utc": source_as_of, "snapshot_age_seconds": None, "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS, "status": "unavailable"}
    age = int((generated - source_as_of).total_seconds())
    return {"source_as_of_utc": source_as_of, "snapshot_age_seconds": age, "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS, "status": "stale" if age > FRESHNESS_THRESHOLD_SECONDS else "fresh"}


def build_portfolio(generated_at: datetime | None = None, data_root: Path = DATA_ROOT) -> PortfolioResponse:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    value, value_as_of, value_availability, value_warnings = load_portfolio_value(data_root / "portfolio_v2.csv")
    holdings, allocation, holdings_total, holdings_warnings = load_complete_holdings(data_root / "holdings_report.csv")
    warnings = value_warnings + holdings_warnings
    source_as_of = holdings.as_of_utc or value_as_of
    if holdings.as_of_utc is not None and holdings.as_of_utc == value_as_of and holdings_total is not None and value is not None:
        reconciliation = available() if holdings_total == value else unavailable("Holdings total does not equal portfolio equity at the same timestamp.")
    else:
        reconciliation = unavailable("Holdings and portfolio equity do not share an exact source timestamp.")
    classification = "local_snapshot" if not warnings else "partial"
    return PortfolioResponse(
        schema_version="portfolio.v1",
        generated_at_utc=generated,
        source_as_of_utc=source_as_of,
        source_classification=classification,
        freshness=freshness(generated, source_as_of),
        warnings=warnings,
        snapshot_selection_policy=snapshot_policy(),
        portfolio_summary=PortfolioValueSummary(
            portfolio_value=decimal_text(value) if value is not None else None,
            as_of_utc=value_as_of,
            holdings_market_value=decimal_text(holdings_total) if holdings_total is not None else None,
            holdings_as_of_utc=holdings.as_of_utc,
            reconciliation=reconciliation,
            availability=value_availability,
        ),
        holdings=holdings,
        allocation=allocation,
        cash=CashSummary(availability=unavailable("No explicit cash source shares the selected portfolio timestamp.")),
        section_availability={
            "portfolio_summary": value_availability,
            "holdings": holdings.availability,
            "allocation": allocation.availability,
            "cash": unavailable("No explicit cash source shares the selected portfolio timestamp."),
            "reconciliation": reconciliation,
        },
    )
