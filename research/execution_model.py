"""Simplified deterministic research execution model; not a broker emulator."""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar, StrategyDecision


@dataclass(frozen=True, slots=True)
class FeePolicy:
    model_id: str
    rate: Decimal


@dataclass(frozen=True, slots=True)
class SlippagePolicy:
    model_id: str
    basis_points: Decimal


@dataclass(frozen=True, slots=True)
class FillResult:
    order_id: str
    model_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    decision_timestamp: object
    eligible_execution_timestamp: object
    fill_timestamp: object | None
    reference_price: Decimal | None
    slippage: Decimal
    fill_price: Decimal | None
    gross_notional: Decimal
    fee: Decimal
    net_cash_impact: Decimal
    status: str
    reason: str
    source_bar_id: str | None
    warnings: tuple[str, ...] = ("no partial fills", "no market impact", "no broker acknowledgement")

    def canonical_sha256(self):
        raw = json.dumps({"order": self.order_id, "model": self.model_id, "instrument": self.instrument_id, "side": self.side, "quantity": str(self.quantity), "status": self.status, "reason": self.reason, "fill": None if self.fill_price is None else str(self.fill_price), "fee": str(self.fee), "source": self.source_bar_id}, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def _validate_costs(fee_policy, slippage_policy):
    if not fee_policy.model_id or fee_policy.rate < 0 or not fee_policy.rate.is_finite(): raise ValueError("invalid fee policy")
    if not slippage_policy.model_id or slippage_policy.basis_points < 0 or not slippage_policy.basis_points.is_finite(): raise ValueError("invalid slippage policy")


def _quantity(quantity, precision):
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0: raise ValueError("quantity must be positive Decimal")
    if -quantity.as_tuple().exponent > precision: raise ValueError("quantity exceeds precision policy")


def _eligible(bar):
    return bar.bar_status is BarStatus.COMPLETED and bar.quality_status is DataQualityStatus.VALID


def simulate_next_bar_entry(*, decision: StrategyDecision, decision_bar: NormalizedMarketBar, next_bar: NormalizedMarketBar | None, quantity: Decimal, quantity_precision: int, fee_policy: FeePolicy, slippage_policy: SlippagePolicy) -> FillResult:
    _validate_costs(fee_policy, slippage_policy); _quantity(quantity, quantity_precision)
    if next_bar is None: return FillResult(decision.decision_id, "completed_bar_next_open_v1", decision.instrument_id, "BUY", quantity, decision.decision_timestamp_utc, decision.eligible_execution_timestamp_utc, None, None, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), "unfilled", "next eligible bar missing", None)
    if next_bar.bar_start_utc < decision_bar.bar_end_utc or not _eligible(next_bar): raise ValueError("next fill bar must be later, completed and valid")
    reference = next_bar.open_price; slippage = reference * slippage_policy.basis_points / Decimal("10000"); fill = reference + slippage; gross = fill * quantity; fee = gross * fee_policy.rate
    return FillResult(decision.decision_id, "completed_bar_next_open_v1", decision.instrument_id, "BUY", quantity, decision.decision_timestamp_utc, decision.eligible_execution_timestamp_utc, next_bar.bar_start_utc, reference, slippage, fill, gross, fee, -(gross + fee), "filled", "next eligible bar open", next_bar.source_record_id)


def simulate_long_exit(*, order_id: str, instrument_id: str, quantity: Decimal, decision_timestamp, position_bar: NormalizedMarketBar, bar: NormalizedMarketBar, stop_price: Decimal, target_price: Decimal, fee_policy: FeePolicy, slippage_policy: SlippagePolicy) -> FillResult:
    _validate_costs(fee_policy, slippage_policy); _quantity(quantity, 8 if instrument_id in {"BTC-GBP", "ETH-GBP"} else 0)
    if not _eligible(bar): raise ValueError("exit bar is not eligible")
    if bar.bar_start_utc < position_bar.bar_end_utc: raise ValueError("exit cannot occur before the entry bar ends")
    stop_crossed, target_crossed = bar.low_price <= stop_price, bar.high_price >= target_price
    if stop_crossed and target_crossed: return FillResult(order_id, "completed_bar_next_open_v1", instrument_id, "SELL", quantity, decision_timestamp, bar.bar_start_utc, None, None, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), "rejected", "ambiguous stop and target ordering", bar.source_record_id)
    if not stop_crossed and not target_crossed: return FillResult(order_id, "completed_bar_next_open_v1", instrument_id, "SELL", quantity, decision_timestamp, bar.bar_start_utc, None, None, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), "no_exit", "neither stop nor target crossed", bar.source_record_id)
    level = stop_price if stop_crossed else target_price
    gap = bar.open_price <= stop_price if stop_crossed else bar.open_price >= target_price
    reference = bar.open_price if gap else level
    slippage = reference * slippage_policy.basis_points / Decimal("10000"); fill = reference - slippage; gross = fill * quantity; fee = gross * fee_policy.rate
    return FillResult(order_id, "completed_bar_next_open_v1", instrument_id, "SELL", quantity, decision_timestamp, bar.bar_start_utc, bar.bar_start_utc, reference, slippage, fill, gross, fee, gross - fee, "filled", "stop" if stop_crossed else "target", bar.source_record_id)
