"""Explicit corporate-action transformations for raw execution research."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json

from data.fx import FxObservation, convert_currency
from data.point_in_time import CorporateAction, CorporateActionType


@dataclass(frozen=True, slots=True)
class ResearchPosition:
    instrument_id: str
    quantity: Decimal
    cost_basis: Decimal
    currency: str
    asset_class: str
    quantity_precision: int


@dataclass(frozen=True, slots=True)
class CorporateActionResult:
    action_id: str
    instrument_id: str
    status: str
    pre_position: ResearchPosition
    post_position: ResearchPosition | None
    cash_movement: Decimal
    cash_currency: str
    fx_observation_id: str | None
    unresolved_conditions: tuple[str, ...]
    reason: str

    def canonical_sha256(self):
        raw = json.dumps({"action_id": self.action_id, "instrument_id": self.instrument_id, "status": self.status, "pre": self.pre_position.__dict__ if hasattr(self.pre_position, "__dict__") else [self.pre_position.instrument_id, str(self.pre_position.quantity), str(self.pre_position.cost_basis)], "post": None if self.post_position is None else [self.post_position.instrument_id, str(self.post_position.quantity), str(self.post_position.cost_basis)], "cash": str(self.cash_movement), "currency": self.cash_currency, "fx": self.fx_observation_id, "unresolved": list(self.unresolved_conditions), "reason": self.reason}, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def apply_corporate_action(*, position: ResearchPosition, action: CorporateAction, research_price_basis: str, as_of_date: date, fx_observation: FxObservation | None = None, terminal_value: Decimal | None = None, terminal_currency: str | None = None) -> CorporateActionResult:
    if as_of_date < action.effective_date:
        return CorporateActionResult(action.action_id, position.instrument_id, "not_yet_effective", position, position, Decimal("0"), position.currency, None, (), "action not yet effective")
    if research_price_basis == "adjusted_total_return_research" and action.action_type in {CorporateActionType.STOCK_SPLIT, CorporateActionType.REVERSE_SPLIT, CorporateActionType.CASH_DIVIDEND}:
        return CorporateActionResult(action.action_id, position.instrument_id, "rejected", position, None, Decimal("0"), position.currency, None, ("adjusted_price_double_count_risk",), "adjusted prices must not receive the action again")
    if research_price_basis != "raw_execution_with_actions": raise ValueError("unsupported research price basis")
    if action.action_type in {CorporateActionType.STOCK_SPLIT, CorporateActionType.REVERSE_SPLIT}:
        quantity = position.quantity * action.ratio
        if position.asset_class in {"equity", "ETF"} and quantity != quantity.to_integral_value():
            return CorporateActionResult(action.action_id, position.instrument_id, "rejected", position, None, Decimal("0"), position.currency, None, ("fractional_entitlement_requires_cash_in_lieu",), "fractional equity entitlement is unresolved")
        if -quantity.as_tuple().exponent > position.quantity_precision: raise ValueError("quantity exceeds precision policy")
        return CorporateActionResult(action.action_id, position.instrument_id, "applied", position, ResearchPosition(position.instrument_id, quantity, position.cost_basis / action.ratio, position.currency, position.asset_class, position.quantity_precision), Decimal("0"), position.currency, None, (), "split applied")
    if action.action_type is CorporateActionType.CASH_DIVIDEND:
        if action.cash_amount is None or not action.currency: raise ValueError("cash dividend requires amount and currency")
        amount = action.cash_amount * position.quantity
        if action.currency != position.currency:
            if fx_observation is None: raise ValueError("dividend FX observation required")
            amount = convert_currency(amount, action.currency, position.currency, observation=fx_observation, information_cutoff_utc=fx_observation.available_at_utc)
        return CorporateActionResult(action.action_id, position.instrument_id, "applied", position, position, amount, position.currency, None if fx_observation is None else fx_observation.source_record_id, (), "cash dividend credited without reinvestment")
    if action.action_type is CorporateActionType.SYMBOL_CHANGE:
        if not action.successor_instrument_id: raise ValueError("symbol change requires successor")
        post = ResearchPosition(action.successor_instrument_id, position.quantity, position.cost_basis, position.currency, position.asset_class, position.quantity_precision)
        return CorporateActionResult(action.action_id, position.instrument_id, "applied", position, post, Decimal("0"), position.currency, None, (), "symbol changed")
    if action.action_type is CorporateActionType.DELISTING:
        if terminal_value is None: return CorporateActionResult(action.action_id, position.instrument_id, "unresolved", position, None, Decimal("0"), position.currency, None, ("terminal_value_required",), "delisting cannot assume zero or last price")
        return CorporateActionResult(action.action_id, position.instrument_id, "applied", position, None, terminal_value, terminal_currency or position.currency, None, (), "explicit terminal value applied")
    return CorporateActionResult(action.action_id, position.instrument_id, "rejected", position, None, Decimal("0"), position.currency, None, ("unsupported_action",), "action is unsupported")
