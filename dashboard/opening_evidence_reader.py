"""Read-only adapter for explicitly frozen evidence operations status."""
from pathlib import Path

from canonical_accounting.frozen_evidence import FrozenEvidenceError, load_current_frozen_evidence


def opening_evidence_status(root: str | Path = "data/frozen_evidence_packs") -> dict:
    try:
        pack = load_current_frozen_evidence(root)
        verification = {state: sum(item.verification_status == state for item in pack.evidence_inventory)
                        for state in ("VERIFIED", "UNVERIFIED", "REJECTED")}
        return {
            "status": pack.overall_status, "pack_id": pack.pack_id,
            "pack_version": pack.pack_version, "cutoff": pack.evidence_cutoff_timestamp.isoformat(),
            "gap_count": len(pack.source_evidence.gaps),
            "critical_gaps": sum(item.severity == "CRITICAL" for item in pack.source_evidence.gaps),
            "coverage": str(pack.coverage.overall), "coverage_metrics": pack.coverage,
            "evidence_count": len(pack.evidence_inventory), "verification": verification,
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
