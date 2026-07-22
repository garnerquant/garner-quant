from __future__ import annotations

import json
import os
from pathlib import Path

from risk_engine.models import OrderProposal, RiskContext, RiskDecision
from runtime.locks import acquire_runtime_write_lock


DEFAULT_AUDIT_PATH = Path("data/risk_engine/decisions.jsonl")


class RiskAuditError(RuntimeError):
    pass


class RiskDecisionAudit:
    def __init__(self, path=DEFAULT_AUDIT_PATH):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")

    def records_for_proposal(self, proposal_id: str) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("proposal", {}).get("proposal_id") == proposal_id:
                    records.append(payload)
        except Exception as exc:
            raise RiskAuditError("risk decision audit is unreadable or malformed") from exc
        return records

    def append(self, proposal: OrderProposal, context: RiskContext, decision: RiskDecision) -> None:
        record = {
            "schema_version": "1",
            "proposal": proposal.canonical_payload(),
            "context": context.canonical_payload(),
            "decision": decision.to_dict(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with acquire_runtime_write_lock(path=self.lock_path, context="risk_decision_audit"):
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        except Exception as exc:
            raise RiskAuditError("risk decision could not be durably audited") from exc
