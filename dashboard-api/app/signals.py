from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .models import AvailabilityField, SignalRecord, SignalsResponse
from .overview import DATA_ROOT, FRESHNESS_THRESHOLD_SECONDS, decimal_text, parse_datetime, parse_decimal, read_csv

SIGNAL_COLUMNS = {"date", "ticker", "signal", "weight", "status"}
SIGNAL_STATUS = {"0": "AVOID / SELL", "1": "HOLD / BUY"}


def unavailable(reason: str) -> AvailabilityField:
    return AvailabilityField(availability="unavailable", reason=reason)


def available() -> AvailabilityField:
    return AvailabilityField(availability="available")


def build_signals(generated_at: datetime | None = None, data_root: Path = DATA_ROOT) -> SignalsResponse:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    source = data_root / "signal_report_v2.csv"
    try:
        rows = read_csv(source, SIGNAL_COLUMNS)
        parsed: list[SignalRecord] = []
        dates: set[datetime] = set()
        instruments: set[str] = set()
        for row in rows:
            instrument = row["ticker"].strip()
            if not instrument or instrument in instruments:
                raise ValueError("missing or duplicate instrument")
            instruments.add(instrument)
            as_of = parse_datetime(row["date"], "date", date_only=True)
            dates.add(as_of)
            signal = parse_decimal(row["signal"], "signal")
            weight = parse_decimal(row["weight"], "weight")
            if signal not in (Decimal("0"), Decimal("1")):
                raise ValueError("unsupported signal code")
            if weight < 0 or weight > 1:
                raise ValueError("weight is outside the inclusive 0 to 1 range")
            status = row["status"].strip()
            if status != SIGNAL_STATUS[decimal_text(signal)]:
                raise ValueError("signal status is inconsistent")
            parsed.append(SignalRecord(instrument=instrument, signal_code=decimal_text(signal), status=status, target_weight=decimal_text(weight), as_of_utc=as_of))
        if len(dates) != 1:
            raise ValueError("inconsistent timestamps")
        parsed.sort(key=lambda item: item.instrument)
        source_as_of = next(iter(dates))
        age = int((generated - source_as_of).total_seconds())
        if age < 0:
            freshness = {"source_as_of_utc": source_as_of, "snapshot_age_seconds": None, "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS, "status": "unavailable"}
        else:
            freshness = {"source_as_of_utc": source_as_of, "snapshot_age_seconds": age, "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS, "status": "stale" if age > FRESHNESS_THRESHOLD_SECONDS else "fresh"}
        warnings = ["Signal snapshot is older than the local freshness threshold."] if freshness["status"] == "stale" else []
        return SignalsResponse(schema_version="signals.v1", generated_at_utc=generated, source_as_of_utc=source_as_of, source_classification="local_snapshot", freshness=freshness, warnings=warnings, source_file=source.name, items=parsed, availability=available())
    except ValueError as exc:
        reason = f"{source.name}: {exc}"
        return SignalsResponse(schema_version="signals.v1", generated_at_utc=generated, source_classification="unavailable", freshness={"status": "unavailable", "freshness_threshold_seconds": FRESHNESS_THRESHOLD_SECONDS}, warnings=[reason], source_file=source.name, availability=unavailable(reason))
