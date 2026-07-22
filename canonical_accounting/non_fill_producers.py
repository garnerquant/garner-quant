from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import timezone
from decimal import Decimal

from canonical_accounting.instruments import get_instrument_metadata
from canonical_accounting.non_fill_events import (
    CorporateActionKind, FxAdjustmentKind, NonFillEventRequest, NonFillEventType,
)
from canonical_accounting.observation import (
    AccountingObservationEnvelope, AccountingObservationError, AccountingObservationStore,
    REPLAY_METADATA, SCHEMA_VERSION,
)


@dataclass(frozen=True)
class ProducerDefinition:
    producer_id: str; version: str; supported_types: tuple[str,...]; authority: str
    invocation: str="internal_only"; production_source_available: bool=False


PRODUCER_REGISTRY={
    "controlled-non-fill-import": ProducerDefinition(
        "controlled-non-fill-import","1.0",tuple(item.value for item in NonFillEventType),
        "explicit authorised source record supplied by an internal caller",
    )
}


def producer_framework_status():
    supported=sorted({kind for producer in PRODUCER_REGISTRY.values() for kind in producer.supported_types})
    active=[item.producer_id for item in PRODUCER_REGISTRY.values() if item.production_source_available]
    return {"status":"AVAILABLE_INTERNAL_ONLY","supported_event_types":supported,"active_production_producers":active,
            "unavailable_producers":supported if not active else [],"source_authority":"EXPLICIT_REQUIRED"}


def _instrument_payload(request):
    policy=REPLAY_METADATA.get(request.symbol)
    if policy is None or policy.instrument_id!=request.instrument_id: raise AccountingObservationError("instrument is absent from authoritative replay policy")
    payload={key:(str(value) if isinstance(value,Decimal) else value) for key,value in asdict(policy).items()}
    try:
        metadata=get_instrument_metadata(request.symbol)
        payload.update({"metadata_source":metadata.metadata_source,"price_scale":str(metadata.price_scale),
                        "provider":metadata.provider,"provider_symbol":metadata.provider_symbol,"listing_unit":metadata.listing_unit})
        return metadata,payload
    except KeyError:
        if not request.symbol.endswith("-CASH"): raise
        payload.update({"metadata_source":"internal cash-balance replay policy v1","price_scale":"1",
                        "provider":"internal","provider_symbol":request.symbol,"listing_unit":request.native_currency})
        return None,payload


def _cash_impact(request,fx):
    kind=request.event_type
    if kind is NonFillEventType.DEPOSIT: return request.amount*fx
    if kind is NonFillEventType.WITHDRAWAL: return -request.amount*fx
    if kind is NonFillEventType.DIVIDEND: return request.net_amount*fx
    if kind is NonFillEventType.FEE: return -request.amount*fx
    if kind is NonFillEventType.CORPORATE_ACTION and request.corporate_action_kind==CorporateActionKind.RETURN_OF_CAPITAL.value: return request.amount*fx
    return Decimal("0")


