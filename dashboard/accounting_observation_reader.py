from __future__ import annotations

import json
from pathlib import Path

from canonical_accounting.observation import DEFAULT_FAILURE_STORE, DEFAULT_STORE


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
