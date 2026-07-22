from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from execution.atomic_io import atomic_write_json
from runtime.locks import acquire_runtime_write_lock


DEFAULT_STATE_PATH = Path("data/risk_engine/kill_switch.json")
DEFAULT_AUDIT_PATH = Path("data/risk_engine/kill_switch_audit.jsonl")


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    mode: str
    updated_at: str | None
    actor: str | None
    reason: str
    correlation_id: str | None
    valid: bool


def load_kill_switch(path=DEFAULT_STATE_PATH) -> KillSwitchState:
    path = Path(path)
    if not path.is_file():
        return KillSwitchState(True, "BLOCK_ALL", None, None, "kill-switch state is missing", None, False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1" or type(payload.get("active")) is not bool:
            raise ValueError("schema invalid")
        if payload.get("mode") not in {"BLOCK_ALL", "NORMAL"}:
            raise ValueError("mode invalid")
        if bool(payload["active"]) != (payload["mode"] == "BLOCK_ALL"):
            raise ValueError("state contradictory")
        timestamp = datetime.fromisoformat(str(payload["updated_at"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timestamp ambiguous")
        reason = str(payload.get("reason") or "").strip()
        actor = str(payload.get("actor") or "").strip()
        correlation_id = str(payload.get("correlation_id") or "").strip()
        if not reason or not actor or not correlation_id:
            raise ValueError("audit identity missing")
        return KillSwitchState(
            bool(payload["active"]), payload["mode"], timestamp.astimezone(timezone.utc).isoformat(),
            actor, reason, correlation_id, True,
        )
    except Exception:
        return KillSwitchState(True, "BLOCK_ALL", None, None, "kill-switch state is invalid or unreadable", None, False)


def _append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def set_kill_switch(
    active: bool,
    *,
    actor: str,
    reason: str,
    correlation_id: str,
    state_path=DEFAULT_STATE_PATH,
    audit_path=DEFAULT_AUDIT_PATH,
    now=None,
) -> KillSwitchState:
    if type(active) is not bool:
        raise ValueError("kill-switch active state must be boolean")
    actor = str(actor or "").strip()
    reason = str(reason or "").strip()
    correlation_id = str(correlation_id or "").strip()
    if not actor or not reason or not correlation_id:
        raise ValueError("actor, reason, and correlation_id are required")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("kill-switch timestamp must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    state_path = Path(state_path)
    audit_path = Path(audit_path)
    lock_path = state_path.with_suffix(".lock")
    with acquire_runtime_write_lock(path=lock_path, context="risk_kill_switch_change"):
        previous = load_kill_switch(state_path)
        payload = {
            "schema_version": "1",
            "active": active,
            "mode": "BLOCK_ALL" if active else "NORMAL",
            "updated_at": instant.isoformat(),
            "actor": actor,
            "reason": reason,
            "correlation_id": correlation_id,
        }
        record = {
            "timestamp": instant.isoformat(),
            "previous_state": asdict(previous),
            "new_state": payload,
            "actor": actor,
            "reason": reason,
            "correlation_id": correlation_id,
        }
        _append_record(audit_path, record)
        atomic_write_json(payload, state_path, lock_path=lock_path, json_kwargs={"indent": 2})
    return load_kill_switch(state_path)
