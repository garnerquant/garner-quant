"""Read-only opening-snapshot evidence inventory and gap analysis.

This module deliberately has no persistence or accounting-publication API.  It
describes evidence already present; it never turns that evidence into lots or an
opening snapshot candidate.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from canonical_accounting.instruments import INSTRUMENT_REGISTRY

SCHEMA_VERSION = "1.0"
READINESS = "NOT_READY"


class EvidencePackError(ValueError):
    pass


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _json(asdict(value))
    return value


def _serialize(value: Any) -> str:
    return json.dumps(_json(value), sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_serialize(value).encode("utf-8")).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EvidencePackError(f"invalid {field}") from exc
    if not result.is_finite():
        raise EvidencePackError(f"invalid {field}")
    return result


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def _coverage(rows: list[dict[str, str]]) -> tuple[str | None, str | None]:
    values = []
    for row in rows:
        for key in ("timestamp", "date", "trade_date", "created_at", "effective_timestamp"):
            if row.get(key):
                values.append(str(row[key]))
                break
    return (min(values), max(values)) if values else (None, None)


@dataclass(frozen=True)
class EvidenceSource:
    logical_name: str
    identifier: str
    classification: str
    authority: str
    schema_version: str
    writer: str
    exists: bool
    size: int
    row_count: int
    last_update: str | None
    content_hash: str | None
    coverage_start: str | None
    coverage_end: str | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PositionEvidence:
    symbol: str
    instrument_id: str | None
    market: str | None
    currency: str | None
    quantity: Decimal
    market_value: Decimal | None
    authoritative_source: str
    strategy_evidence: str | None
    cost_basis_evidence: str | None
    fifo_evidence: str | None
    valuation_evidence: str | None
    confidence: str


@dataclass(frozen=True)
class LotEvidence:
    source_event_id: str
    symbol: str
    remaining_quantity: Decimal
    acquisition_timestamp: str
    source_fill: str
    strategy_id: str | None
    acquisition_fx_source: str | None
    complete: bool
    migration_required: bool
    missing: tuple[str, ...]


@dataclass(frozen=True)
class FxEvidence:
    reference: str
    symbol: str
    currency: str
    acquisition_fx: str | None
    valuation_fx: str | None
    source: str | None
    timestamp: str | None
    quote_convention: str | None
    classification: str


@dataclass(frozen=True)
class NonFillCoverage:
    category: str
    status: str
    evidence_count: int
    source: str | None
    limitation: str


@dataclass(frozen=True)
class EvidenceGap:
    gap_id: str
    category: str
    severity: str
    affected_positions: tuple[str, ...]
    affected_value: Decimal | None
    affected_strategies: tuple[str, ...]
    affected_currencies: tuple[str, ...]
    required_evidence: str
    possible_source: str
    operator_action_required: bool
    migration_required: bool
    blocks_opening_snapshot: bool
    blocks_replay: bool


@dataclass(frozen=True)
class CoverageMetrics:
    position: Decimal
    strategy: Decimal
    fx: Decimal
    fifo: Decimal
    cash: Decimal
    dividend: Decimal
    fee: Decimal
    tax: Decimal
    overall: Decimal


@dataclass(frozen=True)
class OpeningSnapshotEvidencePack:
    schema_version: str
    as_of: datetime
    sources: tuple[EvidenceSource, ...]
    positions: tuple[PositionEvidence, ...]
    lots: tuple[LotEvidence, ...]
    fx: tuple[FxEvidence, ...]
    non_fill: tuple[NonFillCoverage, ...]
    gaps: tuple[EvidenceGap, ...]
    coverage: CoverageMetrics
    unattributed_exposure: Decimal
    unattributed_cash: Decimal
    unattributed_lots: int
    opening_snapshot_readiness: str = READINESS
    replay_readiness: str = READINESS

    @property
    def pack_hash(self) -> str:
        return _hash(asdict(self))

    @property
    def gap_register_hash(self) -> str:
        return _hash(self.gaps)

    def serialize(self) -> str:
        return _serialize({**asdict(self), "pack_hash": self.pack_hash,
                           "gap_register_hash": self.gap_register_hash})


_SOURCES = (
    ("trade_ledger", "trade_ledger_v1.csv", "AUTHORITATIVE", "legacy fill events", "trade ledger writer", ("No strategy identity", "No acquisition FX provenance")),
    ("transaction_history", "trade_transactions_v1.csv", "CORROBORATING", "legacy transaction projection", "transaction report writer", ("Not canonical", "No fees or strategy identity")),
    ("portfolio", "paper_portfolio_v3.csv", "DERIVED", "runtime position projection", "portfolio projection writer", ("Mutable runtime projection",)),
    ("broker_report", "broker_account.csv", "DERIVED", "runtime account projection", "broker reconciliation writer", ("Mutable runtime projection",)),
    ("holdings_report", "holdings_report.csv", "DERIVED", "runtime valuation projection", "mark-to-market writer", ("Prices lack canonical valuation evidence",)),
    ("instrument_registry", "canonical_accounting/instruments.py", "AUTHORITATIVE", "instrument metadata", "source control", ("Registry does not provide historical acquisition FX",)),
    ("currency_registry", "canonical_accounting/currency.py", "AUTHORITATIVE", "currency and unit policy", "source control", ("Policy is not historical FX evidence",)),
    ("strategy_registry", "risk_engine/configuration.py", "PARTIAL", "risk strategy configuration", "source control", ("No authoritative historical fill-to-strategy registry",)),
    ("observation_envelopes", "data/accounting_observations/envelopes.jsonl", "AUTHORITATIVE", "prospective observations", "monitor-only observation producer", ("Prospective coverage only",)),
    ("non_fill_observations", "data/accounting_observations/non_fill.jsonl", "AUTHORITATIVE", "prospective non-fill observations", "explicit internal producer", ("No complete historical backfill",)),
    ("reconciliation_reports", "accounting_reconciliation_report.csv", "DERIVED", "legacy reconciliation output", "reconciliation validator", ("Not opening-snapshot evidence",)),
    ("opening_snapshot_candidates", "data/opening_snapshot_candidates", "UNAVAILABLE", "inactive candidate artifacts", "operator-only candidate process", ("No production candidate is permitted in this task",)),
    ("generated_runtime_files", "paper_30_day_tracker.csv", "DERIVED", "runtime reporting", "scheduled runtime", ("Mutable generated report",)),
)


def _inventory(root: Path) -> tuple[EvidenceSource, ...]:
    result = []
    for name, relative, classification, authority, writer, limitations in _SOURCES:
        path = root / relative
        exists = path.is_file()
        fields, rows = _csv(path) if exists and path.suffix.lower() == ".csv" else ([], [])
        if exists and path.suffix.lower() == ".jsonl":
            rows = [{"line": line} for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        start, end = _coverage(rows)
        schema = "csv:" + _hash(fields)[:12] if fields else ("jsonl" if exists and path.suffix == ".jsonl" else "source" if exists else "absent")
        stat = path.stat() if exists else None
        result.append(EvidenceSource(name, relative, classification, authority, schema, writer, exists,
                                     stat.st_size if stat else 0, len(rows),
                                     datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat() if stat else None,
                                     _file_hash(path) if exists else None, start, end, limitations))
    return tuple(sorted(result, key=lambda item: item.logical_name))


def _fifo(rows: list[dict[str, str]]) -> tuple[LotEvidence, ...]:
    lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    seen: dict[str, str] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise EvidencePackError("ledger event is missing stable identity")
        fingerprint = _hash(row)
        if event_id in seen:
            if seen[event_id] != fingerprint:
                raise EvidencePackError(f"conflicting duplicate ledger event: {event_id}")
            continue
        seen[event_id] = fingerprint
        symbol = str(row.get("ticker") or "").strip().upper()
        quantity = _decimal(row.get("shares"), "shares")
        action = str(row.get("action") or "").upper()
        if action == "BUY":
            lots[symbol].append({"id": event_id, "remaining": quantity, "timestamp": str(row.get("timestamp") or ""), "currency": str(row.get("currency") or "")})
        elif action == "SELL":
            remaining = quantity
            while remaining > 0 and lots[symbol]:
                lot = lots[symbol][0]
                matched = min(remaining, lot["remaining"])
                lot["remaining"] -= matched
                remaining -= matched
                if lot["remaining"] == 0:
                    lots[symbol].popleft()
            if remaining > 0:
                raise EvidencePackError(f"orphan sell prevents proven FIFO evidence: {event_id}")
        else:
            raise EvidencePackError(f"unknown ledger action: {action}")
    evidence = []
    for symbol in sorted(lots):
        for lot in lots[symbol]:
            missing = ("strategy_id", "acquisition_fx_source", "acquisition_fx_timestamp", "quote_convention")
            evidence.append(LotEvidence(lot["id"], symbol, lot["remaining"], lot["timestamp"], "trade_ledger_v1.csv",
                                        None, None, False, True, missing))
    return tuple(evidence)


def _gap(category: str, severity: str, symbols: tuple[str, ...], value: Decimal | None,
         currencies: tuple[str, ...], evidence: str, source: str, migration: bool,
         opening: bool = True, replay: bool = True) -> EvidenceGap:
    material = {"category": category, "symbols": symbols, "evidence": evidence, "source": source}
    return EvidenceGap("gap-" + _hash(material)[:20], category, severity, symbols, value, (), currencies,
                       evidence, source, True, migration, opening, replay)


def _percent(proven: int, total: int) -> Decimal:
    return Decimal("100") if total == 0 else (Decimal(proven) * Decimal("100") / Decimal(total)).quantize(Decimal("0.01"))


def build_evidence_pack(root: str | Path = ".", *, as_of: datetime) -> OpeningSnapshotEvidencePack:
    """Inspect repository evidence without creating or changing any artifact."""
    if as_of.tzinfo is None:
        raise EvidencePackError("as_of must be timezone-aware")
    root = Path(root).resolve()
    sources = _inventory(root)
    _, ledger = _csv(root / "trade_ledger_v1.csv")
    _, portfolio_rows = _csv(root / "paper_portfolio_v3.csv")
    _, holdings_rows = _csv(root / "holdings_report.csv")
    _, broker_rows = _csv(root / "broker_account.csv")
    lots = _fifo(ledger)
    holdings = {str(row.get("ticker") or "").upper(): row for row in holdings_rows}
    positions = []
    fx_rows = []
    for row in sorted(portfolio_rows, key=lambda item: str(item.get("ticker") or "")):
        symbol = str(row.get("ticker") or "").upper()
        quantity = _decimal(row.get("shares"), "portfolio shares")
        policy = INSTRUMENT_REGISTRY.get(symbol)
        holding = holdings.get(symbol, {})
        value = _decimal(holding["market_value"], "market value") if holding.get("market_value") else None
        matching_lots = [item for item in lots if item.symbol == symbol]
        lot_quantity = sum((item.remaining_quantity for item in matching_lots), Decimal("0"))
        quantity_proven = bool(matching_lots) and abs(lot_quantity - quantity) <= Decimal("0.00000001")
        confidence = "PARTIAL" if policy and quantity_proven else "UNPROVEN"
        positions.append(PositionEvidence(symbol, f"instrument:{symbol}" if policy else None,
                                          policy.exchange if policy else None, policy.instrument_currency if policy else None,
                                          quantity, value, "trade_ledger_v1.csv",
                                          None, "ledger BUY fills; acquisition FX incomplete" if matching_lots else None,
                                          "FIFO sequence reconstructable; lots not created" if quantity_proven else None,
                                          "holdings_report.csv derived valuation" if holding else None, confidence))
        currency = policy.instrument_currency if policy else str(row.get("currency") or "UNKNOWN")
        classification = "PARTIAL" if currency == "GBP" else "MISSING"
        fx_rows.append(FxEvidence("position:" + symbol, symbol, currency,
                                 "GBP identity" if currency == "GBP" else None,
                                 "GBP identity" if currency == "GBP" else None,
                                 "currency policy only" if currency == "GBP" else None, None,
                                 "GBP_PER_GBP" if currency == "GBP" else None, classification))
    positions_t = tuple(positions)
    fx_t = tuple(fx_rows)
    symbols = tuple(item.symbol for item in positions_t)
    currencies = tuple(sorted({item.currency for item in positions_t if item.currency}))
    exposure = sum((item.market_value or Decimal("0") for item in positions_t), Decimal("0"))
    cash = _decimal(broker_rows[0].get("cash", "0"), "broker cash") if broker_rows else Decimal("0")
    non_fill = tuple(NonFillCoverage(category, "MISSING", 0, None, limitation) for category, limitation in (
        ("DEPOSIT", "Starting cash and subsequent deposits lack authoritative event history"),
        ("WITHDRAWAL", "No authoritative withdrawal event history"),
        ("DIVIDEND", "No authoritative entitlement and payment history"),
        ("FEE", "Fill fee columns do not prove standalone fee completeness"),
        ("TAX_WITHHOLDING", "No authoritative tax and withholding history"),
        ("FX_ADJUSTMENT", "No authoritative conversion or remeasurement history"),
        ("CORPORATE_ACTION", "No authoritative corporate-action event history"),
    ))
    gaps = [
        _gap("STRATEGY_ATTRIBUTION", "CRITICAL", symbols, exposure, currencies,
             "authoritative strategy identity for every position and source fill", "proposal/decision records or operator-approved allocation", True),
        _gap("ACQUISITION_FX", "CRITICAL", symbols, exposure, currencies,
             "timestamped acquisition FX rate, source, and quote convention for every lot", "broker contract notes or verified FX archive", True),
        _gap("CASH_PROVENANCE", "CRITICAL", (), cash, ("GBP",),
             "complete external cash-flow history reconciling opening and current cash", "broker statements and bank transfer records", True),
        _gap("NON_FILL_HISTORY", "CRITICAL", symbols, exposure, currencies,
             "complete dividend, standalone fee, tax, FX adjustment, and corporate-action history", "authoritative broker statements", True),
    ]
    if any(item.confidence == "UNPROVEN" for item in positions_t):
        gaps.append(_gap("POSITION_RECONCILIATION", "CRITICAL", tuple(item.symbol for item in positions_t if item.confidence == "UNPROVEN"), exposure,
                         currencies, "ledger FIFO quantities reconciled to current positions", "broker position statement", True))
    gaps_t = tuple(sorted(gaps, key=lambda item: item.gap_id))
    position_pct = _percent(sum(item.confidence == "PROVEN" for item in positions_t), len(positions_t))
    strategy_pct = Decimal("0") if positions_t else Decimal("100")
    fx_pct = _percent(sum(item.classification == "COMPLETE" for item in fx_t), len(fx_t))
    fifo_pct = _percent(sum(item.complete for item in lots), len(lots))
    metrics_values = (position_pct, strategy_pct, fx_pct, fifo_pct, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    coverage = CoverageMetrics(*metrics_values, (sum(metrics_values) / Decimal(len(metrics_values))).quantize(Decimal("0.01")))
    return OpeningSnapshotEvidencePack(SCHEMA_VERSION, as_of.astimezone(timezone.utc), sources, positions_t, lots, fx_t,
                                       non_fill, gaps_t, coverage, exposure, cash, len(lots))
