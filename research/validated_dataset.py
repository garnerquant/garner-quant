"""Immutable validated research dataset boundary, disconnected from providers."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar
from strategy.serialization import to_canonical_payload, _canonical_value


PRICE_BASES = {"adjusted_total_return_research", "raw_execution_with_actions"}


def _text(value, field):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{field} is required")


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value): raise ValueError(f"{field} must be UTC")


@dataclass(frozen=True, slots=True)
class ValidatedResearchDataset:
    schema_version: int
    dataset_id: str
    dataset_version: str
    content_source_hash: str
    created_at: datetime
    information_cutoff: datetime
    price_basis: str
    bar_frequency: str
    instrument_metadata_identity: str
    quality_policy_id: str
    quality_policy_version: str
    bars: tuple[NormalizedMarketBar, ...]
    warnings: tuple[str, ...] = ()
    corporate_action_dataset_identity: str | None = None

    def __post_init__(self):
        if self.schema_version <= 0: raise ValueError("schema_version must be positive")
        for field in ("dataset_id", "dataset_version", "content_source_hash", "bar_frequency", "instrument_metadata_identity", "quality_policy_id", "quality_policy_version"):
            _text(getattr(self, field), field)
        _utc(self.created_at, "created_at"); _utc(self.information_cutoff, "information_cutoff")
        if self.price_basis not in PRICE_BASES: raise ValueError("unknown price basis")
        if self.price_basis == "raw_execution_with_actions" and not self.corporate_action_dataset_identity:
            raise ValueError("raw execution datasets require corporate-action provenance")
        if not self.bars: raise ValueError("validated dataset requires eligible bars")
        identities = set()
        for bar in self.bars:
            if not isinstance(bar, NormalizedMarketBar): raise TypeError("bars must be NormalizedMarketBar contracts")
            identity = (bar.instrument_id, bar.bar_start_utc, bar.source_record_id)
            if identity in identities: raise ValueError("duplicate bar identity")
            identities.add(identity)
            if bar.bar_status is not BarStatus.COMPLETED: raise ValueError("incomplete bars are not eligible")
            if bar.quality_status is not DataQualityStatus.VALID: raise ValueError("bar quality is not valid")
            if bar.bar_end_utc > self.information_cutoff: raise ValueError("future bar exceeds information cutoff")

    @classmethod
    def from_bars(cls, *, schema_version, dataset_id, dataset_version, content_source_hash, created_at, information_cutoff, price_basis, bar_frequency, instrument_metadata_identity, quality_policy_id, quality_policy_version, bars, warnings=(), corporate_action_dataset_identity=None):
        ordered = sorted(tuple(bars), key=lambda b: (b.instrument_id, b.bar_start_utc, b.bar_end_utc, b.source_record_id))
        # Exact duplicate observations are idempotent; conflicting identities fail in __post_init__.
        unique = []
        seen = set()
        for bar in ordered:
            identity = (bar.instrument_id, bar.bar_start_utc, bar.source_record_id)
            if identity not in seen:
                unique.append(bar); seen.add(identity)
            elif unique[-1] != bar:
                raise ValueError("conflicting duplicate bar identity")
        return cls(schema_version, dataset_id, dataset_version, content_source_hash, created_at, information_cutoff, price_basis, bar_frequency, instrument_metadata_identity, quality_policy_id, quality_policy_version, tuple(unique), tuple(warnings), corporate_action_dataset_identity)

    def payload(self):
        return {"contract_type": "validated_research_dataset", "schema_version": 1, "payload": {field.name: [to_canonical_payload(x) for x in getattr(self, field.name)] if field.name == "bars" else _canonical_value(getattr(self, field.name)) for field in fields(self)}}

    def canonical_bytes(self):
        return json.dumps(self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def canonical_sha256(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
