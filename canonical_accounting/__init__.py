"""Prospective, GBP-normalized accounting generation support."""

from canonical_accounting.currency import (
    ConversionResult,
    CurrencyError,
    FxQuote,
    InstrumentMetadata,
    convert_amount_to_base,
    normalize_price_to_major_unit,
)
from canonical_accounting.events import AccountingEvent, AccountingEventType
from canonical_accounting.snapshot import CanonicalPortfolioSnapshot
from canonical_accounting.successor import SuccessorGenerationWriter
from canonical_accounting.observation import AccountingObservationEnvelope, AccountingObservationStore
from canonical_accounting.non_fill_events import NonFillEventRequest, NonFillEventType
from canonical_accounting.non_fill_producers import observe_non_fill_event
from canonical_accounting.opening_snapshot import OpeningSnapshotCandidate, OpeningApprovalRecord
from canonical_accounting.evidence_pack import OpeningSnapshotEvidencePack, build_evidence_pack
from canonical_accounting.migration_approval import ApprovalPack, ApprovalRecord, MigrationProposal, build_migration_approval_pack

__all__ = [
    "ConversionResult",
    "CurrencyError",
    "FxQuote",
    "InstrumentMetadata",
    "convert_amount_to_base",
    "normalize_price_to_major_unit",
    "AccountingEvent",
    "AccountingEventType",
    "CanonicalPortfolioSnapshot",
    "SuccessorGenerationWriter",
    "AccountingObservationEnvelope",
    "AccountingObservationStore",
    "NonFillEventRequest",
    "NonFillEventType",
    "observe_non_fill_event",
    "OpeningSnapshotCandidate",
    "OpeningApprovalRecord",
    "OpeningSnapshotEvidencePack",
    "build_evidence_pack",
    "ApprovalPack", "ApprovalRecord", "MigrationProposal", "build_migration_approval_pack",
]
