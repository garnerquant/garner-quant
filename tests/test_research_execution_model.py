from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest

from research.execution_model import FeePolicy, SlippagePolicy, simulate_long_exit, simulate_next_bar_entry
from strategy.contract import BarStatus, DataQualityStatus, DecisionAction, DecisionStatus, NormalizedMarketBar, StrategyDecision


OBS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(start_hour, open_price=Decimal("100"), high=Decimal("105"), low=Decimal("95"), close=Decimal("100"), record="r"):
    start = datetime(2026, 1, 1, start_hour, tzinfo=timezone.utc); end = start + timedelta(hours=1)
    return NormalizedMarketBar("AAPL", start, end, date(2026, 1, 1), open_price, high, low, close, Decimal("1"), "GBP", "GBP", BarStatus.COMPLETED, DataQualityStatus.VALID, "d", f"{record}{start_hour}")


def decision():
    return StrategyDecision("d1", "s", "v", "AAPL", datetime(2026, 1, 1, 1, tzinfo=timezone.utc), OBS, datetime(2026, 1, 1, 2, tzinfo=timezone.utc), DecisionAction.BUY, DecisionStatus.ELIGIBLE, Decimal("1"), Decimal("0.1"), "GBP", "GBP", DataQualityStatus.VALID, (), "d", "u", "p", "c")


def costs(): return FeePolicy("fee-v1", Decimal("0.01")), SlippagePolicy("slip-v1", Decimal("10"))


def test_next_bar_entry_costs_and_missing_bar():
    fee, slip = costs(); filled = simulate_next_bar_entry(decision=decision(), decision_bar=bar(1, record="d"), next_bar=bar(2, record="n"), quantity=Decimal("2"), quantity_precision=0, fee_policy=fee, slippage_policy=slip)
    assert filled.status == "filled" and filled.fill_timestamp == bar(2, record="n").bar_start_utc and filled.fee > 0
    missing = simulate_next_bar_entry(decision=decision(), decision_bar=bar(1), next_bar=None, quantity=Decimal("2"), quantity_precision=0, fee_policy=fee, slippage_policy=slip)
    assert missing.status == "unfilled"


def test_exit_gap_and_ambiguity():
    fee, slip = costs(); entry = bar(1); stop = bar(2, open_price=Decimal("90"), high=Decimal("92"), low=Decimal("88"), close=Decimal("90"))
    result = simulate_long_exit(order_id="x", instrument_id="AAPL", quantity=Decimal("2"), decision_timestamp=OBS, position_bar=entry, bar=stop, stop_price=Decimal("95"), target_price=Decimal("110"), fee_policy=fee, slippage_policy=slip)
    assert result.status == "filled" and result.reference_price == Decimal("90")
    both = bar(2, high=Decimal("115"), low=Decimal("90"))
    ambiguous = simulate_long_exit(order_id="x", instrument_id="AAPL", quantity=Decimal("2"), decision_timestamp=OBS, position_bar=entry, bar=both, stop_price=Decimal("95"), target_price=Decimal("110"), fee_policy=fee, slippage_policy=slip)
    assert ambiguous.status == "rejected"


def test_quantity_precision_and_unknown_costs_rejected():
    fee, slip = costs()
    with pytest.raises(ValueError): simulate_next_bar_entry(decision=decision(), decision_bar=bar(1), next_bar=bar(2), quantity=Decimal("1.1"), quantity_precision=0, fee_policy=fee, slippage_policy=slip)
    assert simulate_next_bar_entry(decision=decision(), decision_bar=bar(1), next_bar=bar(2), quantity=Decimal("0.12345678"), quantity_precision=8, fee_policy=fee, slippage_policy=slip).status == "filled"
    with pytest.raises(ValueError): simulate_next_bar_entry(decision=decision(), decision_bar=bar(1), next_bar=bar(2), quantity=Decimal("1"), quantity_precision=0, fee_policy=FeePolicy("", Decimal("0")), slippage_policy=slip)
