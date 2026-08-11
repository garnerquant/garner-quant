import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from strategy.contract import (
    BarStatus, DataQualityStatus, DecisionAction, DecisionStatus,
    NormalizedMarketBar, StrategyDecision,
)


UTC = timezone.utc


def bar(**changes):
    values = dict(
        instrument_id="AAPL", bar_start_utc=datetime(2026, 1, 1, tzinfo=UTC),
        bar_end_utc=datetime(2026, 1, 2, tzinfo=UTC), session_date=date(2026, 1, 1),
        open_price=Decimal("100"), high_price=Decimal("110"), low_price=Decimal("95"),
        close_price=Decimal("105"), volume=Decimal("1000"), currency="USD",
        price_unit="USD", bar_status=BarStatus.COMPLETED,
        quality_status=DataQualityStatus.VALID, source_dataset_id="dataset-1", source_record_id="row-1",
    )
    values.update(changes)
    return NormalizedMarketBar(**values)


def decision(**changes):
    values = dict(
        decision_id="decision-1", strategy_id="strategy-1", strategy_version="v1",
        instrument_id="AAPL", decision_timestamp_utc=datetime(2026, 1, 2, tzinfo=UTC),
        information_cutoff_utc=datetime(2026, 1, 2, tzinfo=UTC),
        eligible_execution_timestamp_utc=datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
        decision_action=DecisionAction.BUY, decision_status=DecisionStatus.ELIGIBLE,
        signal_value=Decimal("0.8"), target_weight=Decimal("0.1"), currency="USD",
        price_unit="USD", quality_status=DataQualityStatus.VALID, reason_codes=(),
        dataset_version="data-v1", universe_version="universe-v1", parameter_version="params-v1",
        code_revision="abc123",
    )
    values.update(changes)
    return StrategyDecision(**values)


class StrategyContractTests(unittest.TestCase):
    def test_valid_objects_are_immutable(self):
        market_bar = bar()
        strategy_decision = decision()
        with self.assertRaises(FrozenInstanceError):
            market_bar.close_price = Decimal("1")
        with self.assertRaises(FrozenInstanceError):
            strategy_decision.reason_codes = ("changed",)

    def test_bar_rejects_bad_time_identifiers_and_decimals(self):
        cases = [
            {"bar_start_utc": datetime(2026, 1, 1)}, {"bar_end_utc": datetime(2026, 1, 2)},
            {"bar_start_utc": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
            {"bar_end_utc": datetime(2026, 1, 1, tzinfo=UTC)}, {"instrument_id": ""},
            {"source_dataset_id": ""}, {"source_record_id": ""}, {"open_price": 1.0},
            {"open_price": Decimal("NaN")}, {"open_price": Decimal("Infinity")},
            {"open_price": Decimal("-1")}, {"high_price": Decimal("90")},
            {"low_price": Decimal("111")}, {"volume": Decimal("-1")},
            {"currency": "usd"}, {"price_unit": ""},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises((TypeError, ValueError)):
                    bar(**changes)

    def test_bar_status_and_missing_volume_are_explicit(self):
        self.assertIsNone(bar(volume=None).volume)
        with self.assertRaises(ValueError):
            bar(bar_status=BarStatus.INCOMPLETE, quality_status=DataQualityStatus.VALID)
        incomplete = bar(bar_status=BarStatus.INCOMPLETE, quality_status=DataQualityStatus.INVALID)
        self.assertEqual(incomplete.bar_status, BarStatus.INCOMPLETE)

    def test_decision_rejects_timing_identifiers_values_and_reasons(self):
        cases = [
            {"decision_timestamp_utc": datetime(2026, 1, 2)},
            {"decision_timestamp_utc": datetime(2026, 1, 2, tzinfo=timezone(timedelta(hours=1)))},
            {"information_cutoff_utc": datetime(2026, 1, 3, tzinfo=UTC)},
            {"eligible_execution_timestamp_utc": datetime(2026, 1, 1, tzinfo=UTC)},
            {"decision_id": ""}, {"strategy_version": ""}, {"signal_value": 1.0},
            {"target_weight": Decimal("NaN")}, {"currency": "usd"},
            {"reason_codes": ["reason"]}, {"reason_codes": ("",)},
            {"reason_codes": ("duplicate", "duplicate")},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises((TypeError, ValueError)):
                    decision(**changes)
        with self.assertRaises(ValueError):
            decision(decision_status=DecisionStatus.REJECTED)

    def test_decision_provenance_and_reasons_are_explicit(self):
        rejected = decision(decision_status=DecisionStatus.REJECTED, decision_action=DecisionAction.NO_ACTION, reason_codes=("stale_data",))
        self.assertEqual(rejected.reason_codes, ("stale_data",))
        self.assertEqual(rejected.dataset_version, "data-v1")
        self.assertNotIn("validated", rejected.decision_status.value)
        self.assertNotIn("live", rejected.decision_status.value)


if __name__ == "__main__":
    unittest.main()
