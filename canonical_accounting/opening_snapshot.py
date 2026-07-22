from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any

from canonical_accounting.currency import canonical_currency
from canonical_accounting.observation import REPLAY_METADATA
from canonical_accounting.instruments import get_instrument_metadata
from risk_engine.configuration import load_risk_configuration

SCHEMA_VERSION="1.0"; MANIFEST_VERSION="1.0"; RECONCILIATION_VERSION="1.0"
ALLOWED_AUTHORITY=frozenset({"AUTHORITATIVE"}); INELIGIBLE_AUTHORITY=frozenset({"DERIVED","REPAIR_ONLY","MIGRATION_ONLY","TEST_ONLY","UNSUPPORTED","CORROBORATING"})

class OpeningSnapshotError(ValueError): pass
class DifferenceClass(str,Enum):
    EXACT="EXACT";ROUNDING="ROUNDING";TIMING="TIMING";FX="FX";SOURCE_LIMITATION="SOURCE_LIMITATION";LEGACY_LIMITATION="LEGACY_LIMITATION";MIGRATION_ADJUSTMENT="MIGRATION_ADJUSTMENT";ATTRIBUTION_GAP="ATTRIBUTION_GAP";BUG="BUG";UNKNOWN="UNKNOWN"

def _d(value,name,negative=False):
    try:r=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:raise OpeningSnapshotError(f"{name} is invalid") from exc
    if not r.is_finite() or (not negative and r<0):raise OpeningSnapshotError(f"{name} is invalid")
    return r
def _t(value,name):
    try:r=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception as exc:raise OpeningSnapshotError(f"{name} is invalid") from exc
    if r.tzinfo is None:raise OpeningSnapshotError(f"{name} must be timezone-aware")
    return r.astimezone(timezone.utc)
def _j(value):
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,Enum):return value.value
    if isinstance(value,tuple):return [_j(item) for item in value]
    if isinstance(value,dict):return {str(k):_j(v) for k,v in value.items()}
    if hasattr(value,"__dataclass_fields__"):return _j(asdict(value))
    return value
def _ser(value):return json.dumps(_j(value),sort_keys=True,separators=(",",":"))
def _hash(value):return hashlib.sha256(_ser(value).encode()).hexdigest()

@dataclass(frozen=True)
class SourceManifestEntry:
    logical_name:str;classification:str;identifier:str;schema_version:str;size:int;row_count:int
    modification_timestamp:datetime;content_hash:str;earliest_timestamp:datetime;latest_timestamp:datetime
    complete_through_cutoff:bool;source_authority:str;writer_identity:str;extraction_timestamp:datetime
    def validate(self,cutoff):
        if self.classification not in ALLOWED_AUTHORITY:raise OpeningSnapshotError(f"source is not authoritative: {self.logical_name}")
        if not all((self.logical_name,self.identifier,self.schema_version,self.content_hash,self.source_authority,self.writer_identity)):raise OpeningSnapshotError("source manifest identity is incomplete")
        if self.size<0 or self.row_count<0 or not self.complete_through_cutoff:raise OpeningSnapshotError("source is incomplete through cut-off")
        for name in ("modification_timestamp","earliest_timestamp","latest_timestamp","extraction_timestamp"):_t(getattr(self,name),name)
        if self.latest_timestamp>cutoff:raise OpeningSnapshotError("source contains post-cut-off records")
        return self

@dataclass(frozen=True)
class SourceManifest:
    manifest_id:str;schema_version:str;cut_off_timestamp:datetime;entries:tuple[SourceManifestEntry,...]
    @property
    def manifest_hash(self):return _hash({"manifest_id":self.manifest_id,"schema_version":self.schema_version,"cut_off_timestamp":self.cut_off_timestamp,"entries":tuple(sorted(self.entries,key=lambda x:x.logical_name))})
    def validate(self):
        if self.schema_version!=MANIFEST_VERSION or not self.entries:raise OpeningSnapshotError("source manifest schema or content is invalid")
        cutoff=_t(self.cut_off_timestamp,"cut_off_timestamp");names=[x.logical_name for x in self.entries]
        if len(names)!=len(set(names)):raise OpeningSnapshotError("duplicate source manifest identity")
        for entry in self.entries:entry.validate(cutoff)
        return self

