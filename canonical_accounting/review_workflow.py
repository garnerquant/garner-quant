"""Governance-only operator review records and deterministic export bundles."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from enum import Enum
from canonical_accounting.migration_approval import ApprovalPack,MigrationPackError

SCHEMA_VERSION="1.0"
class ReviewState(str,Enum):
 PENDING="PENDING";APPROVED="APPROVED";REJECTED="REJECTED";CHANGES_REQUIRED="CHANGES_REQUIRED";EXPIRED="EXPIRED"
def _j(v):
 if isinstance(v,datetime):return v.astimezone(timezone.utc).isoformat()
 if isinstance(v,Enum):return v.value
 if isinstance(v,tuple):return [_j(x) for x in v]
 if isinstance(v,dict):return {str(k):_j(x) for k,x in v.items()}
 if hasattr(v,"__dataclass_fields__"):return _j(asdict(v))
 return v
def _hash(v):return hashlib.sha256(json.dumps(_j(v),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _time(v,name):
 if v.tzinfo is None:raise MigrationPackError(f"{name} must be timezone-aware")
 return v.astimezone(timezone.utc)

@dataclass(frozen=True)
class ReviewRecord:
 review_id:str;proposal_id:str;proposal_hash:str;approval_pack_id:str;approval_pack_hash:str
 evidence_pack_hash:str;repository_commit:str;reviewer_identity:str;review_timestamp:datetime
 review_state:str;comments:str;supporting_reference:str;digital_signature_placeholder:str;schema_version:str=SCHEMA_VERSION
 @property
 def review_hash(self):return _hash({k:v for k,v in asdict(self).items() if k!="review_id"})
 def validate(self,pack:ApprovalPack):
  proposal=next((x for x in pack.proposals if x.proposal_id==self.proposal_id),None)
  if self.schema_version!=SCHEMA_VERSION or self.review_state not in {x.value for x in ReviewState}:raise MigrationPackError("review schema or state is invalid")
  if proposal is None or self.proposal_hash!=proposal.proposal_hash:raise MigrationPackError("proposal hash changed; review invalid")
  if self.approval_pack_id!=pack.pack_id or self.approval_pack_hash!=pack.pack_hash:raise MigrationPackError("approval pack changed; review invalid")
  if self.evidence_pack_hash!=pack.evidence_hash:raise MigrationPackError("evidence pack changed; review invalid")
  if self.repository_commit!=pack.repository_commit:raise MigrationPackError("repository version changed; review invalid")
  if not all((self.reviewer_identity,self.comments,self.supporting_reference,self.digital_signature_placeholder)):raise MigrationPackError("explicit review identity, rationale, reference, and signature placeholder are required")
  _time(self.review_timestamp,"review_timestamp");return self

def create_review(pack:ApprovalPack,proposal_id:str,*,reviewer_identity:str,review_timestamp:datetime,review_state:str,comments:str,supporting_reference:str,digital_signature_placeholder:str)->ReviewRecord:
 proposal=next((x for x in pack.proposals if x.proposal_id==proposal_id),None)
 if proposal is None:raise MigrationPackError("unknown proposal")
 material={"proposal":proposal.proposal_hash,"pack":pack.pack_hash,"reviewer":reviewer_identity,"time":_time(review_timestamp,"review_timestamp"),"state":review_state,"comments":comments,"reference":supporting_reference,"signature":digital_signature_placeholder}
 record=ReviewRecord("review-"+_hash(material)[:20],proposal_id,proposal.proposal_hash,pack.pack_id,pack.pack_hash,pack.evidence_hash,pack.repository_commit,reviewer_identity,review_timestamp,review_state,comments,supporting_reference,digital_signature_placeholder)
 return record.validate(pack)

def validate_review_history(pack:ApprovalPack,reviews:tuple[ReviewRecord,...]):
 ids=[x.review_id for x in reviews]
 if len(ids)!=len(set(ids)):raise MigrationPackError("duplicate review record")
 for review in reviews:review.validate(pack)
 return tuple(sorted(reviews,key=lambda x:(x.review_timestamp,x.review_id)))

@dataclass(frozen=True)
class ReviewExportBundle:
 bundle_id:str;schema_version:str;creation_timestamp:datetime;repository_commit:str;evidence_pack_hash:str
 approval_pack_id:str;approval_pack_hash:str;proposal_hashes:tuple[str,...];reviews:tuple[ReviewRecord,...];summary:tuple[tuple[str,int],...]
 @property
 def bundle_hash(self):return _hash({k:v for k,v in asdict(self).items() if k!="bundle_id"})
 def serialize(self):return json.dumps(_j({**asdict(self),"bundle_hash":self.bundle_hash}),sort_keys=True,separators=(",",":"))

def export_review_bundle(pack:ApprovalPack,reviews:tuple[ReviewRecord,...],*,created_at:datetime)->ReviewExportBundle:
 reviews=validate_review_history(pack,reviews);created_at=_time(created_at,"created_at")
 states=tuple((state.value,sum(x.review_state==state.value for x in reviews)) for state in ReviewState)
 material={"pack":pack.pack_hash,"reviews":tuple(x.review_hash for x in reviews),"time":created_at}
 return ReviewExportBundle("review-bundle-"+_hash(material)[:20],SCHEMA_VERSION,created_at,pack.repository_commit,pack.evidence_hash,pack.pack_id,pack.pack_hash,pack.proposal_hashes,reviews,states)

def decision_metrics(pack:ApprovalPack,reviews:tuple[ReviewRecord,...]):
 reviews=validate_review_history(pack,reviews);latest={}
 for review in reviews:latest[review.proposal_id]=review
 counts={state.value:sum(x.review_state==state.value for x in latest.values()) for state in ReviewState};counts["PENDING"]+=len(pack.proposals)-len(latest)
 unresolved={x.proposal_id for x in pack.proposals if x.proposal_id not in latest or latest[x.proposal_id].review_state!="APPROVED"}
 counts["CRITICAL_UNRESOLVED"]=sum(x.proposal_id in unresolved and x.materiality.severity=="CRITICAL" for x in pack.proposals)
 counts["HIGH_UNRESOLVED"]=sum(x.proposal_id in unresolved and x.materiality.severity=="HIGH" for x in pack.proposals)
 counts["APPROVAL_COMPLETENESS"]=0 if not pack.proposals else round(100*sum(x.review_state=="APPROVED" for x in latest.values())/len(pack.proposals),2)
 return counts
