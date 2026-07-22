"""Read-only adapter for opening-snapshot evidence operations status."""
from datetime import datetime, timezone
from pathlib import Path

from canonical_accounting.evidence_pack import build_evidence_pack


def opening_evidence_status(root: str | Path = ".") -> dict:
    try:
        pack = build_evidence_pack(root, as_of=datetime.now(timezone.utc))
        return {
            "status": "GAPS_IDENTIFIED" if pack.gaps else "COMPLETE",
            "gap_count": len(pack.gaps),
            "critical_gaps": sum(item.severity == "CRITICAL" for item in pack.gaps),
            "coverage": str(pack.coverage.overall),
            "replay_readiness": pack.replay_readiness,
            "opening_snapshot_readiness": pack.opening_snapshot_readiness,
            "pack_hash": pack.pack_hash,
        }
    except Exception as exc:
        return {"status": "ERROR", "gap_count": None, "critical_gaps": None, "coverage": None,
                "replay_readiness": "NOT_READY", "opening_snapshot_readiness": "NOT_READY",
                "error": str(exc)}
