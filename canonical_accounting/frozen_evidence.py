"""Authoritative evidence ingestion and immutable Evidence Pack freezing.

Frozen Evidence Packs are governance artifacts only.  This module has no
accounting, candidate, generation, pointer, lot, risk, or execution dependency.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from canonical_accounting.evidence_pack import (
    CoverageMetrics,
    EvidenceGap,
    EvidenceSource,
    FxEvidence,
    LotEvidence,
    NonFillCoverage,
    OpeningSnapshotEvidencePack,
    PositionEvidence,
)

SCHEMA_VERSION = "1.0"
PACK_VERSION_FORMAT = re.compile(r"^[1-9][0-9]*$")
IDENTIFIER_FORMAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DOCUMENT_TYPES = frozenset({
    "BROKER_STATEMENT", "TRADE_CONFIRMATION", "CASH_STATEMENT",
    "DIVIDEND_STATEMENT", "CORPORATE_ACTION", "FX_RECORD",
    "TAX_STATEMENT", "MANUAL_OPERATOR_DOCUMENT",
})
RECORD_TYPES = frozenset({
    "TRADE", "CASH_MOVEMENT", "DIVIDEND", "FEE", "TAX",
    "FX_CONVERSION", "CORPORATE_ACTION", "ADJUSTMENT",
})
CONFIDENCE_LEVELS = frozenset({"HIGH", "MEDIUM", "LOW", "UNKNOWN"})
VERIFICATION_STATES = frozenset({"VERIFIED", "UNVERIFIED", "REJECTED"})


class FrozenEvidenceError(ValueError):
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


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _time(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FrozenEvidenceError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class NormalizedEvidenceRecord:
    record_id: str
    record_type: str
    effective_timestamp: datetime
    currency: str | None = None
    amount: str | None = None
    quantity: str | None = None
    price: str | None = None
    fields: tuple[tuple[str, str], ...] = ()
    unknown_fields: tuple[str, ...] = ()

    def validate(self):
        if not self.record_id or self.record_type not in RECORD_TYPES:
            raise FrozenEvidenceError("normalized record identity or type is invalid")
        _time(self.effective_timestamp, "effective_timestamp")
        if len({key for key, _ in self.fields}) != len(self.fields):
            raise FrozenEvidenceError("normalized record contains duplicate fields")
        for field in ("amount", "quantity", "price"):
            value = getattr(self, field)
            if value is not None:
                try:
                    number = Decimal(value)
                except Exception as exc:
                    raise FrozenEvidenceError(f"{field} is invalid") from exc
                if not number.is_finite():
                    raise FrozenEvidenceError(f"{field} is invalid")
        return self


@dataclass(frozen=True)
class EvidenceDocumentRequest:
    source: str
    identifier: str
    source_timestamp: datetime
    document_type: str
    coverage_start: datetime
    coverage_end: datetime
    confidence: str
    verification_status: str
    linked_gap_ids: tuple[str, ...]
    associated_positions: tuple[str, ...] = ()
    associated_cash_flows: tuple[str, ...] = ()
    associated_lots: tuple[str, ...] = ()
    normalized_records: tuple[NormalizedEvidenceRecord, ...] = ()

    def validate(self, gap_ids):
        if not self.source or not IDENTIFIER_FORMAT.fullmatch(self.identifier):
            raise FrozenEvidenceError("evidence source or identifier is invalid")
        if self.document_type not in DOCUMENT_TYPES:
            raise FrozenEvidenceError("unsupported evidence document type")
        if self.confidence not in CONFIDENCE_LEVELS or self.verification_status not in VERIFICATION_STATES:
            raise FrozenEvidenceError("evidence confidence or verification state is invalid")
        source_time = _time(self.source_timestamp, "source_timestamp")
        start = _time(self.coverage_start, "coverage_start")
        end = _time(self.coverage_end, "coverage_end")
        if start > end or source_time < start:
            raise FrozenEvidenceError("evidence coverage is invalid")
        if not self.linked_gap_ids or not set(self.linked_gap_ids) <= set(gap_ids):
            raise FrozenEvidenceError("evidence must link existing gaps")
        record_ids = [item.record_id for item in self.normalized_records]
        if len(record_ids) != len(set(record_ids)):
            raise FrozenEvidenceError("duplicate normalized record identity")
        for item in self.normalized_records:
            item.validate()
        return self


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    identifier: str
    source_timestamp: datetime
    checksum: str
    byte_size: int
    document_type: str
    coverage_start: datetime
    coverage_end: datetime
    confidence: str
    verification_status: str
    linked_gap_ids: tuple[str, ...]
    associated_positions: tuple[str, ...]
    associated_cash_flows: tuple[str, ...]
    associated_lots: tuple[str, ...]
    normalized_records: tuple[NormalizedEvidenceRecord, ...]
    artifact_name: str


@dataclass(frozen=True)
class CollectedEvidence:
    item: EvidenceItem
    content: bytes


def collect_evidence(path: str | Path, request: EvidenceDocumentRequest, *, gap_ids) -> CollectedEvidence:
    """Read one explicitly supplied document; never discover or infer evidence."""
    request.validate(gap_ids)
    source_path = Path(path)
    if not source_path.is_file():
        raise FrozenEvidenceError("authoritative evidence document is missing")
    content = source_path.read_bytes()
    if not content:
        raise FrozenEvidenceError("authoritative evidence document is empty")
    suffix = source_path.suffix.lower()
    artifact_name = f"documents/{request.identifier}{suffix}"
    item = EvidenceItem(
        request.source, request.identifier, _time(request.source_timestamp, "source_timestamp"),
        _bytes_hash(content), len(content), request.document_type,
        _time(request.coverage_start, "coverage_start"), _time(request.coverage_end, "coverage_end"),
        request.confidence, request.verification_status, tuple(sorted(request.linked_gap_ids)),
        tuple(sorted(request.associated_positions)), tuple(sorted(request.associated_cash_flows)),
        tuple(sorted(request.associated_lots)), tuple(request.normalized_records), artifact_name,
    )
    return CollectedEvidence(item, content)


def validate_collection(collection: tuple[CollectedEvidence, ...], *, gap_ids) -> tuple[CollectedEvidence, ...]:
    by_id = {}
    for entry in collection:
        entry.item.normalized_records and [item.validate() for item in entry.item.normalized_records]
        if not set(entry.item.linked_gap_ids) <= set(gap_ids):
            raise FrozenEvidenceError("collected evidence links unknown gap")
        if _bytes_hash(entry.content) != entry.item.checksum or len(entry.content) != entry.item.byte_size:
            raise FrozenEvidenceError("collected evidence content changed")
        previous = by_id.get(entry.item.identifier)
        if previous is not None:
            if previous.item != entry.item or previous.content != entry.content:
                raise FrozenEvidenceError("conflicting duplicate evidence identifier")
            continue
        by_id[entry.item.identifier] = entry
    return tuple(sorted(by_id.values(), key=lambda value: value.item.identifier))


@dataclass(frozen=True)
class FrozenCoverage:
    strategy: Decimal
    fifo: Decimal
    position: Decimal
    cash: Decimal
    dividend: Decimal
    fx: Decimal
    fee: Decimal
    tax: Decimal
    corporate_action: Decimal
    overall: Decimal
    unknown: Decimal


def _coverage(found, expected):
    if not expected:
        return Decimal("100.00")
    return (Decimal(len(set(found) & set(expected))) * 100 / Decimal(len(set(expected)))).quantize(Decimal("0.01"))


def calculate_frozen_coverage(evidence: OpeningSnapshotEvidencePack, items: tuple[EvidenceItem, ...]) -> FrozenCoverage:
    verified = [item for item in items if item.verification_status == "VERIFIED"]
    positions = {item.symbol for item in evidence.positions}
    lots = {item.source_event_id for item in evidence.lots}
    record_types = {record.record_type for item in verified for record in item.normalized_records}
    covered_positions = {value for item in verified for value in item.associated_positions}
    covered_lots = {value for item in verified for value in item.associated_lots}
    strategy_positions = {value for item in verified if item.document_type == "MANUAL_OPERATOR_DOCUMENT" for value in item.associated_positions}
    values = (
        _coverage(strategy_positions, positions), _coverage(covered_lots, lots),
        _coverage(covered_positions, positions), Decimal("100.00") if "CASH_MOVEMENT" in record_types else Decimal("0.00"),
        Decimal("100.00") if "DIVIDEND" in record_types else Decimal("0.00"),
        Decimal("100.00") if "FX_CONVERSION" in record_types else Decimal("0.00"),
        Decimal("100.00") if "FEE" in record_types else Decimal("0.00"),
        Decimal("100.00") if "TAX" in record_types else Decimal("0.00"),
        Decimal("100.00") if "CORPORATE_ACTION" in record_types else Decimal("0.00"),
    )
    overall = (sum(values) / Decimal(len(values))).quantize(Decimal("0.01"))
    return FrozenCoverage(*values, overall, Decimal("100.00") - overall)


@dataclass(frozen=True)
class FrozenEvidencePack:
    path: Path
    pack_id: str
    pack_version: str
    repository_commit: str
    creation_timestamp: datetime
    evidence_cutoff_timestamp: datetime
    schema_version: str
    evidence_hash: str
    overall_status: str
    gap_summary: tuple[tuple[str, int], ...]
    artifact_manifest: tuple[tuple[str, str, int], ...]
    evidence_inventory: tuple[EvidenceItem, ...]
    coverage: FrozenCoverage
    proposal_evidence_links: tuple[tuple[str, tuple[str, ...]], ...]
    missing_evidence: tuple[tuple[str, str], ...]
    source_evidence: OpeningSnapshotEvidencePack
    approval_pack_id: str | None
    approval_pack_hash: str | None
    bundle_hash: str


def _decode_time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _time(result, "timestamp")


def _decode_source_evidence(value) -> OpeningSnapshotEvidencePack:
    coverage = CoverageMetrics(**{key: Decimal(item) for key, item in value["coverage"].items()})
    return OpeningSnapshotEvidencePack(
        value["schema_version"], _decode_time(value["as_of"]),
        tuple(EvidenceSource(**{**item, "limitations": tuple(item["limitations"])}) for item in value["sources"]),
        tuple(PositionEvidence(**{**item, "quantity": Decimal(item["quantity"]), "market_value": Decimal(item["market_value"]) if item["market_value"] is not None else None}) for item in value["positions"]),
        tuple(LotEvidence(**{**item, "remaining_quantity": Decimal(item["remaining_quantity"]), "missing": tuple(item["missing"])}) for item in value["lots"]),
        tuple(FxEvidence(**item) for item in value["fx"]), tuple(NonFillCoverage(**item) for item in value["non_fill"]),
        tuple(EvidenceGap(**{**item, "affected_positions": tuple(item["affected_positions"]), "affected_value": Decimal(item["affected_value"]) if item["affected_value"] is not None else None, "affected_strategies": tuple(item["affected_strategies"]), "affected_currencies": tuple(item["affected_currencies"])}) for item in value["gaps"]),
        coverage, Decimal(value["unattributed_exposure"]), Decimal(value["unattributed_cash"]), int(value["unattributed_lots"]),
        value["opening_snapshot_readiness"], value["replay_readiness"],
    )


def _decode_record(value):
    return NormalizedEvidenceRecord(value["record_id"], value["record_type"], _decode_time(value["effective_timestamp"]), value.get("currency"), value.get("amount"), value.get("quantity"), value.get("price"), tuple(tuple(x) for x in value.get("fields", ())), tuple(value.get("unknown_fields", ())))


def _decode_item(value):
    return EvidenceItem(value["source"], value["identifier"], _decode_time(value["source_timestamp"]), value["checksum"], int(value["byte_size"]), value["document_type"], _decode_time(value["coverage_start"]), _decode_time(value["coverage_end"]), value["confidence"], value["verification_status"], tuple(value["linked_gap_ids"]), tuple(value["associated_positions"]), tuple(value["associated_cash_flows"]), tuple(value["associated_lots"]), tuple(_decode_record(x) for x in value["normalized_records"]), value["artifact_name"])


def freeze_evidence_pack(evidence: OpeningSnapshotEvidencePack, collection: tuple[CollectedEvidence, ...], destination: str | Path, *, pack_version: str, repository_commit: str, created_at: datetime, evidence_cutoff: datetime, approval_pack=None, failure_hook=None) -> Path:
    """Atomically create a new immutable pack version; never update an old one."""
    if not PACK_VERSION_FORMAT.fullmatch(str(pack_version)) or not repository_commit:
        raise FrozenEvidenceError("pack version or repository commit is invalid")
    created_at = _time(created_at, "created_at"); evidence_cutoff = _time(evidence_cutoff, "evidence_cutoff")
    if evidence.as_of != evidence_cutoff:
        raise FrozenEvidenceError("evidence audit and freeze cut-off differ")
    gap_ids = {gap.gap_id for gap in evidence.gaps}
    collection = validate_collection(tuple(collection), gap_ids=gap_ids)
    items = tuple(entry.item for entry in collection)
    coverage = calculate_frozen_coverage(evidence, items)
    links = []
    missing = []
    if approval_pack is not None:
        if approval_pack.evidence_hash != evidence.pack_hash:
            raise FrozenEvidenceError("approval pack does not bind source evidence")
        for proposal in approval_pack.proposals:
            evidence_ids = tuple(sorted(item.identifier for item in items if set(item.linked_gap_ids) & set(proposal.linked_gap_ids)))
            links.append((proposal.proposal_id, evidence_ids))
            if not evidence_ids:
                missing.append((proposal.proposal_id, "No linked authoritative evidence"))
    material = {"version": str(pack_version), "commit": repository_commit, "created_at": created_at, "cutoff": evidence_cutoff, "evidence": evidence.pack_hash, "items": tuple((item.identifier, item.checksum) for item in items), "approval": getattr(approval_pack, "pack_hash", None)}
    pack_id = "evidence-freeze-" + _hash(material)[:24]
    root = Path(destination); final = root / f"v{pack_version}-{pack_id}"; staging = root / f".staging-{pack_id}"
    if root.exists():
        for existing in root.iterdir():
            if existing.is_dir() and not existing.name.startswith(".staging-"):
                if load_frozen_evidence_pack(existing).pack_version == str(pack_version):
                    raise FrozenEvidenceError("frozen Evidence Pack version already exists")
    if final.exists() or staging.exists():
        raise FrozenEvidenceError("frozen Evidence Pack version already exists")
    root.mkdir(parents=True, exist_ok=True); staging.mkdir()
    try:
        _write_bytes(staging / "source_evidence.json", _serialize(evidence).encode())
        _write_bytes(staging / "evidence_inventory.json", _serialize(items).encode())
        _write_bytes(staging / "coverage.json", _serialize(coverage).encode())
        _write_bytes(staging / "gap_register.json", _serialize(evidence.gaps).encode())
        _write_bytes(staging / "proposal_links.json", _serialize({"links": tuple(links), "missing": tuple(missing)}).encode())
        for entry in collection:
            _write_bytes(staging / entry.item.artifact_name, entry.content)
        if failure_hook: failure_hook("after_artifacts", staging)
        artifacts = tuple(sorted((str(path.relative_to(staging)).replace("\\", "/"), _bytes_hash(path.read_bytes()), path.stat().st_size) for path in staging.rglob("*") if path.is_file()))
        gap_summary = tuple(sorted((severity, sum(gap.severity == severity for gap in evidence.gaps)) for severity in {gap.severity for gap in evidence.gaps}))
        manifest = {"pack_id": pack_id, "pack_version": str(pack_version), "repository_commit": repository_commit, "creation_timestamp": created_at, "evidence_cutoff_timestamp": evidence_cutoff, "schema_version": SCHEMA_VERSION, "evidence_hash": evidence.pack_hash, "overall_status": "GAPS_IDENTIFIED" if evidence.gaps else "COMPLETE", "gap_summary": gap_summary, "artifact_manifest": artifacts, "coverage": coverage, "evidence_count": len(items), "verification_summary": tuple((state, sum(item.verification_status == state for item in items)) for state in sorted(VERIFICATION_STATES)), "proposal_evidence_links": tuple(links), "missing_evidence": tuple(missing), "approval_pack_id": getattr(approval_pack, "pack_id", None), "approval_pack_hash": getattr(approval_pack, "pack_hash", None)}
        manifest["bundle_hash"] = _hash(manifest)
        _write_bytes(staging / "manifest.json", _serialize(manifest).encode())
        if failure_hook: failure_hook("after_manifest", staging)
        load_frozen_evidence_pack(staging)
        staging.replace(final)
        return final
    except Exception:
        if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
        raise


def load_frozen_evidence_pack(path: str | Path) -> FrozenEvidencePack:
    path = Path(path)
    try: manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except Exception as exc: raise FrozenEvidenceError("frozen Evidence Pack manifest is missing or malformed") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION or _hash({key:value for key,value in manifest.items() if key != "bundle_hash"}) != manifest.get("bundle_hash"):
        raise FrozenEvidenceError("frozen Evidence Pack manifest hash is invalid")
    for name, checksum, size in manifest.get("artifact_manifest", []):
        artifact = path / name
        if not artifact.is_file() or artifact.stat().st_size != size or _bytes_hash(artifact.read_bytes()) != checksum:
            raise FrozenEvidenceError(f"frozen evidence artifact is invalid: {name}")
    source = _decode_source_evidence(json.loads((path / "source_evidence.json").read_text()))
    if source.pack_hash != manifest["evidence_hash"]:
        raise FrozenEvidenceError("frozen source evidence hash is invalid")
    items = tuple(_decode_item(value) for value in json.loads((path / "evidence_inventory.json").read_text()))
    coverage = FrozenCoverage(**{key:Decimal(value) for key,value in json.loads((path / "coverage.json").read_text()).items()})
    links = json.loads((path / "proposal_links.json").read_text())
    return FrozenEvidencePack(path, manifest["pack_id"], manifest["pack_version"], manifest["repository_commit"], _decode_time(manifest["creation_timestamp"]), _decode_time(manifest["evidence_cutoff_timestamp"]), manifest["schema_version"], manifest["evidence_hash"], manifest["overall_status"], tuple(tuple(x) for x in manifest["gap_summary"]), tuple((x[0],x[1],int(x[2])) for x in manifest["artifact_manifest"]), items, coverage, tuple((x[0],tuple(x[1])) for x in links["links"]), tuple(tuple(x) for x in links["missing"]), source, manifest.get("approval_pack_id"), manifest.get("approval_pack_hash"), manifest["bundle_hash"])


def load_current_frozen_evidence(root: str | Path) -> FrozenEvidencePack:
    root = Path(root)
    candidates = []
    if root.exists():
        for path in root.iterdir():
            if path.is_dir() and not path.name.startswith(".staging-"):
                pack = load_frozen_evidence_pack(path); candidates.append((int(pack.pack_version), pack))
    if not candidates:
        raise FrozenEvidenceError("no frozen Evidence Pack is available")
    versions = [version for version, _ in candidates]
    if len(versions) != len(set(versions)):
        raise FrozenEvidenceError("duplicate frozen Evidence Pack version")
    return max(candidates, key=lambda value:value[0])[1]


def export_frozen_evidence_bundle(path: str | Path) -> str:
    pack = load_frozen_evidence_pack(path)
    payload = {"manifest": json.loads((pack.path / "manifest.json").read_text()), "coverage": _json(pack.coverage), "gap_register": json.loads((pack.path / "gap_register.json").read_text()), "evidence_inventory": json.loads((pack.path / "evidence_inventory.json").read_text()), "repository_commit": pack.repository_commit, "creation_timestamp": pack.creation_timestamp, "schema_version": pack.schema_version}
    payload["export_hash"] = _hash(payload)
    return _serialize(payload)