@dataclass(frozen=True)
class CutOffContract:
    cut_off_timestamp:datetime;cut_off_timezone:str;boundary_type:str;market_session_identity:str;scheduler_bar_identity:str
    source_as_of:tuple[tuple[str,str],...];valuation_timestamp:datetime;fx_timestamp_policy:str;configuration_version:str
    instrument_registry_version:str;strategy_registry_version:str;source_manifest_hash:str
    def validate(self):
        cutoff=_t(self.cut_off_timestamp,"cut_off_timestamp");valuation=_t(self.valuation_timestamp,"valuation_timestamp")
        if self.boundary_type not in {"INTRADAY","END_OF_DAY","END_OF_MARKET_SESSION","ADMINISTRATIVE"}:raise OpeningSnapshotError("cut-off boundary type is invalid")
        if valuation>cutoff or not all((self.cut_off_timezone,self.market_session_identity,self.fx_timestamp_policy,self.instrument_registry_version,self.strategy_registry_version,self.source_manifest_hash)):raise OpeningSnapshotError("cut-off contract is incomplete")
        if self.configuration_version!=load_risk_configuration().configuration_version:raise OpeningSnapshotError("unknown configuration version")
        return self

@dataclass(frozen=True)
class OpeningCash:
    currency:str;settled:Decimal;restricted:Decimal;unsettled:Decimal;base_equivalent:Decimal;fx_rate:Decimal;fx_timestamp:datetime;fx_source:str;quote_convention:str;source_reference:str
@dataclass(frozen=True)
class OpeningLot:
    lot_id:str;strategy_id:str;instrument_id:str;symbol:str;open_timestamp:datetime;quantity:Decimal;remaining_quantity:Decimal
    native_unit_cost:Decimal;native_total_cost:Decimal;fees_allocated:Decimal;base_cost:Decimal;acquisition_fx_rate:Decimal
    acquisition_fx_timestamp:datetime;acquisition_fx_source:str;source_reference:str;migration_classification:str="NONE"
@dataclass(frozen=True)
class OpeningPosition:
    position_id:str;strategy_id:str;instrument_id:str;symbol:str;market:str;venue:str;asset_class:str;currency:str
    quantity:Decimal;settled_quantity:Decimal;unsettled_quantity:Decimal;price_units:str;quantity_precision:int;price_precision:int
    valuation_price:Decimal;valuation_timestamp:datetime;valuation_source:str;valuation_fx_rate:Decimal;fx_timestamp:datetime;fx_source:str
    native_market_value:Decimal;base_market_value:Decimal;base_cost:Decimal;unrealised_pnl:Decimal;source_reference:str
@dataclass(frozen=True)
class PnlCarryForward:
    strategy_id:str;instrument_id:str;currency:str;realised_trading:Decimal;unrealised:Decimal;fees:Decimal;dividends:Decimal
    taxes_withholding:Decimal;deposits:Decimal;withdrawals:Decimal;realised_fx:Decimal;valuation_fx:Decimal;migration_adjustment:Decimal;unknown_historical_pnl:Decimal;source_reference:str

