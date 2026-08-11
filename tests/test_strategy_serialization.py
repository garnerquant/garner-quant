import json
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from strategy.contract import BarStatus, DataQualityStatus, DecisionAction, DecisionStatus
from strategy.serialization import _canonical_value, canonical_sha256, to_canonical_json_bytes, to_canonical_payload
from tests.test_strategy_contract import bar, decision


BAR_JSON = '{"contract_type":"normalized_market_bar","payload":{"bar_end_utc":"2026-01-02T00:00:00.000000Z","bar_start_utc":"2026-01-01T00:00:00.000000Z","bar_status":"completed","close_price":"105","currency":"USD","high_price":"110","instrument_id":"AAPL","low_price":"95","open_price":"100","price_unit":"USD","quality_status":"valid","session_date":"2026-01-01","source_dataset_id":"dataset-1","source_record_id":"row-1","volume":"1000"},"schema_version":1}'
DECISION_JSON = '{"contract_type":"strategy_decision","payload":{"code_revision":"abc123","currency":"USD","dataset_version":"data-v1","decision_action":"buy","decision_id":"decision-1","decision_status":"eligible","decision_timestamp_utc":"2026-01-02T00:00:00.000000Z","eligible_execution_timestamp_utc":"2026-01-02T00:01:00.000000Z","information_cutoff_utc":"2026-01-02T00:00:00.000000Z","instrument_id":"AAPL","parameter_version":"params-v1","price_unit":"USD","quality_status":"valid","reason_codes":[],"signal_value":"0.8","strategy_id":"strategy-1","strategy_version":"v1","target_weight":"0.1","universe_version":"universe-v1"},"schema_version":1}'
BAR_SHA256 = "a36c875138d95e214680c5040003a290252a42d27145d7d1b34ee401a72d3be3"
DECISION_SHA256 = "7d1f644f724f8354859fd20e198107a30a3793d806d0f50abf891db1d5b57bcc"


class StrategySerializationTests(unittest.TestCase):
    def test_golden_json_and_hashes(self):
        market_bar = bar()
        strategy_decision = decision()
        self.assertEqual(to_canonical_json_bytes(market_bar).decode("utf-8"), BAR_JSON)
        self.assertEqual(to_canonical_json_bytes(strategy_decision).decode("utf-8"), DECISION_JSON)
        self.assertEqual(canonical_sha256(market_bar), BAR_SHA256)
        self.assertEqual(canonical_sha256(strategy_decision), DECISION_SHA256)

    def test_output_is_stable_utf8_compact_and_without_newline(self):
        encoded = to_canonical_json_bytes(bar())
        self.assertEqual(encoded, to_canonical_json_bytes(bar()))
        self.assertEqual(canonical_sha256(bar()), canonical_sha256(bar()))
        self.assertFalse(encoded.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(encoded.endswith(b"\n"))
        self.assertNotIn(b": ", encoded)
        self.assertEqual(json.loads(encoded), to_canonical_payload(bar()))

    def test_decimal_date_time_enum_tuple_none_and_unicode_rules(self):
        payload = to_canonical_payload(decision(signal_value=Decimal("1.0"), target_weight=Decimal("-0"), reason_codes=("z", "a")))
        self.assertEqual(payload["payload"]["signal_value"], "1")
        self.assertEqual(payload["payload"]["target_weight"], "0")
        self.assertEqual(payload["payload"]["reason_codes"], ["z", "a"])
        self.assertEqual(payload["payload"]["decision_action"], DecisionAction.BUY.value)
        self.assertEqual(payload["payload"]["decision_timestamp_utc"], "2026-01-02T00:00:00.000000Z")
        self.assertEqual(payload["payload"]["signal_value"], "1")
        self.assertEqual(to_canonical_payload(decision(signal_value=None))["payload"]["signal_value"], None)
        self.assertEqual(_canonical_value(Decimal("0.0100")), "0.01")
        self.assertEqual(_canonical_value(Decimal("1E+3")), "1000")
        self.assertEqual(_canonical_value(Decimal("-1.250")), "-1.25")
        with self.assertRaises(TypeError):
            _canonical_value(1.0)
        with self.assertRaises(TypeError):
            _canonical_value({1: "not allowed"})
        self.assertEqual(date(2026, 1, 1).isoformat(), "2026-01-01")
        self.assertEqual(to_canonical_payload(bar(instrument_id="e\u0301"))["payload"]["instrument_id"], "é")
        self.assertEqual(to_canonical_payload(bar(instrument_id="é")), to_canonical_payload(bar(instrument_id="e\u0301")))

    def test_contract_types_schema_and_meaningful_changes_are_separated(self):
        self.assertNotEqual(to_canonical_payload(bar())["contract_type"], to_canonical_payload(decision())["contract_type"])
        self.assertEqual(to_canonical_payload(bar())["schema_version"], 1)
        self.assertNotEqual(canonical_sha256(bar()), canonical_sha256(bar(close_price=Decimal("106"))))

    def test_unsupported_values_and_top_level_objects_are_rejected(self):
        with self.assertRaises(TypeError):
            to_canonical_json_bytes(object())
        with self.assertRaises(TypeError):
            _canonical_value(object())

    def test_no_file_environment_or_network_side_effects(self):
        before = set(os.environ)
        root = Path(__file__).parents[1]
        to_canonical_json_bytes(bar())
        self.assertEqual(before, set(os.environ))
        self.assertEqual(list(root.glob("_tkt004*")), [])


if __name__ == "__main__":
    unittest.main()
