from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from canonical_accounting.currency import canonical_currency
from canonical_accounting.events import AccountingEventType
from canonical_accounting.observation import AccountingObservationError, SCHEMA_VERSION
from risk_engine.configuration import load_risk_configuration


class NonFillEventType(str, Enum):
    DEPOSIT="DEPOSIT"; WITHDRAWAL="WITHDRAWAL"; DIVIDEND="DIVIDEND"; FEE="FEE"
    FX_ADJUSTMENT="FX_ADJUSTMENT"; CORPORATE_ACTION="CORPORATE_ACTION"


class FxAdjustmentKind(str, Enum):
    REALISED_CONVERSION="REALISED_CONVERSION"; VALUATION_ONLY="VALUATION_ONLY"


class CorporateActionKind(str, Enum):
    STOCK_SPLIT="STOCK_SPLIT"; REVERSE_SPLIT="REVERSE_SPLIT"; SYMBOL_CHANGE="SYMBOL_CHANGE"
    MERGER="MERGER"; SPIN_OFF="SPIN_OFF"; RETURN_OF_CAPITAL="RETURN_OF_CAPITAL"
    STOCK_DIVIDEND="STOCK_DIVIDEND"; DELISTING="DELISTING"; OTHER_UNSUPPORTED="OTHER_UNSUPPORTED"


FEE_CATEGORIES=frozenset({"CUSTODY","PLATFORM","MARKET_DATA","FINANCING","TAX","REGULATORY","ACCOUNT"})


def _decimal(value,name,*,allow_zero=True):
    try: result=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc: raise AccountingObservationError(f"{name} is invalid") from exc
    if not result.is_finite() or (result < 0 if allow_zero else result <= 0): raise AccountingObservationError(f"{name} is invalid")
    return result


def _utc(value,name):
    try: result=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (TypeError,ValueError) as exc: raise AccountingObservationError(f"{name} is invalid") from exc
    if result.tzinfo is None: raise AccountingObservationError(f"{name} must be timezone-aware")
    return result.astimezone(timezone.utc)


def _metadata(value):
    if value is None: return ()
    if not isinstance(value,dict): raise AccountingObservationError("supporting_metadata must be a dictionary")
    rows=[]
    for key,item in sorted(value.items()):
        if not str(key).strip() or isinstance(item,(dict,list,set)): raise AccountingObservationError("supporting metadata must contain scalar named values")
        rows.append((str(key),str(item)))
    return tuple(rows)


