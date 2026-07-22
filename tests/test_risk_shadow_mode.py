from __future__ import annotations

import hashlib
import shutil
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from risk_engine.operations import activation_readiness, configuration_health, decision_history, risk_metrics
from risk_engine.shadow_simulation import run_shadow_simulations
from runtime.live_runtime import run_shadow_evaluation


ROOT = Path(__file__).resolve().parents[1]


class RiskShadowModeTests(unittest.TestCase):
    def setUp(self):
        self.output = ROOT / ".tmp" / "risk_shadow_tests"
        shutil.rmtree(self.output, ignore_errors=True)
        self.report = run_shadow_simulations(self.output, prices_path=ROOT / "prices_v2.csv")
        self.audit = self.output / "decisions.jsonl"

    def tearDown(self):
        shutil.rmtree(self.output, ignore_errors=True)

    def test_all_required_scenarios_are_non_executing(self):
        expected = {
            "valid_buy", "valid_sell", "insufficient_cash", "position_limit", "gross_exposure",
            "net_exposure", "drawdown", "daily_loss", "stale_data", "missing_fx",
            "inactive_accounting", "kill_switch", "monitor_only", "duplicate_proposal",
            "expired_approval", "approval_tampering",
        }
        self.assertEqual({item["scenario"] for item in self.report["scenarios"]}, expected)
        self.assertEqual(self.report["execution_attempts"], 0)
        for item in self.report["scenarios"]:
            if item["scenario"] not in {"expired_approval", "approval_tampering"}:
                self.assertFalse(item["decision"]["approved"])

    def test_shadow_decision_contains_full_operational_projection(self):
        decision = next(item["decision"] for item in self.report["scenarios"] if item["scenario"] == "valid_buy")
        self.assertEqual(decision["status"], "MONITOR_ONLY")
        self.assertFalse(decision["observed_values"]["execution_eligible"])
        self.assertIn("projected_cash_base", decision["observed_values"])
        self.assertIn("projected_gross_exposure_base", decision["observed_values"])
        self.assertIn("projected_net_exposure_base", decision["observed_values"])
        self.assertIn("projected_concentration_ratio", decision["observed_values"])
        self.assertGreaterEqual(float(decision["evaluation_latency_ms"]), 0)

    def test_history_is_filterable_and_append_only(self):
        before = self.audit.read_bytes()
        rows = decision_history(audit_path=self.audit, symbol="AAPL", decision="MONITOR_ONLY")
        self.assertTrue(rows)
        self.assertTrue(all(row["symbol"] == "AAPL" for row in rows))
        self.assertEqual(before, self.audit.read_bytes())
        digest = hashlib.sha256(before).hexdigest()
        run_shadow_simulations(self.output / "second", prices_path=ROOT / "prices_v2.csv")
        self.assertEqual(hashlib.sha256(self.audit.read_bytes()).hexdigest(), digest)

    def test_metrics_readiness_and_configuration_health(self):
        metrics = risk_metrics(audit_path=self.audit, kill_audit_path=self.output / "kill-audit.jsonl",
                               now=datetime(2026, 7, 22, tzinfo=timezone.utc))
        self.assertGreater(metrics["MONITOR_ONLY"], 0)
        self.assertIsNotNone(metrics["average_latency_ms"])
        health = configuration_health()
        self.assertTrue(health["healthy"])
        self.assertTrue(all(item["valid"] for item in health["fields"]))
        readiness = activation_readiness(accounting_root=self.output / "missing-accounting",
                                         kill_switch_path=self.output / "missing-kill.json")
        self.assertFalse(readiness["ready"])
        descriptions = {item["description"] for item in readiness["blockers"]}
        self.assertIn("Accounting inactive", descriptions)
        self.assertIn("Canonical strategy exposure unavailable", descriptions)

    def test_runtime_shadow_wrapper_never_accepts_execution_side_effects(self):
        safe = {"status": "shadow_complete", "shadow_decisions": 2, "trades_recorded": 0,
                "portfolio_changed": False, "executed_symbols": [], "latest_shadow_decision": {"status": "MONITOR_ONLY"}}
        with patch("main_v2.main", return_value=safe) as pipeline:
            result = run_shadow_evaluation(
                datetime(2026, 7, 22, 10, tzinfo=timezone.utc), eligible_symbols=["BTC-GBP"],
                bar_identities={"BTC-GBP": "bar"}, bar_timestamps={"BTC-GBP": "2026-07-22T00:00:00+00:00"},
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["trades_recorded"], 0)
        self.assertTrue(pipeline.call_args.kwargs["shadow_mode"])
        unsafe = dict(safe, trades_recorded=1)
        with patch("main_v2.main", return_value=unsafe):
            result = run_shadow_evaluation(
                datetime(2026, 7, 22, 10, tzinfo=timezone.utc), eligible_symbols=["BTC-GBP"],
                bar_identities={"BTC-GBP": "bar"}, bar_timestamps={"BTC-GBP": "2026-07-22T00:00:00+00:00"},
            )
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
