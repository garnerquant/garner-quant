from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal

from canonical_accounting.events import AccountingEvent, AccountingEventError, AccountingEventType
from canonical_accounting.instruments import get_instrument_metadata


@dataclass(frozen=True)
class CanonicalLot:
    event_id: str
    strategy_id: str
    instrument: str
    quantity: Decimal
    base_cost_basis: Decimal
    native_unit_cost: Decimal
    currency: str
    entry_fx_rate: Decimal
    entry_fx_timestamp: str | None


@dataclass(frozen=True)
class CanonicalPosition:
    instrument: str
    strategy_ids: tuple[str, ...]
    quantity: Decimal
    base_cost_basis: Decimal
    base_market_value: Decimal
    base_unrealised_pnl: Decimal
    currency: str
    market: str
    valuation_price: Decimal
    valuation_timestamp: str
    fx_rate_to_base: Decimal
    fx_timestamp: str | None


@dataclass(frozen=True)
class StrategyExposure:
    strategy_id: str
    gross: Decimal
    net: Decimal
    long: Decimal
    short: Decimal
    cash_usage: Decimal
    position_count: int
    market_exposure: dict[str, Decimal]
    currency_exposure: dict[str, Decimal]


@dataclass(frozen=True)
class CanonicalPortfolioSnapshot:
    generation_id: str
    parent_generation: str | None
    valuation_timestamp: str
    last_accounting_event: str | None
    cash: Decimal
    positions: tuple[CanonicalPosition, ...]
    lots: tuple[CanonicalLot, ...]
    realised_pnl: Decimal
    unrealised_pnl: Decimal
    total_equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    currency_exposure: dict[str, Decimal]
    strategy_exposure: dict[str, StrategyExposure]
    external_cash_flow: Decimal
    fees: Decimal
    dividends: Decimal
    fx_effects: Decimal

    def to_dict(self):
        def convert(value):
            if isinstance(value, Decimal): return str(value)
            if isinstance(value, tuple): return [convert(item) for item in value]
            if isinstance(value, dict): return {str(key): convert(item) for key, item in value.items()}
            if hasattr(value, "__dataclass_fields__"): return convert(asdict(value))
            return value
        return convert(asdict(self))

    @classmethod
    def from_dict(cls, payload):
        positions = tuple(CanonicalPosition(**{**item, "strategy_ids": tuple(item["strategy_ids"]), **{k: Decimal(str(item[k])) for k in ("quantity", "base_cost_basis", "base_market_value", "base_unrealised_pnl", "valuation_price", "fx_rate_to_base")}}) for item in payload["positions"])
        lots = tuple(CanonicalLot(**{**item, **{k: Decimal(str(item[k])) for k in ("quantity", "base_cost_basis", "native_unit_cost", "entry_fx_rate")}}) for item in payload["lots"])
        strategies = {}
        for key, item in payload["strategy_exposure"].items():
            values = {**item}
            for name in ("gross", "net", "long", "short", "cash_usage"): values[name] = Decimal(str(values[name]))
            for name in ("market_exposure", "currency_exposure"): values[name] = {k: Decimal(str(v)) for k, v in values[name].items()}
            strategies[key] = StrategyExposure(**values)
        scalar = {name: Decimal(str(payload[name])) for name in ("cash", "realised_pnl", "unrealised_pnl", "total_equity", "gross_exposure", "net_exposure", "external_cash_flow", "fees", "dividends", "fx_effects")}
        return cls(**{**payload, **scalar, "positions": positions, "lots": lots,
                      "currency_exposure": {k: Decimal(str(v)) for k, v in payload["currency_exposure"].items()},
                      "strategy_exposure": strategies})


