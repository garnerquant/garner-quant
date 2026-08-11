import ast
import os
import unittest
from decimal import Decimal
from pathlib import Path

from strategy.contract import BarStatus, DataQualityStatus, NormalizedMarketBar
from strategy.serialization import canonical_sha256, to_canonical_json_bytes
from tests.strategy_fixtures import make_market_bar, make_market_bar_series, make_strategy_decision


class StrategyFixtureTests(unittest.TestCase):
    def test_default_bar_is_valid_repeated_and_immutable(self):
        first = make_market_bar()
        second = make_market_bar()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsInstance(first, NormalizedMarketBar)
        with self.assertRaises(Exception):
            first.close_price = Decimal("1")

    def test_bar_override_is_new_and_invalid_or_unknown_overrides_fail(self):
        original = make_market_bar()
        changed = make_market_bar(close_price=Decimal("103"))
        self.assertNotEqual(original, changed)
        self.assertEqual(original.close_price, Decimal("102"))
        with self.assertRaises(ValueError):
            make_market_bar(high_price=Decimal("90"))
        with self.assertRaises(TypeError):
            make_market_bar(unknown_field="not-supported")

    def test_default_decision_is_valid_immutable_and_later_eligible(self):
        first = make_strategy_decision()
        second = make_strategy_decision()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertGreater(first.eligible_execution_timestamp_utc, first.decision_timestamp_utc)
        with self.assertRaises(Exception):
            first.target_weight = Decimal("0.2")

    def test_decision_overrides_validate_and_change_hash(self):
        original = make_strategy_decision()
        changed = make_strategy_decision(target_weight=Decimal("0.20"))
        self.assertNotEqual(canonical_sha256(original), canonical_sha256(changed))
        with self.assertRaises(TypeError):
            make_strategy_decision(decision_status="not-a-status")
        with self.assertRaises(TypeError):
            make_strategy_decision(unknown_field="not-supported")

    def test_series_is_tuple_deterministic_unique_and_structurally_valid(self):
        first = make_market_bar_series(3)
        second = make_market_bar_series(3)
        self.assertIsInstance(first, tuple)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(len({item.source_record_id for item in first}), 3)
        self.assertEqual([canonical_sha256(item) for item in first], [canonical_sha256(item) for item in second])
        self.assertIsNot(first[0], second[0])
        for item in first:
            self.assertIsInstance(item.open_price, Decimal)
            self.assertLessEqual(item.low_price, item.open_price)
            self.assertLessEqual(item.open_price, item.high_price)
            self.assertEqual(item.bar_status, BarStatus.COMPLETED)
            self.assertEqual(item.quality_status, DataQualityStatus.VALID)

    def test_series_count_validation(self):
        for value, error in ((0, ValueError), (-1, ValueError), (True, TypeError), (1.5, TypeError)):
            with self.subTest(value=value):
                with self.assertRaises(error):
                    make_market_bar_series(value)

    def test_serialization_is_stable_and_fixture_module_is_safe(self):
        fixture = make_market_bar()
        self.assertEqual(to_canonical_json_bytes(fixture), to_canonical_json_bytes(make_market_bar()))
        before_environment = set(os.environ)
        module = Path(__file__).with_name("strategy_fixtures.py")
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = " ".join(ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
        for forbidden in ("random", "uuid", "pandas", "yfinance", "requests", "supabase", "runtime", "execution", "canonical_accounting"):
            self.assertNotIn(forbidden, imports.lower())
        self.assertEqual(before_environment, set(os.environ))
        self.assertEqual(list(Path(__file__).parents[1].glob("_tkt005*")), [])


if __name__ == "__main__":
    unittest.main()
