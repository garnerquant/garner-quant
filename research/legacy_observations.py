"""Immutable, caller-supplied observations from legacy research outputs.

This module never opens repository files and never infers missing timing,
currency, units, availability, or methodology quality.
"""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import io
import json
import unicodedata


CLASSIFICATIONS = frozenset({
    "legacy_methodologically_invalid",
    "legacy_unverified",
    "paper_observation_unverified",
    "operational_evidence_not_quantitative_validation",
    "accounting_evidence_not_quantitative_validation",
})
PARSING_STATUSES = frozenset({"parsed", "unavailable", "rejected"})


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")
    return value


def _classification(value):
    if value not in CLASSIFICATIONS:
        raise ValueError("unknown legacy methodology classification")
    return value


def _status(value):
    if value not in PARSING_STATUSES:
        raise ValueError("unknown parsing status")
    return value


def _decimal(value, field, *, optional=True):
    if value is None and optional:
        return None
    if isinstance(value, (bool, float)) or not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{field} must be a finite Decimal or None")
    return value


def _utc(value, field):
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
        raise ValueError(f"{field} must be timezone-aware UTC or None")


def _canonical(value):
    if value is None or isinstance(value, (str, int, bool)):
        return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, datetime):
        _utc(value, "datetime")
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    raise TypeError(f"unsupported legacy canonical value: {type(value).__name__}")


def _hash(value):
    raw = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacySignalObservation:
    schema_version: int
    legacy_source_type: str
    source_artifact_hash: str
    source_row_id: str
    instrument_id: str
    observation_date: date | None
    observation_timestamp_utc: datetime | None
    available_timestamp_utc: datetime | None
    signal_value: Decimal | None
    weight: Decimal | None
    weight_unit: str | None
    status: str | None
    currency: str | None
    price_unit: str | None
    methodology_classification: str
    parsing_status: str
    limitations: tuple[str, ...]
    raw_field_provenance: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0: raise ValueError("schema_version must be positive")
        for field in ("legacy_source_type", "source_artifact_hash", "source_row_id", "instrument_id"):
            _text(getattr(self, field), field)
        if self.observation_date is not None and not isinstance(self.observation_date, date): raise TypeError("observation_date must be a date")
        _utc(self.observation_timestamp_utc, "observation_timestamp_utc"); _utc(self.available_timestamp_utc, "available_timestamp_utc")
        _decimal(self.signal_value, "signal_value"); _decimal(self.weight, "weight")
        if self.weight_unit is not None: _text(self.weight_unit, "weight_unit")
        if self.currency is not None and (not isinstance(self.currency, str) or self.currency != self.currency.upper()): raise ValueError("currency must be uppercase when known")
        if self.price_unit is not None: _text(self.price_unit, "price_unit")
        _classification(self.methodology_classification); _status(self.parsing_status)
        if any(not isinstance(x, str) or not x.strip() for x in self.limitations): raise ValueError("limitations must be nonblank strings")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.raw_field_provenance): raise ValueError("raw_field_provenance must contain string pairs")

    @property
    def canonical_hash(self): return _hash(self)


@dataclass(frozen=True, slots=True)
class LegacyWeightObservation:
    schema_version: int
    legacy_source_type: str
    source_artifact_hash: str
    source_row_id: str
    instrument_id: str
    observation_date: date | None
    observation_timestamp_utc: datetime | None
    available_timestamp_utc: datetime | None
    weight: Decimal | None
    weight_unit: str | None
    notional: Decimal | None
    quantity: Decimal | None
    price: Decimal | None
    currency: str | None
    price_unit: str | None
    methodology_classification: str
    parsing_status: str
    limitations: tuple[str, ...]
    raw_field_provenance: tuple[tuple[str, str], ...]

    def __post_init__(self):
        LegacySignalObservation( self.schema_version, self.legacy_source_type, self.source_artifact_hash, self.source_row_id, self.instrument_id, self.observation_date, self.observation_timestamp_utc, self.available_timestamp_utc, None, self.weight, self.weight_unit, None, self.currency, self.price_unit, self.methodology_classification, self.parsing_status, self.limitations, self.raw_field_provenance)
        _decimal(self.notional, "notional"); _decimal(self.quantity, "quantity"); _decimal(self.price, "price")

    @property
    def canonical_hash(self): return _hash(self)


