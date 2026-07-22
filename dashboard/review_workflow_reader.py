from datetime import datetime,timezone
from pathlib import Path
from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.migration_approval import build_migration_approval_pack
from canonical_accounting.review_workflow import decision_metrics
def review_workflow_status(root:Path,repository_commit="WORKTREE"):
 try:
  now=datetime.now(timezone.utc);e=build_evidence_pack(root,as_of=now);p=build_migration_approval_pack(e,repository_commit=repository_commit,created_at=now);m=decision_metrics(p,())
  return {"status":"PENDING_REVIEW","outstanding":m["PENDING"],"critical_pending":m["CRITICAL_UNRESOLVED"],"coverage":m["APPROVAL_COMPLETENESS"],"evidence_version":e.pack_hash,"pack_version":p.pack_hash,"proposals":[{"proposal":x.proposal_id,"type":x.proposal_type,"gaps":x.linked_gap_ids,"materiality":x.materiality.severity,"status":"PENDING","evidence":x.evidence_summary,"references":(),"blockers":x.known_limitations} for x in p.proposals]}
 except Exception as exc:return {"status":"ERROR","outstanding":None,"critical_pending":None,"coverage":0,"error":str(exc),"proposals":[]}
