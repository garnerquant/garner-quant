from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from data.fx import FxObservation
from data.point_in_time import CorporateAction, CorporateActionType
from research.corporate_actions import ResearchPosition, apply_corporate_action


def position(quantity=Decimal("10"), asset="equity", precision=0):
    return ResearchPosition("AAPL", quantity, Decimal("1000"), "GBP", asset, precision)


def action(kind, **kwargs):
    return CorporateAction(1, "a1", "AAPL", kind, date(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc), source_name="fixture", source_record_id="a1", **kwargs)


def test_split_reverse_split_and_fractional_policy():
    split = apply_corporate_action(position=position(), action=action(CorporateActionType.STOCK_SPLIT, ratio=Decimal("2")), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert split.post_position.quantity == Decimal("20") and split.post_position.cost_basis == Decimal("500")
    reverse = apply_corporate_action(position=position(Decimal("3")), action=action(CorporateActionType.REVERSE_SPLIT, ratio=Decimal("0.5")), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert reverse.status == "rejected"


def test_dividend_fx_symbol_change_delisting_and_adjusted_guard():
    dividend = apply_corporate_action(position=position(), action=action(CorporateActionType.CASH_DIVIDEND, cash_amount=Decimal("1"), currency="GBP"), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert dividend.cash_movement == Decimal("10")
    fx = FxObservation("USD", "GBP", Decimal("0.8"), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 1, tzinfo=timezone.utc), "f", "fx1", "v")
    foreign = apply_corporate_action(position=ResearchPosition("AAPL", Decimal("10"), Decimal("1000"), "GBP", "equity", 0), action=action(CorporateActionType.CASH_DIVIDEND, cash_amount=Decimal("1"), currency="USD"), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1), fx_observation=fx)
    assert foreign.cash_movement == Decimal("8")
    changed = apply_corporate_action(position=position(), action=action(CorporateActionType.SYMBOL_CHANGE, successor_instrument_id="NEW"), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert changed.post_position.instrument_id == "NEW"
    unresolved = apply_corporate_action(position=position(), action=action(CorporateActionType.DELISTING), research_price_basis="raw_execution_with_actions", as_of_date=date(2026, 1, 1))
    assert unresolved.status == "unresolved"
    adjusted = apply_corporate_action(position=position(), action=action(CorporateActionType.STOCK_SPLIT, ratio=Decimal("2")), research_price_basis="adjusted_total_return_research", as_of_date=date(2026, 1, 1))
    assert adjusted.status == "rejected"


def test_effective_boundary_hash_and_no_mutation():
    original = position()
    result = apply_corporate_action(position=original, action=action(CorporateActionType.STOCK_SPLIT, ratio=Decimal("2")), research_price_basis="raw_execution_with_actions", as_of_date=date(2025, 12, 31))
    assert result.status == "not_yet_effective" and original.quantity == Decimal("10")
    assert len(result.canonical_sha256()) == 64