@dataclass(frozen=True)
class NonFillEventRequest:
    source_event_id: str; event_type: NonFillEventType; producer_id: str; producer_version: str
    source_system: str; source_reference: str; authority_method: str; correlation_id: str
    strategy_id: str; instrument_id: str; symbol: str; native_currency: str; base_currency: str
    amount: Decimal; quantity: Decimal; effective_timestamp: datetime; source_timestamp: datetime
    received_timestamp: datetime; valuation_timestamp: datetime; fx_rate_to_base: Decimal | None
    fx_timestamp: datetime | None; fx_source: str; reason: str; description: str
    supporting_metadata: tuple[tuple[str,str],...]; configuration_version: str; runtime_mode: str
    monitor_only: bool; schema_version: str=SCHEMA_VERSION; withholding_tax: Decimal=Decimal("0")
    net_amount: Decimal | None=None; fee_category: str=""; attribution_policy: str=""
    related_event_id: str=""; fill_linked: bool=False; fx_adjustment_kind: str=""
    from_currency: str=""; to_currency: str=""; from_amount: Decimal=Decimal("0")
    to_amount: Decimal=Decimal("0"); executed_fx_rate: Decimal=Decimal("0"); rate_convention: str=""; corporate_action_kind: str=""
    destination_instrument_id: str=""; destination_symbol: str=""; action_ratio: Decimal=Decimal("0")

    @classmethod
    def create(cls, **values):
        data=dict(values)
        try: data["event_type"]=NonFillEventType(data["event_type"])
        except Exception as exc: raise AccountingObservationError("unsupported non-fill event type") from exc
        for name,default in (("amount",0),("quantity",0),("withholding_tax",0),("from_amount",0),("to_amount",0),("executed_fx_rate",0),("action_ratio",0)):
            data[name]=_decimal(data.get(name,default),name)
        if data.get("net_amount") is not None: data["net_amount"]=_decimal(data["net_amount"],"net_amount")
        if data.get("fx_rate_to_base") is not None: data["fx_rate_to_base"]=_decimal(data["fx_rate_to_base"],"fx_rate_to_base",allow_zero=False)
        for name in ("effective_timestamp","source_timestamp","received_timestamp","valuation_timestamp"):
            data[name]=_utc(data.get(name),name)
        if data.get("fx_timestamp") is not None: data["fx_timestamp"]=_utc(data["fx_timestamp"],"fx_timestamp")
        data["supporting_metadata"]=_metadata(data.get("supporting_metadata"))
        request=cls(**data); request.validate(); return request

    @property
    def metadata(self): return dict(self.supporting_metadata)

    def validate(self):
        required=(self.source_event_id,self.producer_id,self.producer_version,self.source_system,self.source_reference,
                  self.authority_method,self.correlation_id,self.strategy_id,self.instrument_id,self.symbol,
                  self.native_currency,self.base_currency,self.reason,self.description,self.configuration_version)
        if any(not str(value).strip() for value in required): raise AccountingObservationError("required non-fill source authority field is missing")
        if self.schema_version!=SCHEMA_VERSION: raise AccountingObservationError("unknown request schema version")
        if self.runtime_mode!="monitor_only" or self.monitor_only is not True: raise AccountingObservationError("non-fill producers are monitor-only")
        if self.configuration_version!=load_risk_configuration().configuration_version: raise AccountingObservationError("unknown configuration version")
        canonical_currency(self.native_currency); canonical_currency(self.base_currency)
        if self.base_currency!="GBP": raise AccountingObservationError("base currency must be GBP")
        if self.native_currency=="GBP":
            if self.fx_rate_to_base not in {None,Decimal("1")}: raise AccountingObservationError("GBP identity FX must equal one")
        elif self.fx_rate_to_base is None or self.fx_timestamp is None or not self.fx_source.strip():
            raise AccountingObservationError("foreign currency requires complete FX evidence")
        if self.event_type in {NonFillEventType.DEPOSIT,NonFillEventType.WITHDRAWAL}:
            if self.amount<=0 or self.quantity!=0: raise AccountingObservationError("cash flow uses a positive absolute amount and zero quantity")
            if self.metadata.get("derived_from_balance","false").lower()=="true": raise AccountingObservationError("balance-inferred cash flows are forbidden")
        elif self.event_type is NonFillEventType.DIVIDEND:
            if self.amount<=0 or self.quantity!=0 or self.net_amount is None: raise AccountingObservationError("dividend gross/net amounts are required")
            if self.net_amount+self.withholding_tax!=self.amount: raise AccountingObservationError("dividend net plus withholding must equal gross")
            if not self.metadata.get("entitlement_reference") or self.attribution_policy not in {"STRATEGY","EXPLICIT_ALLOCATION"}: raise AccountingObservationError("dividend entitlement and attribution are required")
        elif self.event_type is NonFillEventType.FEE:
            if self.amount<=0 or self.quantity!=0 or self.fee_category not in FEE_CATEGORIES: raise AccountingObservationError("standalone fee category/amount is invalid")
            if self.fill_linked or self.metadata.get("already_in_fill","false").lower()=="true": raise AccountingObservationError("fill-linked fee cannot be duplicated")
            if self.attribution_policy not in {"PORTFOLIO","STRATEGY"}: raise AccountingObservationError("fee attribution policy is required")
        elif self.event_type is NonFillEventType.FX_ADJUSTMENT:
            try: kind=FxAdjustmentKind(self.fx_adjustment_kind)
            except Exception as exc: raise AccountingObservationError("FX adjustment classification is required") from exc
            if not self.from_currency or not self.to_currency or self.from_currency==self.to_currency or self.rate_convention!="TO_PER_FROM": raise AccountingObservationError("explicit TO_PER_FROM currency direction is required")
            canonical_currency(self.from_currency); canonical_currency(self.to_currency)
            if self.fx_rate_to_base is None or self.fx_timestamp is None or not self.fx_source: raise AccountingObservationError("FX evidence is required")
            if kind is FxAdjustmentKind.REALISED_CONVERSION:
                if self.from_amount<=0 or self.to_amount<=0 or self.executed_fx_rate<=0 or abs(self.from_amount*self.executed_fx_rate-self.to_amount)>Decimal("0.000001"): raise AccountingObservationError("realised FX amounts do not reconcile to quoted direction")
            elif self.from_amount!=0 or self.to_amount!=0: raise AccountingObservationError("valuation-only FX has no cash amounts")
        elif self.event_type is NonFillEventType.CORPORATE_ACTION:
            try: kind=CorporateActionKind(self.corporate_action_kind)
            except Exception as exc: raise AccountingObservationError("corporate action subtype is required") from exc
            if kind is CorporateActionKind.OTHER_UNSUPPORTED: raise AccountingObservationError("unsupported corporate action subtype")
            if kind in {CorporateActionKind.STOCK_SPLIT,CorporateActionKind.REVERSE_SPLIT,CorporateActionKind.STOCK_DIVIDEND} and self.action_ratio<=0: raise AccountingObservationError("corporate action ratio is required")
            if kind is CorporateActionKind.SYMBOL_CHANGE and (not self.destination_instrument_id or not self.destination_symbol): raise AccountingObservationError("symbol change destination is required")
            if kind in {CorporateActionKind.MERGER,CorporateActionKind.SPIN_OFF} and (not self.destination_instrument_id or not self.destination_symbol or self.action_ratio<=0): raise AccountingObservationError("merger/spin-off terms are incomplete")
            if kind is CorporateActionKind.RETURN_OF_CAPITAL and self.amount<=0: raise AccountingObservationError("return of capital amount is required")
        return self

    def to_dict(self):
        def value(item:Any):
            if isinstance(item,Decimal): return str(item)
            if isinstance(item,datetime): return item.isoformat()
            if isinstance(item,Enum): return item.value
            if isinstance(item,tuple): return [value(part) for part in item]
            return item
        return {key:value(item) for key,item in asdict(self).items()}

    def serialize(self): self.validate(); return json.dumps(self.to_dict(),sort_keys=True,separators=(",",":"))
    @property
    def request_hash(self): return hashlib.sha256(self.serialize().encode()).hexdigest()
