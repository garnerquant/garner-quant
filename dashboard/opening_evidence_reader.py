"""Read-only adapter for explicitly frozen evidence operations status."""
from pathlib import Path

from canonical_accounting.frozen_evidence import FrozenEvidenceError, load_frozen_evidence_history


def opening_evidence_status(root: str | Path = "data/frozen_evidence_packs") -> dict:
    try:
        history = load_frozen_evidence_history(root); pack = history[-1]
        previous = history[-2] if len(history) > 1 else None
        verification = {state: sum(item.verification_status == state for item in pack.evidence_inventory)
                        for state in ("VERIFIED", "UNVERIFIED", "REJECTED")}
        report = pack.reconciliation_report or {}
        gap_states = {item["state"]: sum(gap["state"] == item["state"] for gap in report.get("gaps", ()))
                      for item in report.get("gaps", ())}
        return {
            "status": pack.overall_status, "pack_id": pack.pack_id,
            "previous_pack_id": previous.pack_id if previous else None,
            "pack_version": pack.pack_version, "cutoff": pack.evidence_cutoff_timestamp.isoformat(),
            "gap_count": len(pack.source_evidence.gaps),
            "critical_gaps": sum(item.severity == "CRITICAL" for item in pack.source_evidence.gaps),
            "coverage": str(pack.coverage.overall), "coverage_metrics": pack.coverage,
            "coverage_improvement": dict(pack.coverage_change),
            "evidence_count": len(pack.evidence_inventory), "verification": verification,
            "resolved_gaps": gap_states.get("RESOLVED", 0), "outstanding_gaps": gap_states.get("OPEN", len(pack.source_evidence.gaps)),
            "conflict_count": report.get("conflicts", 0),
            "import_history": tuple((item.identifier, item.import_timestamp.isoformat()) for item in pack.evidence_inventory),
            "replay_readiness": pack.source_evidence.replay_readiness,
            "opening_snapshot_readiness": pack.source_evidence.opening_snapshot_readiness,
            "pack_hash": pack.bundle_hash,
        }
    except FrozenEvidenceError as exc:
        return {"status": "NOT_FROZEN", "gap_count": None, "critical_gaps": None, "coverage": None,
                "replay_readiness": "NOT_READY", "opening_snapshot_readiness": "NOT_READY",
                "error": str(exc)}
    except Exception as exc:
        return {"status": "ERROR", "gap_count": None, "critical_gaps": None, "coverage": None,
                "replay_readiness": "NOT_READY", "opening_snapshot_readiness": "NOT_READY",
                "error": str(exc)}