@dataclass(frozen=True)
class OpeningSnapshotCandidate:
    candidate_id:str;schema_version:str;creation_timestamp:datetime;cut_off:CutOffContract;configuration_version:str
    source_manifest_id:str;source_manifest_hash:str;lifecycle_status:str;validation_status:str;reconciliation_status:str
    approval_status:str;active:bool;production_pointer_eligible:bool;cash:tuple[OpeningCash,...];positions:tuple[OpeningPosition,...]
    lots:tuple[OpeningLot,...];pnl:tuple[PnlCarryForward,...];metadata_versions:tuple[tuple[str,str],...]
    evidence:tuple[tuple[str,str],...];exceptions:tuple[str,...];unresolved_items:tuple[str,...]
    strategy_attribution_coverage:Decimal;fx_evidence_coverage:Decimal
    def payload(self):return {key:value for key,value in asdict(self).items()}
    @property
    def candidate_hash(self):return _hash(self.payload())
    def serialize(self):self.validate();return _ser(self.payload())
    def validate(self):
        if self.schema_version!=SCHEMA_VERSION or self.active or self.production_pointer_eligible:raise OpeningSnapshotError("candidate must be inactive and pointer-ineligible")
        if self.configuration_version!=load_risk_configuration().configuration_version:raise OpeningSnapshotError("unknown configuration version")
        self.cut_off.validate();ids=[]
        for cash in self.cash:
            canonical_currency(cash.currency);[_d(getattr(cash,n),n) for n in ("settled","restricted","unsettled","base_equivalent","fx_rate")];_t(cash.fx_timestamp,"fx_timestamp")
            if cash.currency!="GBP" and not cash.fx_source:raise OpeningSnapshotError("foreign cash FX evidence is missing")
            if cash.fx_timestamp>self.cut_off.cut_off_timestamp or (cash.currency!="GBP" and self.cut_off.cut_off_timestamp-cash.fx_timestamp>timedelta(hours=3)):raise OpeningSnapshotError("cash FX evidence is future-dated or stale")
            if cash.currency=="GBP" and (cash.fx_rate!=1 or cash.quote_convention!="GBP_PER_GBP"):raise OpeningSnapshotError("GBP identity policy is invalid")
        lot_totals={}
        lot_costs={}
        for lot in self.lots:
            ids.append(lot.lot_id);[_d(getattr(lot,n),n) for n in ("quantity","remaining_quantity","native_unit_cost","native_total_cost","fees_allocated","base_cost","acquisition_fx_rate")]
            if lot.remaining_quantity>lot.quantity or not lot.strategy_id or not lot.source_reference:raise OpeningSnapshotError("FIFO lot evidence is invalid")
            if lot.open_timestamp>self.cut_off.cut_off_timestamp:raise OpeningSnapshotError("post-cut-off lot is forbidden")
            if not lot.acquisition_fx_source or lot.acquisition_fx_timestamp>lot.open_timestamp or lot.acquisition_fx_rate<=0:raise OpeningSnapshotError("acquisition FX evidence is invalid")
            if lot.base_cost!=lot.native_total_cost*lot.acquisition_fx_rate+lot.fees_allocated:raise OpeningSnapshotError("FIFO lot cost basis does not reconcile")
            if lot.migration_classification not in {"NONE","EXPLICIT_OPENING_MIGRATION"}:raise OpeningSnapshotError("lot migration classification is invalid")
            lot_totals[(lot.strategy_id,lot.symbol)]=lot_totals.get((lot.strategy_id,lot.symbol),Decimal("0"))+lot.remaining_quantity
            lot_costs[(lot.strategy_id,lot.symbol)]=lot_costs.get((lot.strategy_id,lot.symbol),Decimal("0"))+lot.base_cost
        for pos in self.positions:
            ids.append(pos.position_id);policy=REPLAY_METADATA.get(pos.symbol)
            if policy is None or policy.instrument_id!=pos.instrument_id:raise OpeningSnapshotError("position instrument identity is invalid")
            instrument=get_instrument_metadata(pos.symbol)
            if pos.price_units!=instrument.provider_price_unit or pos.currency!=instrument.instrument_currency:raise OpeningSnapshotError("position currency or price-unit metadata is invalid")
            if pos.currency=="GBp":raise OpeningSnapshotError("GBp is a price unit, not currency")
            if not pos.strategy_id:raise OpeningSnapshotError("unattributed position blocks candidate")
            if lot_totals.get((pos.strategy_id,pos.symbol),Decimal("0"))!=pos.quantity:raise OpeningSnapshotError("FIFO quantity does not reconcile to position")
            if lot_costs.get((pos.strategy_id,pos.symbol),Decimal("0"))!=pos.base_cost:raise OpeningSnapshotError("FIFO cost does not reconcile to position")
            if pos.base_market_value-pos.base_cost!=pos.unrealised_pnl:raise OpeningSnapshotError("position unrealised P&L does not reconcile")
            if pos.native_market_value!=pos.quantity*pos.valuation_price*instrument.price_scale:raise OpeningSnapshotError("native market value does not apply authoritative price scale")
            if pos.valuation_timestamp>self.cut_off.cut_off_timestamp:raise OpeningSnapshotError("post-cut-off valuation is forbidden")
            if not pos.fx_source or pos.fx_timestamp>self.cut_off.cut_off_timestamp:raise OpeningSnapshotError("valuation FX evidence is invalid")
            if pos.currency!="GBP" and self.cut_off.cut_off_timestamp-pos.fx_timestamp>timedelta(hours=3):raise OpeningSnapshotError("foreign valuation FX evidence is stale")
        if len(ids)!=len(set(ids)):raise OpeningSnapshotError("duplicate candidate IDs")
        if any(item.unknown_historical_pnl!=0 for item in self.pnl) and not self.unresolved_items:raise OpeningSnapshotError("unknown historical P&L must remain unresolved")
        if not Decimal("0")<=self.strategy_attribution_coverage<=Decimal("100") or not Decimal("0")<=self.fx_evidence_coverage<=Decimal("100"):raise OpeningSnapshotError("coverage is invalid")
        return self

