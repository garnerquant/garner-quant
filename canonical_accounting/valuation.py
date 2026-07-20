from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from canonical_accounting.currency import (
    ConversionResult, FxQuote, InstrumentMetadata, base_market_value, decimal_value,
)


@dataclass(frozen=True)
class PositionValuation:
    symbol: str
    quantity: Decimal
    native_market_value: Decimal
    base_market_value: Decimal
    base_cost_basis: Decimal
    base_unrealised_pnl: Decimal
    fx_rate_to_base: Decimal
    fx_timestamp: datetime
    fx_source: str


def value_position(
    *, symbol: str, quantity, raw_price, metadata: InstrumentMetadata,
    base_cost_basis, quote: FxQuote | None, as_of: datetime,
    max_age: timedelta, future_tolerance: timedelta,
) -> PositionValuation:
    conversion = base_market_value(
        quantity, raw_price, metadata, quote=quote, as_of=as_of,
        max_age=max_age, future_tolerance=future_tolerance,
    )
    cost = decimal_value(base_cost_basis, "base_cost_basis")
    if cost < 0:
        raise ValueError("base_cost_basis must not be negative")
    return PositionValuation(
        symbol=symbol, quantity=decimal_value(quantity, "quantity"),
        native_market_value=conversion.source_amount,
        base_market_value=conversion.converted_amount, base_cost_basis=cost,
        base_unrealised_pnl=conversion.converted_amount - cost,
        fx_rate_to_base=conversion.fx_rate, fx_timestamp=conversion.fx_timestamp,
        fx_source=conversion.fx_source,
    )


def portfolio_totals(base_cash, positions: list[PositionValuation]) -> dict:
    cash = decimal_value(base_cash, "base_cash")
    values = sum((position.base_market_value for position in positions), Decimal("0"))
    costs = sum((position.base_cost_basis for position in positions), Decimal("0"))
    return {
        "base_cash": cash,
        "base_positions_value": values,
        "base_total_equity": cash + values,
        "base_open_cost_basis": costs,
        "base_unrealised_pnl": values - costs,
    }