def replay_events(events: list[AccountingEvent], *, generation_id: str, parent_generation=None,
                  valuations=None, valuation_timestamp=None) -> CanonicalPortfolioSnapshot:
    valuations = dict(valuations or {})
    queues = defaultdict(deque)
    cash = realised = external = fees = dividends = fx_effects = Decimal("0")
    latest_fx = {}
    ordered = sorted(events, key=lambda item: (item.timestamp, item.event_id))
    seen = set()
    for event in ordered:
        event.validate()
        if event.event_id in seen: raise AccountingEventError("duplicate accounting event ID")
        seen.add(event.event_id)
        rate = event.fx_rate_to_base
        native = event.amount * rate
        kind = event.event_type
        if kind is AccountingEventType.DEPOSIT:
            cash += native; external += native
        elif kind is AccountingEventType.WITHDRAWAL:
            if native > cash: raise AccountingEventError("withdrawal exceeds cash")
            cash -= native; external -= native
        elif kind is AccountingEventType.FEE:
            if native > cash: raise AccountingEventError("fee exceeds cash")
            cash -= native; fees += native
        elif kind is AccountingEventType.DIVIDEND:
            cash += native; dividends += native
        elif kind is AccountingEventType.BUY_FILL:
            metadata = get_instrument_metadata(event.instrument)
            cost = event.amount * metadata.price_scale * event.quantity * rate
            if cost > cash: raise AccountingEventError("buy fill exceeds cash")
            cash -= cost
            queues[(event.strategy_id, event.instrument)].append(CanonicalLot(event.event_id, event.strategy_id, event.instrument,
                event.quantity, cost, event.amount * metadata.price_scale, event.currency, rate,
                event.fx_timestamp.isoformat() if event.fx_timestamp else event.timestamp.isoformat()))
        elif kind is AccountingEventType.SELL_FILL:
            metadata = get_instrument_metadata(event.instrument)
            remaining = event.quantity; proceeds_total = event.amount * metadata.price_scale * event.quantity * rate
            while remaining > 0:
                key = (event.strategy_id, event.instrument)
                if not queues[key]: raise AccountingEventError("sell fill exceeds strategy open quantity")
                lot = queues[key][0]; matched = min(remaining, lot.quantity)
                cost = lot.base_cost_basis * matched / lot.quantity
                proceeds = proceeds_total * matched / event.quantity
                realised += proceeds - cost
                left = lot.quantity - matched
                if left == 0: queues[key].popleft()
                else: queues[key][0] = CanonicalLot(lot.event_id, lot.strategy_id, lot.instrument,
                    left, lot.base_cost_basis - cost, lot.native_unit_cost, lot.currency,
                    lot.entry_fx_rate, lot.entry_fx_timestamp)
                remaining -= matched
            cash += proceeds_total
        elif kind is AccountingEventType.FX_ADJUSTMENT:
            previous = latest_fx.get(event.currency)
            latest_fx[event.currency] = event.amount
            if previous is not None:
                native_value = sum(lot.quantity * lot.native_unit_cost for queue in queues.values() for lot in queue if lot.currency == event.currency)
                fx_effects += native_value * (event.amount - previous)
        elif kind is AccountingEventType.CORPORATE_ACTION:
            factor = event.amount
            matching = [key for key in queues if key[1] == event.instrument]
            if not matching: raise AccountingEventError("corporate action has no open position")
            for key in matching:
                queues[key] = deque(CanonicalLot(lot.event_id, lot.strategy_id, lot.instrument,
                    lot.quantity * factor, lot.base_cost_basis, lot.native_unit_cost / factor,
                    lot.currency, lot.entry_fx_rate, lot.entry_fx_timestamp) for lot in queues[key])

    lots = tuple(lot for key in sorted(queues) for lot in queues[key])
    timestamp = valuation_timestamp or (ordered[-1].timestamp if ordered else datetime.now(timezone.utc))
    if isinstance(timestamp, str): timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if timestamp.tzinfo is None: raise AccountingEventError("valuation timestamp must be timezone-aware")
    positions = []
    strategy_values = defaultdict(lambda: {"gross": Decimal("0"), "net": Decimal("0"), "long": Decimal("0"), "short": Decimal("0"), "cash_usage": Decimal("0"), "symbols": set(), "market": defaultdict(Decimal), "currency": defaultdict(Decimal)})
    currency_values = defaultdict(Decimal)
    symbols = sorted({key[1] for key in queues})
    for symbol in symbols:
        symbol_lots = [lot for key, queue in queues.items() if key[1] == symbol for lot in queue]
        quantity = sum((lot.quantity for lot in symbol_lots), Decimal("0"))
        if quantity == 0:
            continue
        cost = sum((lot.base_cost_basis for lot in symbol_lots), Decimal("0"))
        if symbol not in valuations: raise AccountingEventError(f"missing valuation for {symbol}")
        valuation = valuations[symbol]; price = Decimal(str(valuation["price"])); rate = Decimal(str(valuation.get("fx_rate_to_base", "1")))
        if price <= 0 or rate <= 0: raise AccountingEventError("valuation price and FX must be positive")
        metadata = get_instrument_metadata(symbol)
        market_value = quantity * price * metadata.price_scale * rate
        fx_time = str(valuation.get("fx_timestamp") or timestamp.isoformat())
        positions.append(CanonicalPosition(symbol, tuple(sorted({lot.strategy_id for lot in symbol_lots})), quantity, cost, market_value, market_value-cost,
            metadata.instrument_currency, metadata.exchange, price, timestamp.astimezone(timezone.utc).isoformat(), rate, fx_time))
        currency_values[metadata.instrument_currency] += market_value
        for lot in symbol_lots:
            allocated = market_value * lot.quantity / quantity
            state = strategy_values[lot.strategy_id]; state["gross"] += abs(allocated); state["net"] += allocated
            state["long"] += max(allocated, Decimal("0")); state["short"] += min(allocated, Decimal("0"))
            state["cash_usage"] += lot.base_cost_basis; state["symbols"].add(symbol)
            state["market"][metadata.exchange] += allocated; state["currency"][metadata.instrument_currency] += allocated
    gross = sum((abs(item.base_market_value) for item in positions), Decimal("0")); net = sum((item.base_market_value for item in positions), Decimal("0"))
    unrealised = sum((item.base_unrealised_pnl for item in positions), Decimal("0"))
    strategies = {key: StrategyExposure(key, value["gross"], value["net"], value["long"], value["short"], value["cash_usage"], len(value["symbols"]), dict(value["market"]), dict(value["currency"])) for key, value in strategy_values.items()}
    return CanonicalPortfolioSnapshot(generation_id, parent_generation, timestamp.astimezone(timezone.utc).isoformat(),
        ordered[-1].event_id if ordered else None, cash, tuple(positions), lots, realised, unrealised,
        cash + net, gross, net, dict(currency_values), strategies, external, fees, dividends, fx_effects)


def snapshot_json(snapshot):
    return json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"))