@dataclass(frozen=True)
class ReconciliationDifference:
    metric:str;scope:str;legacy_value:Decimal;candidate_value:Decimal;absolute_difference:Decimal;percentage_difference:Decimal
    currency:str;severity:str;classification:str;source_evidence:str;explanation:str;blocking:bool
@dataclass(frozen=True)
class ReconciliationReport:
    report_id:str;schema_version:str;candidate_id:str;candidate_hash:str;differences:tuple[ReconciliationDifference,...];created_at:datetime
    @property
    def reconciliation_hash(self):return _hash(self)
    @property
    def blocking(self):return any(item.blocking for item in self.differences)
    @property
    def largest_difference(self):return max((item.absolute_difference for item in self.differences),default=Decimal("0"))

def reconcile_candidate(candidate,expected,tolerance=Decimal("0.01"),classifications=None):
    classifications=classifications or {}
    actual={"cash_base":sum((x.base_equivalent for x in candidate.cash),Decimal("0")),"positions_base":sum((x.base_market_value for x in candidate.positions),Decimal("0")),"lot_cost_base":sum((x.base_cost for x in candidate.lots),Decimal("0")),"lot_quantity":sum((x.remaining_quantity for x in candidate.lots),Decimal("0")),"realised_pnl":sum((x.realised_trading for x in candidate.pnl),Decimal("0")),"unrealised_pnl":sum((x.unrealised_pnl for x in candidate.positions),Decimal("0")),"fees":sum((x.fees for x in candidate.pnl),Decimal("0")),"dividends":sum((x.dividends for x in candidate.pnl),Decimal("0")),"taxes_withholding":sum((x.taxes_withholding for x in candidate.pnl),Decimal("0")),"deposits":sum((x.deposits for x in candidate.pnl),Decimal("0")),"withdrawals":sum((x.withdrawals for x in candidate.pnl),Decimal("0"))}
    actual["gross_exposure"]=sum((abs(x.base_market_value) for x in candidate.positions),Decimal("0"));actual["net_exposure"]=sum((x.base_market_value for x in candidate.positions),Decimal("0"))
    for position in candidate.positions:
        actual[f"position:{position.symbol}"]=actual.get(f"position:{position.symbol}",Decimal("0"))+position.quantity
        actual[f"strategy_exposure:{position.strategy_id}"]=actual.get(f"strategy_exposure:{position.strategy_id}",Decimal("0"))+position.base_market_value
    actual["equity"]=actual["cash_base"]+actual["positions_base"]
    rows=[]
    for metric in sorted(set(expected)|set(actual)):
        legacy=_d(expected.get(metric,0),metric,negative=True);value=_d(actual.get(metric,0),metric,negative=True);delta=abs(value-legacy);pct=Decimal("0") if legacy==0 and delta==0 else Decimal("100") if legacy==0 else delta/abs(legacy)*100
        classification=DifferenceClass.EXACT.value if delta==0 else DifferenceClass.ROUNDING.value if delta<=tolerance else classifications.get(metric,DifferenceClass.UNKNOWN.value)
        if classification not in {item.value for item in DifferenceClass}:raise OpeningSnapshotError("unknown reconciliation classification")
        rows.append(ReconciliationDifference(metric,"PORTFOLIO",legacy,value,delta,pct,"GBP","INFO" if delta<=tolerance else "ERROR",classification,"explicit reconciliation fixture",classification+" comparison",delta>tolerance))
    return ReconciliationReport("recon-"+candidate.candidate_id,RECONCILIATION_VERSION,candidate.candidate_id,candidate.candidate_hash,tuple(rows),candidate.creation_timestamp)

