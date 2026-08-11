"""Explicit research evidence modes; never connected to legacy signals."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from data.point_in_time import FundamentalObservation


MODES = {"technical_only_historical_v1", "point_in_time_fundamental_v1"}
OPERATORS = {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal", "equal"}


@dataclass(frozen=True, slots=True)
class FieldRequirement:
    field_name: str
    operator: str
    threshold: Decimal

    def __post_init__(self):
        if not self.field_name or self.operator not in OPERATORS or not isinstance(self.threshold, Decimal) or not self.threshold.is_finite(): raise ValueError("invalid field requirement")


@dataclass(frozen=True, slots=True)
class EvidenceModeDecision:
    schema_version: int
    mode: str
    instrument_id: str
    decision_timestamp: datetime
    information_cutoff: datetime
    selected_observation_ids: tuple[str, ...]
    field_outcomes: tuple[tuple[str, str], ...]
    status: str
    reason_codes: tuple[str, ...]
    result_classification: str = "exploratory_unverified"
    warnings: tuple[str, ...] = ()

    def canonical_sha256(self):
        value = {"schema_version": self.schema_version, "mode": self.mode, "instrument_id": self.instrument_id, "decision_timestamp": self.decision_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "information_cutoff": self.information_cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "selected_observation_ids": list(self.selected_observation_ids), "field_outcomes": [list(x) for x in self.field_outcomes], "status": self.status, "reason_codes": list(self.reason_codes), "result_classification": self.result_classification, "warnings": list(self.warnings)}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value): raise ValueError(f"{field} must be UTC")


def _compare(value, requirement):
    if not isinstance(value, Decimal): return False
    return {"greater_than": value > requirement.threshold, "greater_than_or_equal": value >= requirement.threshold, "less_than": value < requirement.threshold, "less_than_or_equal": value <= requirement.threshold, "equal": value == requirement.threshold}[requirement.operator]


def select_evidence(*, mode: str, instrument_id: str, decision_timestamp: datetime, information_cutoff: datetime, observations: tuple[FundamentalObservation, ...] = (), requirements: tuple[FieldRequirement, ...] = ()) -> EvidenceModeDecision:
    if mode not in MODES: raise ValueError("unknown or missing evidence mode")
    _utc(decision_timestamp, "decision_timestamp"); _utc(information_cutoff, "information_cutoff")
    if decision_timestamp < information_cutoff: raise ValueError("decision timestamp cannot precede information cutoff")
    if mode == "technical_only_historical_v1":
        return EvidenceModeDecision(1, mode, instrument_id, decision_timestamp, information_cutoff, (), (), "eligible", (), warnings=("technical-only historical research", "exploratory and unverified"))
    selected, outcomes, reasons = [], [], []
    for requirement in requirements:
        candidates = [o for o in observations if o.instrument_id == instrument_id and o.field_name == requirement.field_name and o.eligibility(information_cutoff).eligible]
        if not candidates:
            outcomes.append((requirement.field_name, "unavailable")); reasons.append(f"missing:{requirement.field_name}"); continue
        chosen = sorted(candidates, key=lambda o: (o.available_at, o.source_revision_id or "", o.source_record_id))[-1]
        selected.append(chosen.source_record_id)
        passed = _compare(chosen.value, requirement)
        outcomes.append((requirement.field_name, "eligible" if passed else "ineligible"))
        if not passed: reasons.append(f"predicate_failed:{requirement.field_name}")
    status = "eligible" if outcomes and not reasons else ("unavailable" if any(x[1] == "unavailable" for x in outcomes) else "ineligible")
    return EvidenceModeDecision(1, mode, instrument_id, decision_timestamp, information_cutoff, tuple(selected), tuple(outcomes), status, tuple(reasons), warnings=("prospective point-in-time evidence only", "exploratory and unverified"))
