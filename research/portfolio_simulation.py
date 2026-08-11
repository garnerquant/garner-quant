"""Pure current-equity research portfolio sizing, valuation and metrics."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import hashlib
import json

from data.fx import FxObservation, convert_currency
from data.instrument_metadata import InstrumentMetadata, price_to_major_unit


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    instrument_id: str
    quantity: Decimal
    cost_basis_gbp: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioState:
    schema_version: int
    simulation_id: str
    timestamp: object
    base_currency: str
    cash_gbp: Decimal
    positions: tuple[PortfolioPosition, ...]
    realized_pnl_gbp: Decimal
    unrealized_pnl_gbp: Decimal
    total_equity_gbp: Decimal
    gross_exposure_gbp: Decimal
    warnings: tuple[str, ...] = ()

    def canonical_sha256(self):
        raw = json.dumps({"simulation": self.simulation_id, "timestamp": str(self.timestamp), "cash": str(self.cash_gbp), "equity": str(self.total_equity_gbp), "positions": [[p.instrument_id, str(p.quantity), str(p.cost_basis_gbp)] for p in self.positions]}, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class SizingResult:
    instrument_id: str
    current_equity_gbp: Decimal
    target_weight: Decimal
    target_notional_gbp: Decimal
    quantity: Decimal
    price_gbp: Decimal
    fee_gbp: Decimal
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class QuantitativeMetrics:
    cumulative_return: Decimal
    running_peak: Decimal
    drawdown: Decimal
    maximum_drawdown: Decimal
    realized_pnl_gbp: Decimal
    unrealized_pnl_gbp: Decimal
    fees_gbp: Decimal
    turnover_gbp: Decimal
    benchmark_cumulative_return: Decimal | None
    arithmetic_excess_return: Decimal | None


def _floor_quantity(value: Decimal, precision: int) -> Decimal:
    quantum = Decimal("1") if precision == 0 else Decimal("1e-" + str(precision))
    return value.quantize(quantum, rounding=ROUND_DOWN)


def value_in_gbp(*, price: Decimal, metadata: InstrumentMetadata, fx_observation: FxObservation | None, information_cutoff) -> Decimal:
    native_major = price_to_major_unit(price, metadata)
    if metadata.listing_currency == "GBP": return native_major
    if fx_observation is None: raise ValueError("eligible FX is required for foreign valuation")
    return convert_currency(native_major, metadata.listing_currency, "GBP", observation=fx_observation, information_cutoff_utc=information_cutoff)


def size_target(*, state: PortfolioState, instrument_id: str, target_weight: Decimal, price: Decimal, metadata: InstrumentMetadata, available_cash_gbp: Decimal, information_cutoff, fx_observation: FxObservation | None = None, fee_rate: Decimal = Decimal("0")) -> SizingResult:
    if not target_weight.is_finite() or target_weight < 0 or target_weight > 1: raise ValueError("target weight must be between zero and one")
    if fee_rate < 0 or not fee_rate.is_finite(): raise ValueError("invalid fee rate")
    price_gbp = value_in_gbp(price=price, metadata=metadata, fx_observation=fx_observation, information_cutoff=information_cutoff)
    target_notional = state.total_equity_gbp * target_weight
    precision = metadata.quantity_precision
    quantity = _floor_quantity(target_notional / price_gbp, precision)
    affordable = _floor_quantity(available_cash_gbp / (price_gbp * (Decimal("1") + fee_rate)), precision)
    quantity = min(quantity, affordable)
    fee = quantity * price_gbp * fee_rate
    status = "sized" if quantity > 0 else "no_trade"
    return SizingResult(instrument_id, state.total_equity_gbp, target_weight, target_notional, quantity, price_gbp, fee, status, "current-equity basis" if quantity > 0 else "zero affordable quantity")


def mark_to_market(*, state: PortfolioState, prices: dict[str, Decimal], metadata: dict[str, InstrumentMetadata], fx_by_currency: dict[str, FxObservation], information_cutoff) -> PortfolioState:
    values = []
    for position in state.positions:
        value = value_in_gbp(price=prices[position.instrument_id], metadata=metadata[position.instrument_id], fx_observation=fx_by_currency.get(metadata[position.instrument_id].listing_currency), information_cutoff=information_cutoff) * position.quantity
        values.append(value)
    total = state.cash_gbp + sum(values, Decimal("0"))
    return PortfolioState(state.schema_version, state.simulation_id, state.timestamp, state.base_currency, state.cash_gbp, state.positions, state.realized_pnl_gbp, total - sum(p.cost_basis_gbp for p in state.positions), total, sum(values, Decimal("0")), state.warnings)


def calculate_metrics(*, equity_series: tuple[Decimal, ...], realized_pnl_gbp: Decimal, unrealized_pnl_gbp: Decimal, fees_gbp: Decimal, turnover_gbp: Decimal, benchmark_cumulative_return: Decimal | None = None) -> QuantitativeMetrics:
    if not equity_series or equity_series[0] <= 0: raise ValueError("positive equity series required")
    peak = equity_series[0]; max_dd = Decimal("0")
    for equity in equity_series:
        if equity > peak: peak = equity
        drawdown = equity / peak - Decimal("1")
        if drawdown < max_dd: max_dd = drawdown
    cumulative = equity_series[-1] / equity_series[0] - Decimal("1")
    return QuantitativeMetrics(cumulative, peak, equity_series[-1] / peak - Decimal("1"), max_dd, realized_pnl_gbp, unrealized_pnl_gbp, fees_gbp, turnover_gbp, benchmark_cumulative_return, None if benchmark_cumulative_return is None else cumulative - benchmark_cumulative_return)