@dataclass(frozen=True)
class OpeningApprovalRecord:
    approval_id:str;candidate_id:str;approver_identity:str;role:str;approval_timestamp:datetime;candidate_hash:str
    reconciliation_hash:str;decision:str;comments:str;exception_acknowledgements:tuple[str,...];expiry_timestamp:datetime|None
    def validate(self,candidate,reconciliation):
        if self.decision not in {"APPROVED_FOR_REPLAY_TESTING","REJECTED","CHANGES_REQUIRED"}:raise OpeningSnapshotError("approval decision is not permitted")
        if self.candidate_id!=candidate.candidate_id or self.candidate_hash!=candidate.candidate_hash or self.reconciliation_hash!=reconciliation.reconciliation_hash:raise OpeningSnapshotError("approval does not bind to candidate and reconciliation")
        _t(self.approval_timestamp,"approval_timestamp")
        return self

def build_candidate(*,manifest,cut_off,cash,positions,lots,pnl,created_at,exceptions=(),unresolved=()):
    manifest.validate();cut_off.validate()
    if cut_off.source_manifest_hash!=manifest.manifest_hash:raise OpeningSnapshotError("cut-off and manifest hashes differ")
    material={"manifest":manifest.manifest_hash,"cutoff":cut_off,"cash":cash,"positions":positions,"lots":lots,"pnl":pnl}
    candidate_id="opening-"+_hash(material)[:24]
    attributed=sum((p.quantity for p in positions if p.strategy_id),Decimal("0"));total=sum((p.quantity for p in positions),Decimal("0"));coverage=Decimal("100") if total==0 else attributed/total*100
    fx_items=len(cash)+len(lots)+len(positions);fx_valid=sum(bool(getattr(x,"fx_source",None) or getattr(x,"acquisition_fx_source",None)) for x in (*cash,*lots,*positions));fx_coverage=Decimal("100") if fx_items==0 else Decimal(fx_valid)/Decimal(fx_items)*100
    candidate=OpeningSnapshotCandidate(candidate_id,SCHEMA_VERSION,_t(created_at,"creation_timestamp"),cut_off,cut_off.configuration_version,
        manifest.manifest_id,manifest.manifest_hash,"FROZEN_INACTIVE","VALIDATED","PENDING_RECONCILIATION","UNAPPROVED",False,False,
        tuple(cash),tuple(positions),tuple(lots),tuple(pnl),(("instrument","1"),("currency","1"),("strategy","unapproved"),("calendar","exchange-calendars"),("replay","1.0")),
        (("source_manifest",manifest.manifest_hash),),(tuple(exceptions)),tuple(unresolved),coverage,fx_coverage)
    return candidate.validate()

def readiness(candidate,reconciliation,approval=None):
    blockers=["canonical accounting inactive","no sustained replay evidence"]
    if candidate.strategy_attribution_coverage<100:blockers.append("unresolved strategy attribution")
    if candidate.fx_evidence_coverage<100:blockers.append("incomplete FX evidence")
    if reconciliation.blocking:blockers.append("unreconciled material differences")
    if candidate.unresolved_items:blockers.append("unresolved candidate items")
    if approval is None:blockers.append("missing approval")
    return {"status":"NOT_READY","blockers":blockers}

def freeze_inactive_candidate(candidate,reconciliation,destination,approval=None):
    candidate.validate()
    if reconciliation.candidate_hash!=candidate.candidate_hash or reconciliation.blocking:raise OpeningSnapshotError("invalid or unreconciled candidate cannot be frozen")
    if approval is not None:approval.validate(candidate,reconciliation)
    root=Path(destination);target=root/candidate.candidate_id
    if target.exists():raise OpeningSnapshotError("inactive candidate artifact is immutable")
    target.mkdir(parents=True)
    files={"candidate.json":{**candidate.payload(),"candidate_hash":candidate.candidate_hash},"reconciliation.json":{**_j(reconciliation),"reconciliation_hash":reconciliation.reconciliation_hash}}
    if approval is not None:files["approval.json"]=_j(approval)
    for name,payload in files.items():
        path=target/name
        with path.open("x",encoding="utf-8",newline="\n") as handle:handle.write(json.dumps(_j(payload),sort_keys=True,indent=2));handle.flush();os.fsync(handle.fileno())
    return target
