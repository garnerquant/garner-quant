from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard.malformed_observation_reader import malformed_equity_observation_status
from dashboard.operations_presentation import market_data_warning_summary
from dashboard.paper_challenge import build_paper_challenge_series

ROOT = Path(__file__).resolve().parents[1]


class MalformedEquityObservationTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "malformed_equity_tests"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tracker(self):
        return pd.DataFrame([
            {"date": "2026-07-01 22:51:38", "portfolio_value": 9806.945855, "cash": 2470.33,
             "realised_pnl": -229.67, "unrealised_pnl": 36.62},
            {"date": "2026-07-02 13:21:44", "portfolio_value": np.nan, "cash": 2470.33,
             "realised_pnl": -229.67, "unrealised_pnl": np.nan},
            {"date": "2026-07-02 16:35:35", "portfolio_value": 9760.039123, "cash": 1970.33,
             "realised_pnl": -229.67, "unrealised_pnl": -10.29},
        ])

    def test_actual_legacy_shape_is_rejected_with_exact_reason(self):
        result = build_paper_challenge_series(self.tracker(), 10000, 60, today="2026-07-03",
                                              source="paper_30_day_tracker.csv")
        self.assertEqual(result.malformed_observations, 1)
        detail = result.malformed_details[0]
        self.assertEqual((detail.source_record_id, detail.timestamp), ("row-3", "2026-07-02 13:21:44"))
        self.assertEqual(detail.failed_rules, ("portfolio_value must be finite",))
        self.assertEqual(detail.classification, "STALE_LEGACY_RECORD")
        self.assertEqual(detail.status, "ACTIVE")
        self.assertNotIn(pd.Timestamp("2026-07-02 13:21:44"), set(result.data["timestamp"]))

    def test_valid_observations_and_current_calculations_are_unchanged(self):
        valid = self.tracker().drop(index=1).reset_index(drop=True)
        result = build_paper_challenge_series(valid, 10000, 60, today="2026-07-03")
        self.assertEqual(result.malformed_observations, 0)
        self.assertEqual(result.malformed_details, ())
        self.assertAlmostEqual(float(result.data.iloc[-1]["total_equity"]), 9760.039123)
        self.assertAlmostEqual(float(result.data.iloc[-1]["drawdown_pct"]), -2.39960877, places=6)

    def test_invalid_failure_modes_remain_fail_closed_and_deterministic(self):
        invalid = pd.DataFrame([
            {"date": "bad", "portfolio_value": "100", "cash": 1},
            {"date": "2026-01-02", "portfolio_value": "N/A", "cash": 1},
            {"date": "2026-01-03", "portfolio_value": "Infinity", "cash": 1},
            {"date": "2026-01-04", "portfolio_value": 0, "cash": 1},
            {"date": "2026-01-05", "portfolio_value": -1, "cash": 1},
        ])
        first = build_paper_challenge_series(invalid, 100, 60)
        second = build_paper_challenge_series(invalid, 100, 60)
        self.assertEqual(first.malformed_observations, 5)
        self.assertEqual(first.malformed_details, second.malformed_details)
        self.assertTrue(first.data.empty)
        reasons = {reason for item in first.malformed_details for reason in item.failed_rules}
        self.assertEqual(reasons, {"timestamp must be parseable", "portfolio_value must be finite",
                                   "portfolio_value must be positive"})
        self.assertTrue(all(item.classification == "SOURCE_DATA_INVALID" for item in first.malformed_details))

    def test_home_copy_is_plain_english_and_clears_without_records(self):
        warning = market_data_warning_summary(1)
        self.assertEqual(warning["message"], "1 invalid equity record was ignored.")
        self.assertEqual(warning["continuity"], "Monitoring continues.")
        self.assertIn("Operations", warning["action"])
        self.assertIsNone(market_data_warning_summary(0))

    def test_operations_reader_is_actionable_and_does_not_expose_raw_secrets(self):
        path = self.root / "paper_30_day_tracker.csv"
        tracker = self.tracker()
        tracker["api_token"] = "top-secret"
        tracker.to_csv(path, index=False)
        status = malformed_equity_observation_status(path)
        self.assertEqual((status["status"], status["count"]), ("ACTIVE", 1))
        record = status["records"][0]
        self.assertEqual(record["Failure Reason"], "portfolio_value must be finite")
        self.assertIn("Keep excluded", record["Recommended Action"])
        self.assertNotIn("top-secret", str(status))
        self.assertNotIn("api_token", str(status))

    def test_stale_warning_clears_when_source_is_clean(self):
        path = self.root / "paper_30_day_tracker.csv"
        self.tracker().to_csv(path, index=False)
        self.assertEqual(malformed_equity_observation_status(path)["status"], "ACTIVE")
        self.tracker().drop(index=1).to_csv(path, index=False)
        cleared = malformed_equity_observation_status(path)
        self.assertEqual((cleared["status"], cleared["count"], cleared["records"]), ("CLEARED", 0, ()))

    def test_home_and_operations_sources_contain_no_behavioral_dependencies(self):
        reader = (ROOT / "dashboard" / "malformed_observation_reader.py").read_text(encoding="utf-8")
        for token in ("execution.", "risk_engine", "canonical_accounting", "submit_order", "write_text", "to_csv"):
            self.assertNotIn(token, reader)


if __name__ == "__main__":
    unittest.main()