@dataclass(frozen=True, slots=True)
class LegacyPortfolioProjection:
    schema_version: int
    legacy_source_type: str
    source_artifact_hash: str
    source_row_id: str
    observation_date: date | None
    portfolio_value: Decimal | None
    cash: Decimal | None
    realised_pnl: Decimal | None
    unrealised_pnl: Decimal | None
    benchmark_return: Decimal | None
    currency: str | None
    methodology_classification: str
    parsing_status: str
    limitations: tuple[str, ...]
    raw_field_provenance: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0: raise ValueError("schema_version must be positive")
        for field in ("legacy_source_type", "source_artifact_hash", "source_row_id"): _text(getattr(self, field), field)
        if self.observation_date is not None and not isinstance(self.observation_date, date): raise TypeError("observation_date must be a date")
        for field in ("portfolio_value", "cash", "realised_pnl", "unrealised_pnl", "benchmark_return"): _decimal(getattr(self, field), field)
        if self.currency is not None and self.currency != self.currency.upper(): raise ValueError("currency must be uppercase when known")
        _classification(self.methodology_classification); _status(self.parsing_status)

    @property
    def canonical_hash(self): return _hash(self)


@dataclass(frozen=True, slots=True)
class LegacyObservationSet:
    schema_version: int
    signals: tuple[LegacySignalObservation, ...]
    weights: tuple[LegacyWeightObservation, ...]
    projections: tuple[LegacyPortfolioProjection, ...]
    methodology_classification: str
    limitations: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0: raise ValueError("schema_version must be positive")
        _classification(self.methodology_classification)
        if any(not isinstance(x, (LegacySignalObservation, LegacyWeightObservation, LegacyPortfolioProjection)) for x in (*self.signals, *self.weights, *self.projections)): raise TypeError("invalid legacy observation type")
        identities = [(x.legacy_source_type, x.source_row_id) for x in (*self.signals, *self.weights, *self.projections)]
        if len(identities) != len(set(identities)): raise ValueError("duplicate legacy observation identity")

    @property
    def canonical_hash(self): return _hash(LegacyObservationSet(self.schema_version, tuple(sorted(self.signals, key=lambda x: (x.instrument_id, x.source_row_id))), tuple(sorted(self.weights, key=lambda x: (x.instrument_id, x.source_row_id))), tuple(sorted(self.projections, key=lambda x: x.source_row_id)), self.methodology_classification, tuple(sorted(self.limitations))))


@dataclass(frozen=True, slots=True)
class LegacyParseResult:
    schema_version: int
    parser_version: str
    source_artifact_hash: str
    observations: LegacyObservationSet | None
    status: str
    errors: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.schema_version, int) or self.schema_version <= 0: raise ValueError("schema_version must be positive")
        _text(self.parser_version, "parser_version"); _text(self.source_artifact_hash, "source_artifact_hash")
        _status(self.status)
        if any(not isinstance(x, str) or not x.strip() for x in self.errors): raise ValueError("errors must be nonblank strings")

    @property
    def canonical_hash(self): return _hash(self)


def _parse_decimal(value, field):
    if value in (None, ""): return None
    try: return Decimal(value)
    except (InvalidOperation, ValueError): raise ValueError(f"invalid Decimal in {field}")


def parse_signal_report_csv(text: str, *, source_artifact_hash: str, parser_version: str, weight_unit: str, methodology_classification: str = "legacy_methodologically_invalid") -> LegacyParseResult:
    _text(text, "text"); _text(weight_unit, "weight_unit"); _classification(methodology_classification)
    expected = ("date", "ticker", "signal", "weight", "status")
    try:
        rows = list(csv.DictReader(io.StringIO(text), delimiter=","))
        if not rows: raise ValueError("signal report contains no rows")
        if tuple(rows[0].keys()) != expected: raise ValueError("unexpected signal report header")
        observations = []
        identities = set()
        for index, row in enumerate(rows, 1):
            if any(value is None for value in row.values()): raise ValueError("malformed signal report row")
            day = date.fromisoformat(row["date"]) if row["date"] else None
            identity = (row["ticker"], day)
            if identity in identities: raise ValueError("duplicate signal observation identity")
            identities.add(identity)
            observations.append(LegacySignalObservation(1, "signal_report_v2", source_artifact_hash, f"{row['ticker']}|{row['date']}", row["ticker"], day, None, None, _parse_decimal(row["signal"], "signal"), _parse_decimal(row["weight"], "weight"), weight_unit, row["status"] or None, None, None, methodology_classification, "parsed", ("observation_timestamp", "date_only"), (("date", row["date"]), ("ticker", row["ticker"]), ("signal", row["signal"]), ("weight", row["weight"]))))
        obs = LegacyObservationSet(1, tuple(observations), (), (), methodology_classification, ("availability_timestamp_missing", "currency_and_price_unit_missing"))
        return LegacyParseResult(1, parser_version, source_artifact_hash, obs, "parsed", ())
    except (csv.Error, ValueError, TypeError, IndexError) as exc:
        return LegacyParseResult(1, parser_version, source_artifact_hash, None, "rejected", (str(exc),))
