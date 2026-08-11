"""Explicit-root append-only prospective FundamentalObservation storage."""

from dataclasses import fields
import json
from pathlib import Path

from data.point_in_time import FundamentalObservation, canonical_point_in_time_bytes, canonical_point_in_time_sha256


class SnapshotStoreError(ValueError):
    pass


class FundamentalSnapshotStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_absolute():
            raise SnapshotStoreError("storage root must be explicit")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "fundamental_observations.jsonl"

    def _records(self):
        if not self.path.exists(): return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try: envelope = json.loads(line)
            except json.JSONDecodeError as exc: raise SnapshotStoreError("corrupt snapshot JSON") from exc
            if envelope.get("sha256") != __import__("hashlib").sha256(canonical_point_in_time_bytes(_from_payload(envelope["payload"]))).hexdigest():
                raise SnapshotStoreError("snapshot hash mismatch")
            records.append(_from_payload(envelope["payload"]))
        return records

    def append(self, observation: FundamentalObservation):
        records = self._records()
        identity = (observation.instrument_id, observation.field_name, observation.source_record_id)
        for existing in records:
            if (existing.instrument_id, existing.field_name, existing.source_record_id) == identity:
                if existing == observation: return
                raise SnapshotStoreError("conflicting reuse of snapshot record identity")
        payload = {field.name: getattr(observation, field.name) for field in fields(observation)}
        # Reuse the point-in-time canonical encoder by storing its canonical payload.
        canonical = json.loads(canonical_point_in_time_bytes(observation).decode("utf-8"))
        line = {"payload": canonical["payload"], "sha256": canonical_point_in_time_sha256(observation)}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def query(self, instrument_id, field_name, information_cutoff):
        records = [r for r in self._records() if r.instrument_id == instrument_id and r.field_name == field_name and r.eligibility(information_cutoff).eligible]
        return tuple(sorted(records, key=lambda r: (r.available_at, r.source_revision_id or "", r.source_record_id)))

    def content_hash(self):
        return __import__("hashlib").sha256(self.path.read_bytes() if self.path.exists() else b"").hexdigest()


def _from_payload(payload):
    from datetime import date, datetime, timezone
    from decimal import Decimal
    def dt(value): return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) if value else None
    def d(value): return date.fromisoformat(value) if value else None
    value = payload["value"]
    if payload["value_type"] == "decimal": value = Decimal(value)
    return FundamentalObservation(schema_version=payload["schema_version"], instrument_id=payload["instrument_id"], field_name=payload["field_name"], value=value, value_type=payload["value_type"], currency=payload["currency"], period_start=d(payload["period_start"]), period_end=d(payload["period_end"]), reported_at=dt(payload["reported_at"]), observed_at=dt(payload["observed_at"]), available_at=dt(payload["available_at"]), source_name=payload["source_name"], source_record_id=payload["source_record_id"], collection_run_id=payload["collection_run_id"], quality_status=payload["quality_status"], source_revision_id=payload["source_revision_id"], metadata=tuple(tuple(item) for item in payload["metadata"]))
