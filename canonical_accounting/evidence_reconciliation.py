"""Deterministic, read-only reconciliation of explicitly acquired evidence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from canonical_accounting.evidence_pack import OpeningSnapshotEvidencePack
from canonical_accounting.frozen_evidence import (
    RECORD_TYPES, CollectedEvidence, EvidenceDocumentRequest,
    EvidenceItem, FrozenEvidenceError, NormalizedEvidenceRecord, collect_evidence,
)

MATCH_STATES = frozenset({"EXACT_MATCH", "PARTIAL_MATCH", "CONFLICT", "MISSING", "UNKNOWN"})
GAP_STATES = frozenset({"RESOLVED", "CONFLICT", "OPEN"})
REQUIRED_RECORD_FIELDS = {
    "TRADE": {"effective_timestamp", "currency", "quantity", "price", "symbol"},
    "CASH_MOVEMENT": {"effective_timestamp", "currency", "amount"},
    "DIVIDEND": {"effective_timestamp", "currency", "amount"},
    "FEE": {"effective_timestamp", "currency", "amount"},
    "TAX": {"effective_timestamp", "currency", "amount"},
    "FX_CONVERSION": {"effective_timestamp", "currency", "amount"},
    "CORPORATE_ACTION": {"effective_timestamp"},
    "ADJUSTMENT": {"effective_timestamp", "currency", "amount"},
}
SOURCE_ADAPTERS = {
    "BROKER_TRADE_STATEMENT": "BROKER_STATEMENT",
    "BROKER_ACCOUNT_STATEMENT": "BROKER_STATEMENT",
    "CASH_STATEMENT": "CASH_STATEMENT",
    "DIVIDEND_STATEMENT": "DIVIDEND_STATEMENT",
    "FX_CONFIRMATION": "FX_RECORD",
    "CORPORATE_ACTION_NOTICE": "CORPORATE_ACTION",
    "TAX_DOCUMENT": "TAX_STATEMENT",
    "MANUAL_OPERATOR_EVIDENCE": "MANUAL_OPERATOR_DOCUMENT",
}


def acquire_authoritative_evidence(path, request: AuthoritativeImportRequest, *, gap_ids) -> CollectedEvidence:
    """Import one operator-selected document through its typed source adapter."""
    return collect_evidence(path, request.to_document_request(), gap_ids=gap_ids)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, tuple): return [_json(item) for item in value]
    if isinstance(value, dict): return {str(key): _json(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"): return _json(asdict(value))
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FrozenEvidenceError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class AuthoritativeImportRequest:
    adapter_type: str
    source: str
    identifier: str
    statement_start: datetime
    statement_end: datetime
    issue_date: datetime
    import_timestamp: datetime
    confidence: str
    verification_status: str
    linked_gap_ids: tuple[str, ...]
    associated_positions: tuple[str, ...] = ()
    associated_cash_flows: tuple[str, ...] = ()
    associated_lots: tuple[str, ...] = ()
    normalized_records: tuple[NormalizedEvidenceRecord, ...] = ()

    def to_document_request(self) -> EvidenceDocumentRequest:
        if self.adapter_type not in SOURCE_ADAPTERS:
            raise FrozenEvidenceError("unsupported authoritative source adapter")
        start = _aware(self.statement_start, "statement_start")
        end = _aware(self.statement_end, "statement_end")
        issue = _aware(self.issue_date, "issue_date")
        imported = _aware(self.import_timestamp, "import_timestamp")
        if start > end or issue < end or imported < issue:
            raise FrozenEvidenceError("statement, issue, and import chronology is invalid")
        return EvidenceDocumentRequest(
            source=self.source, identifier=self.identifier, source_timestamp=issue,
            document_type=SOURCE_ADAPTERS[self.adapter_type], coverage_start=start,
            coverage_end=end, confidence=self.confidence,
            verification_status=self.verification_status, linked_gap_ids=self.linked_gap_ids,
            associated_positions=self.associated_positions,
            associated_cash_flows=self.associated_cash_flows,
            associated_lots=self.associated_lots, normalized_records=self.normalized_records,
            issue_date=issue, import_timestamp=imported,
        )


@dataclass(frozen=True)
class ReconciliationResult:
    reconciliation_id: str
    record_type: str
    record_id: str
    state: str
    evidence_ids: tuple[str, ...]
    sources: tuple[str, ...]
    matched_fields: tuple[str, ...]
    conflicting_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    associated_positions: tuple[str, ...]
    associated_lots: tuple[str, ...]
    associated_cash_flows: tuple[str, ...]
    confidence: str
    explanation: str


@dataclass(frozen=True)
class GapResolution:
    gap_id: str
    state: str
    evidence_ids: tuple[str, ...]
    reconciliation_ids: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class ReconciliationReport:
    schema_version: str
    created_at: datetime
    evidence_cutoff: datetime
    results: tuple[ReconciliationResult, ...]
    gaps: tuple[GapResolution, ...]
    missing_documents: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    exact_matches: int
    partial_matches: int
    conflicts: int
    missing: int
    unknown: int

    @property
    def report_hash(self) -> str: return _hash(self)


def _record_signature(record: NormalizedEvidenceRecord) -> tuple:
    return (record.record_type, record.effective_timestamp.astimezone(timezone.utc).isoformat(),
            record.currency, record.amount, record.quantity, record.price, tuple(sorted(record.fields)))


def _field_map(record: NormalizedEvidenceRecord) -> dict[str, str | None]:
    return {"effective_timestamp": record.effective_timestamp.astimezone(timezone.utc).isoformat(),
            "currency": record.currency, "amount": record.amount, "quantity": record.quantity,
            "price": record.price, **dict(record.fields)}


def reconcile_evidence(evidence: OpeningSnapshotEvidencePack, collection: tuple[CollectedEvidence, ...], *, created_at: datetime, evidence_cutoff: datetime) -> ReconciliationReport:
    """Compare only supplied, verified facts. No record or relationship is inferred."""
    created_at = _aware(created_at, "created_at"); cutoff = _aware(evidence_cutoff, "evidence_cutoff")
    groups: dict[tuple[str, str], list[tuple[EvidenceItem, NormalizedEvidenceRecord]]] = {}
    for entry in collection:
        if entry.item.verification_status == "REJECTED": continue
        for record in entry.item.normalized_records:
            if record.record_type not in RECORD_TYPES: raise FrozenEvidenceError("unknown normalized record type")
            groups.setdefault((record.record_type, record.record_id), []).append((entry.item, record))
    results = []
    known_positions = {position.symbol for position in evidence.positions}
    known_lots = {lot.source_event_id for lot in evidence.lots}
    for (record_type, record_id), rows in sorted(groups.items()):
        items = tuple(row[0] for row in rows); records = tuple(row[1] for row in rows)
        sources = tuple(sorted({item.source for item in items})); signatures = {_record_signature(record) for record in records}
        maps = [_field_map(record) for record in records]; fields = sorted(set().union(*(row.keys() for row in maps)))
        conflicting = tuple(field for field in fields if len({row.get(field) for row in maps}) > 1)
        matched = tuple(field for field in fields if not conflicting and all(row.get(field) is not None for row in maps))
        required = REQUIRED_RECORD_FIELDS[record_type]
        relationship_unknowns = (
            ({"associated_position"} if any(set(item.associated_positions) - known_positions for item in items) else set()) |
            ({"associated_lot"} if any(set(item.associated_lots) - known_lots for item in items) else set())
        )
        unknown = tuple(sorted(set().union(*(set(record.unknown_fields) for record in records)) |
                               {field for field in required if any(row.get(field) is None for row in maps)} |
                               relationship_unknowns))
        verified = all(item.verification_status == "VERIFIED" for item in items)
        if len(sources) >= 2 and len(signatures) == 1 and verified and not unknown:
            state, explanation = "EXACT_MATCH", "Independent verified sources agree exactly"
        elif conflicting:
            state, explanation = "CONFLICT", "Independent sources disagree on authoritative fields"
        elif unknown:
            state, explanation = "UNKNOWN", "Required or source-declared fields remain unknown"
        else:
            state, explanation = "PARTIAL_MATCH", "Only one independent source or unverified evidence is available"
        confidence = "HIGH" if state == "EXACT_MATCH" else "LOW" if state == "CONFLICT" else "UNKNOWN" if state == "UNKNOWN" else "MEDIUM"
        material = (record_type, record_id, state, tuple(item.identifier for item in items), sources, conflicting, unknown)
        results.append(ReconciliationResult("recon-" + _hash(material)[:20], record_type, record_id, state,
            tuple(sorted({item.identifier for item in items})), sources, matched, conflicting, unknown,
            tuple(sorted({value for item in items for value in item.associated_positions})),
            tuple(sorted({value for item in items for value in item.associated_lots})),
            tuple(sorted({value for item in items for value in item.associated_cash_flows})), confidence, explanation))
    gap_rows = []
    for gap in evidence.gaps:
        linked_items = tuple(entry.item for entry in collection if gap.gap_id in entry.item.linked_gap_ids)
        linked_ids = {item.identifier for item in linked_items}
        linked_results = tuple(result for result in results if linked_ids & set(result.evidence_ids))
        if any(result.state == "CONFLICT" for result in linked_results):
            state, explanation = "CONFLICT", "Linked authoritative evidence conflicts"
        elif (linked_results and {identifier for result in linked_results for identifier in result.evidence_ids} == linked_ids
              and all(result.state == "EXACT_MATCH" for result in linked_results)
              and all(item.verification_status == "VERIFIED" for item in linked_items)):
            state, explanation = "RESOLVED", "All linked facts agree across independent verified sources"
        else:
            state, explanation = "OPEN", "Evidence is missing, partial, unverified, or unknown"
        gap_rows.append(GapResolution(gap.gap_id, state, tuple(sorted(linked_ids)),
            tuple(result.reconciliation_id for result in linked_results), explanation))
    expected = {"TRADE", "CASH_MOVEMENT", "DIVIDEND", "FEE", "TAX", "FX_CONVERSION", "CORPORATE_ACTION"}
    present = {result.record_type for result in results}
    missing_documents = tuple(sorted(expected - present))
    unknown_fields = tuple(sorted({field for result in results for field in result.unknown_fields}))
    counts = {state: sum(result.state == state for result in results) for state in MATCH_STATES}
    counts["MISSING"] = len(missing_documents)
    return ReconciliationReport("1.0", created_at, cutoff, tuple(results), tuple(gap_rows), missing_documents,
        unknown_fields, counts["EXACT_MATCH"], counts["PARTIAL_MATCH"], counts["CONFLICT"], counts["MISSING"], counts["UNKNOWN"])


def reconstruct_evidenced_lot_links(report: ReconciliationReport) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Return explicit trade-to-lot/cash links only; absent associations stay absent."""
    return tuple((result.record_id, result.associated_lots, result.associated_cash_flows)
                 for result in report.results if result.record_type == "TRADE" and result.state == "EXACT_MATCH"
                 and result.associated_lots and result.associated_cash_flows)


def reconcile_cash_evidence(report: ReconciliationReport) -> tuple[ReconciliationResult, ...]:
    cash_types = {"CASH_MOVEMENT", "DIVIDEND", "FEE", "TAX", "FX_CONVERSION", "CORPORATE_ACTION"}
    return tuple(result for result in report.results if result.record_type in cash_types)
