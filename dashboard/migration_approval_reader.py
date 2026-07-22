"""Read-only Operations adapter bound to an immutable frozen Evidence Pack."""
from pathlib import Path
from canonical_accounting.frozen_evidence import FrozenEvidenceError, load_current_frozen_evidence
from canonical_accounting.migration_approval import build_migration_approval_pack

def migration_approval_status(root:Path,repository_commit:str|None=None):
    try:
        frozen=load_current_frozen_evidence(root)
        pack=build_migration_approval_pack(frozen.source_evidence,repository_commit=frozen.repository_commit,created_at=frozen.creation_timestamp)
        if frozen.approval_pack_hash and pack.pack_hash != frozen.approval_pack_hash:
            raise ValueError("frozen approval binding is invalid")
        links=dict(frozen.proposal_evidence_links);missing=dict(frozen.missing_evidence)
        return {"status":"PENDING_REVIEW","pending":pack.summary["PENDING"],"approved":pack.summary["APPROVED"],"rejected":pack.summary["REJECTED"],"coverage":str(pack.coverage),"critical":sum(x.materiality.severity=="CRITICAL" for x in pack.proposals),"readiness":pack.readiness,"pack_id":pack.pack_id,"frozen_pack_id":frozen.pack_id,"linked_evidence":links,"missing_evidence":missing}
    except FrozenEvidenceError as exc:return {"status":"NOT_FROZEN","pending":None,"approved":None,"rejected":None,"coverage":None,"critical":None,"readiness":"NOT_READY","error":str(exc)}
    except Exception as exc:return {"status":"ERROR","pending":None,"approved":None,"rejected":None,"coverage":None,"critical":None,"readiness":"NOT_READY","error":str(exc)}
