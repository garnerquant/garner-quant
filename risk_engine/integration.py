from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from canonical_accounting.instruments import get_instrument_metadata
from dashboard.accounting_reader import load_dashboard_accounting_status
from risk_engine.models import OrderProposal, RiskContext, decimal_value, utc_datetime


def build_order_proposal(
    *,
    proposal_id,
    signal_id,
    symbol,
    side,
    quantity,
    source_bar_timestamp,
    reference_price,
    stop_price=None,
    reason,
    correlation_id,
    strategy_id="garner-strategy-v1",
    strategy_timestamp=None,
) -> OrderProposal:
    metadata = get_instrument_metadata(symbol)
    instant = strategy_timestamp or datetime.now(timezone.utc)
    return OrderProposal.create(
        proposal_id=str(proposal_id), strategy_id=str(strategy_id), signal_id=str(signal_id),
        symbol=str(symbol), market=metadata.exchange, side=str(side).upper(), quantity=quantity,
        order_type="MARKET", limit_price=None, stop_price=stop_price, time_in_force="DAY",
        strategy_timestamp=instant, source_bar_timestamp=source_bar_timestamp,
        expected_execution_currency=metadata.instrument_currency, reason=str(reason),
        correlation_id=str(correlation_id), metadata={"timeframe": "1d", "reference_price": str(reference_price)},
        created_at=instant,
    )


def _runtime_state(config_path, status_path):
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        config = {}
    try:
        status = json.loads(Path(status_path).read_text(encoding="utf-8"))
    except Exception:
        status = {}
    return config, status


def _canonical_state(state_root):
    status = load_dashboard_accounting_status(state_root)
    if status.bundle is None:
        return status, None, None, None, None, None, None, None, None
    bundle = status.bundle
    broker = bundle.broker.iloc[0] if len(bundle.broker) == 1 else None
    if broker is None:
        return status, None, None, None, None, None, None, None, None
    positions = {}
    quantities = {}
    market_exposure = {}
    currency_exposure = {}
    for _, row in bundle.holdings.iterrows():
        symbol = str(row.get("ticker", "")).strip()
        if not symbol:
            continue
        metadata = get_instrument_metadata(symbol)
        value = decimal_value(row.get("market_value"), f"holding {symbol} market value")
        quantity = decimal_value(row.get("quantity"), f"holding {symbol} quantity")
        positions[symbol] = value
        quantities[symbol] = quantity
        market_exposure[metadata.exchange] = market_exposure.get(metadata.exchange, Decimal("0")) + value
        currency_exposure[metadata.instrument_currency] = currency_exposure.get(metadata.instrument_currency, Decimal("0")) + value
    tracker = bundle.tracker.copy()
    if tracker.empty:
        daily_realised = daily_total = hwm = None
    else:
        tracker["_timestamp"] = pd.to_datetime(tracker["date"], errors="coerce", utc=True)
        tracker = tracker.dropna(subset=["_timestamp"]).sort_values("_timestamp")
        if tracker.empty:
            daily_realised = daily_total = hwm = None
        else:
            latest = tracker.iloc[-1]
            same_day = tracker[tracker["_timestamp"].dt.date.eq(latest["_timestamp"].date())]
            first = same_day.iloc[0]
            daily_realised = decimal_value(latest["realised_pnl"], "latest realised pnl") - decimal_value(first["realised_pnl"], "day-start realised pnl")
            daily_total = decimal_value(latest["portfolio_value"], "latest equity") - decimal_value(first["portfolio_value"], "day-start equity")
            hwm = max(decimal_value(value, "tracker equity") for value in tracker["portfolio_value"])
    return (
        status, broker, positions, quantities, market_exposure, currency_exposure,
        daily_realised, daily_total, hwm,
    )


def build_production_risk_context(
    proposal: OrderProposal,
    *,
    reference_price,
    reference_price_timestamp,
    fx_rate_to_base=None,
    fx_timestamp=None,
    runtime_config_path=Path("runtime/live_runtime_config.json"),
    runtime_status_path=Path("data/live_runtime_status.json"),
    accounting_state_root=Path("data/accounting_generations"),
    now=None,
    shadow_mode=False,
) -> RiskContext:
    instant = utc_datetime(now or datetime.now(timezone.utc), "now")
    config, runtime = _runtime_state(runtime_config_path, runtime_status_path)
    accounting, broker, positions, quantities, market_exposure, currency_exposure, daily_realised, daily_total, hwm = _canonical_state(accounting_state_root)
    manifest = accounting.bundle.manifest if accounting.bundle is not None else {}
    reconciliation = str(broker.get("reconciliation_status", "")) if broker is not None else ""
    return RiskContext(
        now=instant,
        runtime_mode=str(config.get("mode") or "unknown"),
        trading_enabled=config.get("paper_execution_enabled") is True,
        runtime_healthy=runtime.get("status") == "running" and runtime.get("last_error") in {None, ""},
        scheduler_healthy=bool(proposal.signal_id), adapter_ready=True,
        market_session_valid=bool(proposal.signal_id), source_bar_complete=True,
        reference_price=decimal_value(reference_price, "reference_price"),
        reference_price_timestamp=utc_datetime(reference_price_timestamp, "reference_price_timestamp"),
        fx_rate_to_base=decimal_value(fx_rate_to_base, "fx_rate_to_base") if fx_rate_to_base is not None else None,
        fx_timestamp=utc_datetime(fx_timestamp, "fx_timestamp") if fx_timestamp is not None else None,
        accounting_active=accounting.state == "active",
        accounting_verified=accounting.state == "active" and manifest.get("status") == "complete" and manifest.get("base_currency") == "GBP",
        accounting_generation_id=accounting.bundle.generation_id if accounting.bundle is not None else None,
        accounting_base_currency=str(manifest.get("base_currency")) if manifest else None,
        accounting_reconciled=reconciliation == "reconciled",
        cash_base=decimal_value(broker.get("cash"), "cash") if broker is not None else None,
        portfolio_equity_base=decimal_value(broker.get("portfolio_value"), "portfolio_value") if broker is not None else None,
        positions_base=positions, position_quantities=quantities, open_order_notional_base=Decimal("0") if positions is not None else None,
        daily_realised_pnl_base=daily_realised, daily_total_pnl_base=daily_total,
        equity_high_water_mark_base=hwm,
        strategy_exposure_base=None,
        market_exposure_base=market_exposure, currency_exposure_base=currency_exposure,
        estimated_fees_base=Decimal("0"), seen_proposal_ids=frozenset(), trace_id=proposal.correlation_id,
        shadow_mode=bool(shadow_mode),
    )
