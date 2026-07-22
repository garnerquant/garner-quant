"""Immutable, read-only migration allocation and approval governance contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from canonical_accounting.evidence_pack import OpeningSnapshotEvidencePack

SCHEMA_VERSION = "1.0"


class MigrationPackError(ValueError): pass


class ProposalType(str, Enum):
    STRATEGY_ALLOCATION="STRATEGY_ALLOCATION";OPENING_LOT="OPENING_LOT";OPENING_CASH="OPENING_CASH"
    FX_ACQUISITION="FX_ACQUISITION";DIVIDEND_HISTORY="DIVIDEND_HISTORY";FEE_HISTORY="FEE_HISTORY"
    TAX_HISTORY="TAX_HISTORY";WITHHOLDING="WITHHOLDING";CORPORATE_ACTION="CORPORATE_ACTION";UNKNOWN="UNKNOWN"


class ApprovalState(str, Enum):
    PENDING="PENDING";APPROVED="APPROVED";REJECTED="REJECTED";CHANGES_REQUIRED="CHANGES_REQUIRED"


def _json(value):
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,datetime):return value.astimezone(timezone.utc).isoformat()
    if isinstance(value,Enum):return value.value
    if isinstance(value,tuple):return [_json(x) for x in value]
    if isinstance(value,dict):return {str(k):_json(v) for k,v in value.items()}
    if hasattr(value,"__dataclass_fields__"):return _json(asdict(value))
    return value


def _hash(value):return hashlib.sha256(json.dumps(_json(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _aware(value,name):
    if value.tzinfo is None:raise MigrationPackError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Materiality:
    estimated_value_affected:Decimal;portfolio_percent:Decimal;strategy_percent:Decimal|None;currency:str;severity:str


@dataclass(frozen=True)
class MigrationProposal:
    proposal_id:str;proposal_type:str;created_timestamp:datetime;linked_gap_ids:tuple[str,...]
    affected_positions:tuple[str,...];affected_cash:Decimal;affected_lots:tuple[str,...]
    affected_currency:str|None;affected_strategy:str|None;evidence_summary:str;known_limitations:tuple[str,...]
    recommended_action:str;operator_required:bool;materiality:Materiality;allocation_outcome:str
    approval_state:str=ApprovalState.PENDING.value
    @property
    def proposal_hash(self):return _hash({k:v for k,v in asdict(self).items() if k!="proposal_id"})
    def validate(self,gap_ids):
        if self.proposal_type not in {x.value for x in ProposalType}:raise MigrationPackError("unknown proposal type")
        if self.approval_state not in {x.value for x in ApprovalState}:raise MigrationPackError("unknown approval state")
        if not self.linked_gap_ids or not set(self.linked_gap_ids)<=set(gap_ids):raise MigrationPackError("proposal must link existing gaps")
        if self.allocation_outcome not in {"PROVEN","MANUAL_REQUIRED","UNRESOLVED"}:raise MigrationPackError("invalid allocation outcome")
        if self.allocation_outcome!="PROVEN" and self.affected_strategy is not None:raise MigrationPackError("unproven strategy cannot be allocated")
        _aware(self.created_timestamp,"created_timestamp")
        return self


@dataclass(frozen=True)
class ApprovalPack:
    pack_id:str;schema_version:str;creation_timestamp:datetime;repository_commit:str;evidence_hash:str
    proposals:tuple[MigrationProposal,...];coverage:Decimal;remaining_blockers:tuple[str,...];readiness:str
    @property
    def proposal_hashes(self):return tuple(x.proposal_hash for x in self.proposals)
    @property
    def summary(self):
        return {state:sum(x.approval_state==state for x in self.proposals) for state in ("PENDING","APPROVED","REJECTED","CHANGES_REQUIRED")}
    @property
    def pack_hash(self):return _hash({"pack_id":self.pack_id,"schema_version":self.schema_version,"creation_timestamp":self.creation_timestamp,"repository_commit":self.repository_commit,"evidence_hash":self.evidence_hash,"proposal_hashes":self.proposal_hashes,"coverage":self.coverage,"remaining_blockers":self.remaining_blockers,"readiness":self.readiness})
    def validate(self,gap_ids):
        if self.schema_version!=SCHEMA_VERSION or self.readiness!="NOT_READY" or not self.repository_commit or not self.evidence_hash:raise MigrationPackError("approval pack is incomplete or unsafe")
        ids=[x.proposal_id for x in self.proposals]
        if len(ids)!=len(set(ids)):raise MigrationPackError("duplicate proposal identity")
        for proposal in self.proposals:proposal.validate(gap_ids)
        return self


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id:str;pack_id:str;pack_hash:str;proposal_id:str;proposal_hash:str;state:str
    operator_identity:str;created_timestamp:datetime;comments:str
    def validate(self,pack):
        proposal=next((x for x in pack.proposals if x.proposal_id==self.proposal_id),None)
        if self.state not in {x.value for x in ApprovalState} or proposal is None:raise MigrationPackError("approval record is invalid")
        if self.pack_id!=pack.pack_id or self.pack_hash!=pack.pack_hash or self.proposal_hash!=proposal.proposal_hash:raise MigrationPackError("approval record binding is stale or invalid")
        if not self.operator_identity:raise MigrationPackError("operator identity is required")
        _aware(self.created_timestamp,"created_timestamp");return self


def _materiality(value,total,currency="GBP"):
    value=Decimal(value or 0);pct=Decimal("0") if total<=0 else (abs(value)/total*100).quantize(Decimal("0.01"))
    severity="CRITICAL" if pct>=25 else "HIGH" if pct>=10 else "MEDIUM" if pct>=2 else "LOW"
    return Materiality(value,pct,None,currency,severity)


def build_migration_approval_pack(evidence:OpeningSnapshotEvidencePack,*,repository_commit:str,created_at:datetime)->ApprovalPack:
    """Convert existing gaps to proposals; never re-audit or persist anything."""
    created_at=_aware(created_at,"created_at");gaps={x.category:x for x in evidence.gaps};gap_ids={x.gap_id for x in evidence.gaps}
    total=evidence.unattributed_exposure+evidence.unattributed_cash;rows=[]
    def add(kind,gap,positions=(),cash=Decimal("0"),lots=(),currency=None,summary="",limits=(),action="Obtain authoritative evidence and submit for explicit operator review",outcome="UNRESOLVED",value=Decimal("0")):
        material={"type":kind,"gap":gap.gap_id,"positions":positions,"summary":summary}
        proposal=MigrationProposal("proposal-"+_hash(material)[:20],kind,created_at,(gap.gap_id,),tuple(positions),cash,tuple(lots),currency,None,summary,tuple(limits),action,True,_materiality(value,total,currency or "GBP"),outcome)
        rows.append(proposal.validate(gap_ids))
    if "STRATEGY_ATTRIBUTION" in gaps:
        gap=gaps["STRATEGY_ATTRIBUTION"]
        for position in evidence.positions:add("STRATEGY_ALLOCATION",gap,(position.symbol,),summary="No authoritative historical strategy linkage is present",limits=("Strategy ownership must not be inferred",),outcome="MANUAL_REQUIRED",value=position.market_value or 0,currency=position.currency)
    if "POSITION_RECONCILIATION" in gaps:
        gap=gaps["POSITION_RECONCILIATION"]
        for symbol in gap.affected_positions:
            pos=next(x for x in evidence.positions if x.symbol==symbol)
            add("OPENING_LOT",gap,(symbol,),lots=tuple(x.source_event_id for x in evidence.lots if x.symbol==symbol),currency=pos.currency,summary=f"Proposed migration-lot review for {symbol}; quantity {pos.quantity}; cost evidence: {pos.cost_basis_evidence}; valuation: {pos.valuation_evidence}",limits=("This is not a lot","Historical FIFO is not proven"),value=pos.market_value or 0)
    if "ACQUISITION_FX" in gaps:
        gap=gaps["ACQUISITION_FX"]
        for fx in evidence.fx:
            if fx.currency!="GBP":
                pos=next(x for x in evidence.positions if x.symbol==fx.symbol)
                add("FX_ACQUISITION",gap,(fx.symbol,),currency=fx.currency,summary="Historical acquisition FX is unavailable",limits=("Affected P&L cannot be quantified without FX evidence",),action="Obtain broker contract note or verified timestamped FX archive",value=pos.market_value or 0)
    if "CASH_PROVENANCE" in gaps:
        gap=gaps["CASH_PROVENANCE"]
        for label in ("DEPOSIT","WITHDRAWAL"):
            add("OPENING_CASH",gap,cash=evidence.unattributed_cash,currency="GBP",summary=f"{label} history is not authoritatively evidenced",limits=("No cash movement is inferred from balances",),value=evidence.unattributed_cash)
    if "NON_FILL_HISTORY" in gaps:
        gap=gaps["NON_FILL_HISTORY"]
        mapping=(("DIVIDEND","DIVIDEND_HISTORY"),("FEE","FEE_HISTORY"),("TAX_WITHHOLDING","TAX_HISTORY"),("TAX_WITHHOLDING","WITHHOLDING"),("CORPORATE_ACTION","CORPORATE_ACTION"),("FX_ADJUSTMENT","UNKNOWN"))
        for category,kind in mapping:
            item=next(x for x in evidence.non_fill if x.category==category)
            add(kind,gap,positions=gap.affected_positions,summary=f"Missing {category} history",limits=(item.limitation,"No values are inferred"),value=gap.affected_value or 0)
    proposals=tuple(sorted(rows,key=lambda x:x.proposal_id));blockers=tuple(sorted(x.category for x in evidence.gaps))
    material={"evidence":evidence.pack_hash,"commit":repository_commit,"proposals":tuple(x.proposal_hash for x in proposals)}
    pack=ApprovalPack("migration-pack-"+_hash(material)[:20],SCHEMA_VERSION,created_at,repository_commit,evidence.pack_hash,proposals,evidence.coverage.overall,blockers,"NOT_READY")
    return pack.validate(gap_ids)
