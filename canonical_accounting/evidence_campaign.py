"""Read-only campaign views over immutable frozen opening evidence.

This module organises evidence already collected.  It deliberately exposes no
accounting, candidate, generation, pointer, migration-lot, or estimation API.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from canonical_accounting.frozen_evidence import FrozenEvidencePack

ITEM_STATES = frozenset({"PRESENT", "MISSING", "PARTIAL", "UNKNOWN"})
WORK_STATES = frozenset({"COMPLETE", "PARTIAL", "MISSING", "UNKNOWN"})
CAMPAIGN_STATES = frozenset({"OPEN", "CLOSED"})
READINESS_STATES = frozenset({"READY", "NOT_READY", "BLOCKED"})


class EvidenceCampaignError(ValueError):
    pass


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
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


@dataclass(frozen=True)
class Requirement:
    key: str
    label: str
    state: str
    reason: str
    critical: bool


@dataclass(frozen=True)
class PositionChecklist:
    symbol: str
    strategy_attribution: str
    fifo: str
    acquisition_fx: str
    cash_linkage: str
    corporate_actions: str
    evidence_confidence: str
    status: str


@dataclass(frozen=True)
class CashChecklist:
    category: str
    state: str
    reason: str


@dataclass(frozen=True)
class PriorityItem:
    rank: int
    key: str
    title: str
    reason: str
    severity: str
    state: str


@dataclass(frozen=True)
class ReadinessAssessment:
    state: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TimelinePoint:
    timestamp: datetime
    pack_id: str
    completion: Decimal


@dataclass(frozen=True)
class EvidenceCampaign:
    campaign_id: str
    title: str
    cutoff_date: date
    created: datetime
    status: str
    coverage: Decimal
    priority: str
    owner: str
    source_pack_id: str
    source_bundle_hash: str
    requirements: tuple[Requirement, ...]
    positions: tuple[PositionChecklist, ...]
    cash: tuple[CashChecklist, ...]
    priorities: tuple[PriorityItem, ...]
    readiness: ReadinessAssessment
    recently_imported: tuple[str, ...]
    outstanding_conflicts: tuple[str, ...]
    resolved_this_campaign: tuple[str, ...]
    timeline: tuple[TimelinePoint, ...]
    remaining_unknowns: tuple[str, ...]
    estimated_remaining_work: int
    closed_at: datetime | None = None

    @property
    def bundle_hash(self) -> str:
        return _hash(asdict(self))


_DOCUMENT_REQUIREMENTS = (
    ("broker_trades", "Broker trades", "TRADE", True),
    ("holdings", "Holdings", None, True),
    ("cash_statements", "Cash statements", "CASH_MOVEMENT", True),
    ("fx_confirmations", "FX confirmations", "FX_CONVERSION", True),
    ("corporate_actions", "Corporate actions", "CORPORATE_ACTION", True),
    ("dividend_statements", "Dividend statements", "DIVIDEND", False),
    ("tax_records", "Tax records", "TAX", False),
)

_CASH_TYPES = (
    ("Deposits", "CASH_MOVEMENT"), ("Withdrawals", "CASH_MOVEMENT"),
    ("Fees", "FEE"), ("Taxes", "TAX"), ("Dividends", "DIVIDEND"),
    ("Interest", "ADJUSTMENT"), ("Transfers", "CASH_MOVEMENT"),
)


def _result_rows(pack: FrozenEvidencePack) -> tuple[dict, ...]:
    report = pack.reconciliation_report or {}
    return tuple(report.get("results") or ())


def _record_state(pack: FrozenEvidencePack, record_type: str) -> tuple[str, str]:
    rows = [row for row in _result_rows(pack) if row.get("record_type") == record_type]
    if not rows:
        return "MISSING", f"No reconciled {record_type.lower().replace('_', ' ')} evidence"
    states = {str(row.get("state", "UNKNOWN")) for row in rows}
    if "CONFLICT" in states:
        return "PARTIAL", "Conflicting evidence remains outstanding"
    if states == {"EXACT_MATCH"}:
        return "PRESENT", "All recorded facts agree across verified sources"
    if "UNKNOWN" in states:
        return "UNKNOWN", "Required fields remain explicitly unknown"
    return "PARTIAL", "Evidence is incomplete, unverified, or supported by one source"


def _work_state(state: str) -> str:
    return {"PRESENT": "COMPLETE", "PARTIAL": "PARTIAL", "MISSING": "MISSING", "UNKNOWN": "UNKNOWN"}[state]


def _requirements(pack: FrozenEvidencePack) -> tuple[Requirement, ...]:
    values = []
    for key, label, record_type, critical in _DOCUMENT_REQUIREMENTS:
        if key == "holdings":
            positions = pack.source_evidence.positions
            if not positions:
                state, reason = "UNKNOWN", "No open-position population is available"
            elif all(item.confidence == "PROVEN" for item in positions):
                state, reason = "PRESENT", "Every open holding is proven"
            elif any(item.authoritative_source for item in positions):
                state, reason = "PARTIAL", "Holdings exist but one or more positions are not proven"
            else:
                state, reason = "MISSING", "No authoritative holdings evidence"
        else:
            state, reason = _record_state(pack, record_type)
        values.append(Requirement(key, label, state, reason, critical))
    return tuple(values)


def _positions(pack: FrozenEvidencePack) -> tuple[PositionChecklist, ...]:
    results = _result_rows(pack)
    output = []
    for position in pack.source_evidence.positions:
        symbol = position.symbol
        linked = [row for row in results if symbol in row.get("associated_positions", ())]
        trade_rows = [row for row in linked if row.get("record_type") == "TRADE"]
        exact_trade_ids = {identifier for row in trade_rows if row.get("state") == "EXACT_MATCH"
                           for identifier in row.get("evidence_ids", ())}
        strategy_items = [item for item in pack.evidence_inventory
                          if item.identifier in exact_trade_ids and item.verification_status == "VERIFIED"
                          and symbol in item.associated_positions]
        strategy = "COMPLETE" if strategy_items and all(
            any(dict(record.fields).get("strategy_id") for record in item.normalized_records
                if record.record_type == "TRADE") for item in strategy_items
        ) else "UNKNOWN"
        lots = [lot for lot in pack.source_evidence.lots if lot.symbol == symbol]
        fifo = "COMPLETE" if lots and all(lot.complete for lot in lots) else "PARTIAL" if lots else "UNKNOWN"
        fx_state, _ = _record_state(pack, "FX_CONVERSION")
        cash_rows = [row for row in linked if row.get("associated_cash_flows")]
        cash = "COMPLETE" if cash_rows and all(row.get("state") == "EXACT_MATCH" for row in cash_rows) else "UNKNOWN"
        corporate_state, _ = _record_state(pack, "CORPORATE_ACTION")
        fields = (strategy, fifo, _work_state(fx_state), cash, _work_state(corporate_state))
        status = "COMPLETE" if all(value == "COMPLETE" for value in fields) else "MISSING" if "MISSING" in fields else "UNKNOWN" if "UNKNOWN" in fields else "PARTIAL"
        confidence = "HIGH" if status == "COMPLETE" else "LOW" if status == "MISSING" else "UNKNOWN" if "UNKNOWN" in fields else "MEDIUM"
        output.append(PositionChecklist(symbol, strategy, fifo, _work_state(fx_state), cash,
                                        _work_state(corporate_state), confidence, status))
    return tuple(sorted(output, key=lambda item: item.symbol))


def _cash(pack: FrozenEvidencePack) -> tuple[CashChecklist, ...]:
    values = []
    for label, record_type in _CASH_TYPES:
        state, reason = _record_state(pack, record_type)
        values.append(CashChecklist(label, _work_state(state), reason))
    return tuple(values)


def _priorities(requirements, positions, cash, conflicts) -> tuple[PriorityItem, ...]:
    raw = []
    for position in positions:
        if position.status != "COMPLETE":
            raw.append((0, f"position:{position.symbol}", f"Resolve {position.symbol} position",
                        "Position evidence is not complete", "CRITICAL", position.status))
        if position.acquisition_fx != "COMPLETE":
            raw.append((1, f"fx:{position.symbol}", f"Acquire {position.symbol} acquisition FX",
                        "Timestamped acquisition FX provenance is incomplete", "CRITICAL", position.acquisition_fx))
    labels = {"cash_statements": "Broker cash history", "dividend_statements": "Historical dividends",
              "tax_records": "Tax evidence", "corporate_actions": "Corporate actions"}
    for item in requirements:
        if item.state != "PRESENT" and item.key in labels:
            raw.append((2 if item.critical else 3, item.key, labels[item.key], item.reason,
                        "CRITICAL" if item.critical else "HIGH", _work_state(item.state)))
    for identifier in conflicts:
        raw.append((-1, f"conflict:{identifier}", f"Resolve conflict {identifier}",
                    "Authoritative evidence disagrees", "CRITICAL", "PARTIAL"))
    raw.sort(key=lambda item: (item[0], item[2], item[1]))
    return tuple(PriorityItem(index, *item[1:]) for index, item in enumerate(raw, 1))


def _reconciliation(pack):
    report = pack.reconciliation_report or {}
    gaps = tuple(report.get("gaps") or ())
    conflicts = tuple(sorted(str(row.get("reconciliation_id") or row.get("record_id") or "unknown")
                             for row in report.get("results", ()) if row.get("state") == "CONFLICT"))
    resolved = tuple(sorted(str(row.get("gap_id")) for row in gaps if row.get("state") == "RESOLVED"))
    return conflicts, resolved


def _readiness(requirements, positions, cash, conflicts) -> ReadinessAssessment:
    reasons = []
    if conflicts:
        reasons.append(f"{len(conflicts)} outstanding evidence conflict(s)")
    reasons.extend(f"{item.label}: {item.reason}" for item in requirements if item.critical and item.state != "PRESENT")
    reasons.extend(f"{item.symbol} position checklist is {item.status.lower()}" for item in positions if item.status != "COMPLETE")
    critical_cash = [item for item in cash if item.category in {"Deposits", "Withdrawals", "Transfers"} and item.state != "COMPLETE"]
    reasons.extend(f"{item.category}: {item.reason}" for item in critical_cash)
    if conflicts:
        state = "BLOCKED"
    elif reasons:
        state = "NOT_READY"
    else:
        state = "READY"
    return ReadinessAssessment(state, tuple(dict.fromkeys(reasons)))


def build_campaign(pack: FrozenEvidencePack, *, title: str, owner: str, created: datetime,
                   priority: str = "HIGH", history: tuple[FrozenEvidencePack, ...] = ()) -> EvidenceCampaign:
    """Build a deterministic campaign view; no source artifact is modified."""
    if not title.strip() or not owner.strip() or created.tzinfo is None:
        raise EvidenceCampaignError("title, owner, and timezone-aware creation time are required")
    created = created.astimezone(timezone.utc)
    requirements = _requirements(pack)
    positions = _positions(pack)
    cash = _cash(pack)
    conflicts, resolved = _reconciliation(pack)
    readiness = _readiness(requirements, positions, cash, conflicts)
    priorities = _priorities(requirements, positions, cash, conflicts)
    ordered_history = tuple(history) if history else (pack,)
    timeline = tuple(TimelinePoint(item.creation_timestamp, item.pack_id, item.coverage.overall)
                     for item in ordered_history)
    unknowns = tuple(sorted({f"{item.symbol}: {field.replace('_', ' ')}" for item in positions
                             for field in ("strategy_attribution", "fifo", "acquisition_fx", "cash_linkage", "corporate_actions")
                             if getattr(item, field) == "UNKNOWN"} |
                            {f"{item.category}: evidence unknown" for item in cash if item.state == "UNKNOWN"}))
    recent = tuple(item.identifier for item in sorted(pack.evidence_inventory,
                   key=lambda value: (value.import_timestamp, value.identifier), reverse=True)[:10])
    material = {"title": title.strip(), "owner": owner.strip(), "cutoff": pack.evidence_cutoff_timestamp.date(),
                "created": created, "source_pack_id": pack.pack_id}
    return EvidenceCampaign("campaign-" + _hash(material)[:20], title.strip(), pack.evidence_cutoff_timestamp.date(),
        created, "OPEN", pack.coverage.overall, priority.upper(), owner.strip(), pack.pack_id, pack.bundle_hash,
        requirements, positions, cash, priorities, readiness, recent, conflicts, resolved, timeline, unknowns,
        len(priorities))


def close_campaign(campaign: EvidenceCampaign, *, closed_at: datetime) -> EvidenceCampaign:
    if campaign.status == "CLOSED":
        raise EvidenceCampaignError("closed campaigns are immutable")
    if closed_at.tzinfo is None or closed_at.astimezone(timezone.utc) < campaign.created:
        raise EvidenceCampaignError("valid timezone-aware closed_at is required")
    return replace(campaign, status="CLOSED", closed_at=closed_at.astimezone(timezone.utc))


def campaign_reports(campaign: EvidenceCampaign) -> dict[str, Any]:
    """Return all requested reports as deterministic, hash-bound JSON values."""
    summary = {"campaign_id": campaign.campaign_id, "title": campaign.title, "cutoff_date": campaign.cutoff_date,
               "status": campaign.status, "owner": campaign.owner, "priority": campaign.priority,
               "completion": campaign.coverage, "readiness": campaign.readiness}
    return {
        "campaign_report": summary,
        "coverage_report": {"overall": campaign.coverage, "timeline": campaign.timeline},
        "evidence_inventory": campaign.requirements,
        "outstanding_requirements": campaign.priorities,
        "resolved_evidence": campaign.resolved_this_campaign,
        "remaining_unknowns": campaign.remaining_unknowns,
        "critical_blockers": tuple(item for item in campaign.priorities if item.severity == "CRITICAL"),
        "bundle_hash": campaign.bundle_hash,
    }


def export_campaign_bundle(campaign: EvidenceCampaign) -> str:
    payload = campaign_reports(campaign)
    payload["export_hash"] = _hash(payload)
    return _serialize(payload)