def build_non_fill_envelope(request:NonFillEventRequest):
    request.validate()
    producer=PRODUCER_REGISTRY.get(request.producer_id)
    if producer is None or producer.version!=request.producer_version or request.event_type.value not in producer.supported_types:
        raise AccountingObservationError("producer identity/version is not registered for this event type")
    metadata,payload=_instrument_payload(request)
    if request.destination_symbol:
        destination=REPLAY_METADATA.get(request.destination_symbol)
        if destination is None or destination.instrument_id!=request.destination_instrument_id:
            raise AccountingObservationError("destination instrument is absent from authoritative replay policy")
    fx=Decimal("1") if request.native_currency=="GBP" else request.fx_rate_to_base
    fx_timestamp=request.fx_timestamp or request.valuation_timestamp
    event_id="nfe_"+hashlib.sha256(f"{request.producer_id}|{request.source_event_id}".encode()).hexdigest()[:24]
    price_units=metadata.provider_price_unit if metadata is not None else request.native_currency
    amount_for_envelope=request.action_ratio if request.event_type is NonFillEventType.CORPORATE_ACTION else request.amount
    if request.event_type is NonFillEventType.FX_ADJUSTMENT and amount_for_envelope==0: amount_for_envelope=fx
    withholding=request.withholding_tax*fx
    fee=request.amount*fx if request.event_type is NonFillEventType.FEE else Decimal("0")
    observation={"producer_id":request.producer_id,"producer_version":request.producer_version,
                 "source_system":request.source_system,"source_reference":request.source_reference,
                 "authority_method":request.authority_method,"source_event_id":request.source_event_id,
                 "correlation_id":request.correlation_id,"request_hash":request.request_hash,
                 "reason":request.reason,"description":request.description,"supporting_metadata":dict(request.supporting_metadata),
                 "effective_timestamp":request.effective_timestamp.isoformat(),"source_timestamp":request.source_timestamp.isoformat(),
                 "received_timestamp":request.received_timestamp.isoformat(),"withholding_tax_base":str(withholding),
                 "fee_category":request.fee_category,"attribution_policy":request.attribution_policy,
                 "related_event_id":request.related_event_id,"fx_adjustment_kind":request.fx_adjustment_kind,
                 "from_currency":request.from_currency,"to_currency":request.to_currency,
                 "from_amount":str(request.from_amount),"to_amount":str(request.to_amount),"executed_fx_rate":str(request.executed_fx_rate),"rate_convention":request.rate_convention,
                 "corporate_action_kind":request.corporate_action_kind,"destination_instrument_id":request.destination_instrument_id,
                 "destination_symbol":request.destination_symbol,"action_ratio":str(request.action_ratio),
                 "performance_classification":"EXTERNAL_FLOW" if request.event_type in {NonFillEventType.DEPOSIT,NonFillEventType.WITHDRAWAL} else "PERFORMANCE" if request.event_type in {NonFillEventType.DIVIDEND,NonFillEventType.FEE} else "NON_CASH_DIAGNOSTIC"}
    return AccountingObservationEnvelope(
        schema_version=SCHEMA_VERSION,event_id=event_id,proposal_id=f"non-fill:{request.source_event_id}",decision_id=f"observation:{event_id}",
        strategy_id=request.strategy_id,strategy_version=request.strategy_id,instrument_id=request.instrument_id,symbol=request.symbol,
        market=metadata.exchange if metadata is not None else "CASH",venue=metadata.exchange if metadata is not None else "INTERNAL",
        asset_class=metadata.asset_class if metadata is not None else "Cash",side="NONE",event_type=request.event_type.value,
        quantity=Decimal("0"),native_price=amount_for_envelope,price_units=price_units,native_currency=request.native_currency,
        base_currency=request.base_currency,fx_rate_to_base=fx,fx_timestamp=fx_timestamp,fx_source=request.fx_source or "GBP identity",
        market_data_timestamp=request.source_timestamp,valuation_timestamp=request.valuation_timestamp,
        planned_execution_timestamp=request.effective_timestamp,fees_base=fee,estimated_costs_base=withholding,
        cash_impact_base=_cash_impact(request,fx),position_impact=Decimal("0"),expected_exposure={"status":"NOT_CALCULATED_NON_FILL"},
        risk_decision={"status":"NOT_APPLICABLE","reason":"observational non-fill source event"},
        configuration_version=request.configuration_version,accounting_generation_version="INACTIVE",
        scheduler_bar={"identity":f"non-fill:{request.source_event_id}","timestamp":request.source_timestamp.isoformat()},
        runtime_mode=request.runtime_mode,monitor_only=request.monitor_only,created_at=request.received_timestamp,
        instrument_metadata=payload,observation_metadata=observation,
    ).validate()


def observe_non_fill_event(request:NonFillEventRequest,*,store=None):
    target=store or AccountingObservationStore()
    try:
        envelope=build_non_fill_envelope(request); appended=target.append(envelope)
        return {"status":"VALID","appended":appended,"event_id":envelope.event_id,"envelope_hash":envelope.envelope_hash,"envelope":envelope}
    except Exception as exc:
        target.append_invalid(source_event_id=getattr(request,"source_event_id","UNKNOWN"),event_type=getattr(request,"event_type","UNKNOWN"),
                              producer_id=getattr(request,"producer_id","UNKNOWN"),reason=exc,received_timestamp=getattr(request,"received_timestamp",None))
        raise AccountingObservationError(f"non-fill observation rejected: {exc}") from exc
