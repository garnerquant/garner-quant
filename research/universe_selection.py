"""Point-in-time universe selection for validated research only."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json

from data.point_in_time import CorporateAction, CorporateActionType, UniverseMembership
from research.validated_dataset import ValidatedResearchDataset


@dataclass(frozen=True, slots=True)
class UniverseSelectionDecision:
    schema_version: int
    universe_id: str
    universe_version: str
    decision_date: date
    information_cutoff: datetime
    eligible_instrument_ids: tuple[str, ...]
    excluded_instrument_reasons: tuple[tuple[str, str], ...]
    membership_evidence_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def canonical_bytes(self):
        payload = {"contract_type": "universe_selection_decision", "schema_version": 1, "payload": {"schema_version": self.schema_version, "universe_id": self.universe_id, "universe_version": self.universe_version, "decision_date": self.decision_date.isoformat(), "information_cutoff": self.information_cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "eligible_instrument_ids": list(self.eligible_instrument_ids), "excluded_instrument_reasons": [list(x) for x in self.excluded_instrument_reasons], "membership_evidence_ids": list(self.membership_evidence_ids), "warnings": list(self.warnings)}}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def canonical_sha256(self): return hashlib.sha256(self.canonical_bytes()).hexdigest()


def select_research_universe(*, dataset: ValidatedResearchDataset, universe_id: str, universe_version: str, decision_date: date, information_cutoff: datetime, memberships: tuple[UniverseMembership, ...], metadata_records: dict | None = None, corporate_actions: tuple[CorporateAction, ...] = ()) -> UniverseSelectionDecision:
    if not universe_id or not universe_version: raise ValueError("universe ID and version are required")
    if information_cutoff.tzinfo is None or information_cutoff.utcoffset() != timezone.utc.utcoffset(information_cutoff): raise ValueError("information_cutoff must be UTC")
    instruments = sorted({bar.instrument_id for bar in dataset.bars})
    eligible, excluded, evidence = [], [], []
    for instrument in instruments:
        records = [m for m in memberships if m.instrument_id == instrument and m.universe_id == universe_id and m.universe_version == universe_version and m.available_at <= information_cutoff and m.valid_from <= decision_date and (m.valid_to is None or decision_date < m.valid_to)]
        if not records:
            excluded.append((instrument, "membership_unavailable_or_not_valid")); continue
        states = {m.included for m in records}
        if len(states) != 1:
            excluded.append((instrument, "ambiguous_membership")); continue
        record = sorted(records, key=lambda m: (m.available_at, m.source_record_id))[-1]
        evidence.append(record.source_record_id)
        if not record.included:
            excluded.append((instrument, "explicitly_excluded")); continue
        if metadata_records is not None and instrument not in metadata_records:
            excluded.append((instrument, "metadata_unavailable")); continue
        delisted = any(a.instrument_id == instrument and a.action_type is CorporateActionType.DELISTING and a.effective_date <= decision_date and a.available_at <= information_cutoff for a in corporate_actions)
        if delisted:
            excluded.append((instrument, "explicitly_delisted")); continue
        eligible.append(instrument)
    if not eligible and not excluded: raise ValueError("no eligible instruments")
    return UniverseSelectionDecision(1, universe_id, universe_version, decision_date, information_cutoff, tuple(eligible), tuple(excluded), tuple(sorted(set(evidence))), ("fixed universe is not inferred from config.ASSETS",))
