from __future__ import annotations

import json
from pathlib import Path

from canonical_accounting.observation import DEFAULT_FAILURE_STORE, DEFAULT_STORE
from canonical_accounting.non_fill_producers import producer_framework_status


def _read(path):
    path = Path(path)
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def accounting_observation_status(path=DEFAULT_STORE, failure_path=DEFAULT_FAILURE_STORE):
    try:
        records = _read(path); failures = _read(failure_path); latest = records[-1] if records else None
        return {"health": "VALID" if records and not failures else "ERROR" if failures else "PENDING",
                "validation": "PASS" if records and not failures else "FAIL" if failures else "PENDING",
                "version": latest.get("schema_version") if latest else "1.0", "count": len(records),
                "latest": latest, "missing_fields": failures[-1].get("reason") if failures else "None"}
    except Exception as exc:
        return {"health": "ERROR", "validation": "FAIL", "version": "UNKNOWN", "count": 0,
                "latest": None, "missing_fields": str(exc)}


def non_fill_observation_status(path=DEFAULT_STORE, failure_path=DEFAULT_FAILURE_STORE):
    framework=producer_framework_status()
    try:
        non_fill={"DEPOSIT","WITHDRAWAL","DIVIDEND","FEE","FX_ADJUSTMENT","CORPORATE_ACTION"}
        records=[row for row in _read(path) if row.get("event_type") in non_fill]
        failures=[row for row in _read(failure_path) if str(row.get("event_type","")) in non_fill or "NonFillEventType" in str(row.get("event_type",""))]
        counts={kind:sum(row.get("event_type")==kind for row in records) for kind in sorted(non_fill)}
        conflicts=sum("duplicate" in str(row.get("reason","")).lower() for row in failures)
        return {**framework,"validation_health":"ERROR" if failures else "VALID" if records else "PENDING",
                "latest_non_fill":records[-1] if records else None,"latest_invalid":failures[-1] if failures else None,
                "counts_by_event_type":counts,"duplicate_conflict_count":conflicts,
                "last_observation_timestamp":records[-1].get("created_at") if records else None}
    except Exception as exc:
        return {**framework,"validation_health":"ERROR","latest_non_fill":None,"latest_invalid":{"reason":str(exc)},
                "counts_by_event_type":{},"duplicate_conflict_count":0,"last_observation_timestamp":None}
