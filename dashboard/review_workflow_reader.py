from pathlib import Path
from canonical_accounting.frozen_evidence import FrozenEvidenceError,load_current_frozen_evidence
from canonical_accounting.migration_approval import build_migration_approval_pack
from canonical_accounting.review_workflow import decision_metrics
def review_workflow_status(root:Path,repository_commit=None):
 try:
  frozen=load_current_frozen_evidence(root);e=frozen.source_evidence;p=build_migration_approval_pack(e,repository_commit=frozen.repository_commit,created_at=frozen.creation_timestamp);m=decision_metrics(p,());links=dict(frozen.proposal_evidence_links);missing=dict(frozen.missing_evidence)
  if frozen.approval_pack_hash and p.pack_hash != frozen.approval_pack_hash: raise ValueError("frozen approval binding is invalid")
  return {"status":"PENDING_REVIEW","outstanding":m["PENDING"],"critical_pending":m["CRITICAL_UNRESOLVED"],"coverage":m["APPROVAL_COMPLETENESS"],"evidence_version":frozen.bundle_hash,"pack_version":p.pack_hash,"proposals":[{"proposal":x.proposal_id,"type":x.proposal_type,"gaps":x.linked_gap_ids,"materiality":x.materiality.severity,"status":"PENDING","linked_evidence":links.get(x.proposal_id,()),"missing_evidence":missing.get(x.proposal_id),"confidence":tuple(sorted({item.confidence for item in frozen.evidence_inventory if item.identifier in links.get(x.proposal_id,())})),"verification":tuple(sorted({item.verification_status for item in frozen.evidence_inventory if item.identifier in links.get(x.proposal_id,())})),"evidence":x.evidence_summary,"references":(),"blockers":x.known_limitations} for x in p.proposals]}
 except FrozenEvidenceError as exc:return {"status":"NOT_FROZEN","outstanding":None,"critical_pending":None,"coverage":0,"error":str(exc),"proposals":[]}
 except Exception as exc:return {"status":"ERROR","outstanding":None,"critical_pending":None,"coverage":0,"error":str(exc),"proposals":[]}
