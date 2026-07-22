"""Read-only evidence acquisition with explicit provenance and unknowns."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import GENERATOR_VERSION, SCHEMA_VERSION, aware, stable_hash


@dataclass(frozen=True)
class EvidenceDatum:
    evidence_id: str
    evidence_type: str
    fields: tuple[tuple[str, str | None], ...]
    source_artifact: str
    source_record_identifier: str
    source_version: str
    observation_timestamp: str | None
    ingestion_timestamp: datetime
    schema_version: str
    evidence_status: str
    content_hash: str


@dataclass(frozen=True)
class ResearchEvidenceSnapshot:
    snapshot_id: str
    schema_version: str
    artifact_type: str
    predecessor_id: str | None
    source_cutoff: datetime
    created_at: datetime
    generator_version: str
    records: tuple[EvidenceDatum, ...]
    source_hashes: tuple[tuple[str, str], ...]
    unsupported_fields: tuple[str, ...]

    @property
    def content_hash(self): return stable_hash(asdict(self))


def _file_hash(path):
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _datum(kind, fields, artifact, record_id, timestamp, ingested, status="AVAILABLE"):
    canonical = tuple(sorted((str(key), None if value is None or str(value).strip() in {"", "nan", "None"} else str(value))
                             for key, value in fields.items()))
    material = {"type": kind, "fields": canonical, "artifact": artifact, "record": record_id,
                "timestamp": timestamp, "status": status}
    digest = stable_hash(material)
    return EvidenceDatum("evidence-" + digest[:24], kind, canonical, artifact, record_id, "source-file-v1",
                         timestamp, ingested, SCHEMA_VERSION, status, digest)


def _csv_records(root, relative, cutoff, ingested):
    path = root / relative
    if not path.is_file(): return (), None
    with path.open(encoding="utf-8-sig", newline="") as handle: rows = list(csv.DictReader(handle))
    values = []
    for index, row in enumerate(rows, 2):
        timestamp = row.get("close_time") or row.get("timestamp") or row.get("date")
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")) if timestamp else None
            if parsed and parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError: parsed = None
        if parsed and parsed.astimezone(timezone.utc) > cutoff: continue
        kind = "COMPLETED_TRADE" if relative == "trade_audit_trail.csv" else "TRADE_EVENT"
        allowed = ("symbol", "ticker", "open_time", "close_time", "holding_period", "buy_price", "sell_price",
                   "shares", "pnl", "pnl_pct", "open_reason", "close_reason", "trade_result", "strategy",
                   "entry_event_id", "exit_event_id", "action", "fees", "source", "mode", "status", "reason")
        values.append(_datum(kind, {key: row.get(key) for key in allowed if key in row}, relative,
                             f"row-{index}", timestamp, ingested))
    return tuple(values), _file_hash(path)


def _decision_records(root, cutoff, ingested):
    relative = "data/runtime_decision_trace.json"; path = root / relative
    if not path.is_file(): return (), None
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError): return (), _file_hash(path)
    values = []
    for index, row in enumerate(payload.get("decisions", ()), 1):
        timestamp = row.get("timestamp")
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError): continue
        if parsed.astimezone(timezone.utc) > cutoff: continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        fields = {key: row.get(key) for key in ("ticker", "signal", "portfolio_decision", "trade_action", "reason")}
        fields.update({key: details.get(key) for key in ("risk_decision_id", "risk_status")})
        values.append(_datum("MONITOR_DECISION", fields, relative, f"decision-{index}", timestamp, ingested))
    return tuple(values), _file_hash(path)


def build_evidence_snapshot(root: str | Path, *, cutoff: datetime, created_at: datetime,
                            predecessor_id=None) -> ResearchEvidenceSnapshot:
    root = Path(root).resolve(); cutoff = aware(cutoff, "cutoff"); created_at = aware(created_at, "created_at")
    records = []; hashes = []
    for relative in ("trade_audit_trail.csv", "trade_ledger_v1.csv"):
        found, digest = _csv_records(root, relative, cutoff, created_at); records.extend(found)
        if digest: hashes.append((relative, digest))
    found, digest = _decision_records(root, cutoff, created_at); records.extend(found)
    if digest: hashes.append(("data/runtime_decision_trace.json", digest))
    records = tuple(sorted(records, key=lambda item: item.evidence_id)); hashes = tuple(sorted(hashes))
    unsupported = ("maximum_favourable_excursion", "maximum_adverse_excursion", "slippage", "strategy_version",
                   "market_regime", "volatility_regime", "market_breadth", "portfolio_context_at_entry",
                   "rejected_signal_counterfactual_outcome")
    material = {"cutoff": cutoff, "records": tuple(item.content_hash for item in records), "hashes": hashes,
                "predecessor": predecessor_id}
    return ResearchEvidenceSnapshot("snapshot-" + stable_hash(material)[:24], SCHEMA_VERSION,
        "RESEARCH_EVIDENCE_SNAPSHOT", predecessor_id, cutoff, created_at, GENERATOR_VERSION,
        records, hashes, unsupported)
