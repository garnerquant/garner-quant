"""Read-only Operations adapter for migration approval governance."""
from datetime import datetime, timezone
from pathlib import Path
from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.migration_approval import build_migration_approval_pack

def migration_approval_status(root:Path,repository_commit:str="WORKTREE"):
    try:
        now=datetime.now(timezone.utc);evidence=build_evidence_pack(root,as_of=now)
        pack=build_migration_approval_pack(evidence,repository_commit=repository_commit,created_at=now)
        return {"status":"PENDING_REVIEW","pending":pack.summary["PENDING"],"approved":pack.summary["APPROVED"],"rejected":pack.summary["REJECTED"],"coverage":str(pack.coverage),"critical":sum(x.materiality.severity=="CRITICAL" for x in pack.proposals),"readiness":pack.readiness,"pack_id":pack.pack_id}
    except Exception as exc:return {"status":"ERROR","pending":None,"approved":None,"rejected":None,"coverage":None,"critical":None,"readiness":"NOT_READY","error":str(exc)}
