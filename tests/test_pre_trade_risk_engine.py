from __future__ import annotations

import json
import shutil
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from risk_engine.audit import RiskAuditError, RiskDecisionAudit
from risk_engine.authorization import RiskAuthorizationError, verify_risk_authorization
from risk_engine.configuration import RiskConfigurationError, load_risk_configuration
from risk_engine.engine import PreTradeRiskEngine
from risk_engine.kill_switch import load_kill_switch, set_kill_switch
from risk_engine.models import DecisionStatus, OrderProposal, RiskContext


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)


class FailingAudit(RiskDecisionAudit):
    def append(self, *_args, **_kwargs):
        raise RiskAuditError("fixture write failure")


class CentralRiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "central_risk_tests"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        base = load_risk_configuration()
        self.config = replace(
            base,
            trading_enabled=True,
            limits_approved=True,
            configuration_version="fixture",
            configuration_hash="fixture-hash",
        )
        self.kill_path = self.root / "kill.json"
        set_kill_switch(
            False, actor="unit-test", reason="deterministic fixture",
            correlation_id="fixture", state_path=self.kill_path,
            audit_path=self.root / "kill-audit.jsonl", now=NOW,
        )
        self.audit = RiskDecisionAudit(self.root / "decisions.jsonl")
        self.engine = PreTradeRiskEngine(
            configuration=self.config, audit=self.audit, kill_switch_path=self.kill_path,
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def proposal(self, **changes):
        values = {
            "proposal_id": "proposal-1", "strategy_id": "strategy-1", "signal_id": "bar-1",
            "symbol": "BTC-GBP", "market": "Crypto", "side": "BUY", "quantity": "0.01",
            "order_type": "MARKET", "limit_price": None, "stop_price": None,
            "time_in_force": "DAY", "strategy_timestamp": NOW,
            "source_bar_timestamp": NOW.replace(hour=0), "expected_execution_currency": "GBP",
            "reason": "fixture", "correlation_id": "trace-1", "metadata": {"timeframe": "1d"},
            "created_at": NOW,
        }
        values.update(changes)
        return OrderProposal.create(**values)

    def context(self, **changes):
        values = {
            "now": NOW, "runtime_mode": "paper_execution", "trading_enabled": True,
            "runtime_healthy": True, "scheduler_healthy": True, "adapter_ready": True,
            "market_session_valid": True, "source_bar_complete": True,
            "reference_price": Decimal("50000"), "reference_price_timestamp": NOW.replace(hour=0),
            "fx_rate_to_base": None, "fx_timestamp": None,
            "accounting_active": True, "accounting_verified": True,
            "accounting_generation_id": "generation-1", "accounting_base_currency": "GBP",
            "accounting_reconciled": True, "cash_base": Decimal("5000"),
            "portfolio_equity_base": Decimal("10000"), "positions_base": {},
            "position_quantities": {}, "open_order_notional_base": Decimal("0"),
            "daily_realised_pnl_base": Decimal("0"), "daily_total_pnl_base": Decimal("0"),
            "equity_high_water_mark_base": Decimal("10000"), "strategy_exposure_base": {},
            "market_exposure_base": {}, "currency_exposure_base": {},
            "estimated_fees_base": Decimal("0"), "seen_proposal_ids": frozenset(), "trace_id": "trace-1",
        }
        values.update(changes)
        return RiskContext(**values)

    def assert_reason(self, reason, *, proposal=None, context=None):
        decision = self.engine.evaluate(proposal or self.proposal(), context or self.context())
        self.assertFalse(decision.approved)
        self.assertEqual(decision.primary_reason_code, reason)
        return decision

    def test_valid_proposal_is_structured_approved_and_idempotent(self):
        proposal, context = self.proposal(), self.context()
        first = self.engine.evaluate(proposal, context)
        second = self.engine.evaluate(proposal, context)
        self.assertEqual(first.status, DecisionStatus.APPROVED)
        self.assertTrue(first.approved)
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertGreater(len(first.checks_passed), 0)
        verify_risk_authorization(proposal, first, configuration=self.config, now=NOW)

    def test_proposal_validation_and_duplicate_identity(self):
        self.assert_reason("UNKNOWN_INSTRUMENT", proposal=self.proposal(symbol="MISSING", market="UNKNOWN"))
        self.assert_reason("INVALID_QUANTITY", proposal=self.proposal(quantity="0", proposal_id="p-zero"))
        self.assert_reason("UNSUPPORTED_ORDER_TYPE", proposal=self.proposal(order_type="ICEBERG", proposal_id="p-type"))
        self.engine.evaluate(self.proposal(), self.context())
        self.assert_reason("DUPLICATE_PROPOSAL", proposal=self.proposal(quantity="0.02"))
        self.assert_reason("DUPLICATE_PROPOSAL", proposal=self.proposal(proposal_id="seen"), context=self.context(seen_proposal_ids=frozenset({"seen"})))

    def test_market_data_completion_freshness_and_future_checks(self):
        self.assert_reason("MARKET_DATA_MISSING", context=self.context(reference_price=None, reference_price_timestamp=None))
        self.assert_reason("BAR_INCOMPLETE", proposal=self.proposal(proposal_id="incomplete"), context=self.context(source_bar_complete=False))
        stale_now = NOW + timedelta(hours=13)
        self.assert_reason("MARKET_DATA_STALE", proposal=self.proposal(proposal_id="stale"), context=self.context(now=stale_now))
        self.assert_reason("FUTURE_MARKET_DATA", proposal=self.proposal(proposal_id="future", source_bar_timestamp=NOW+timedelta(minutes=1)))
        self.assert_reason("MARKET_CLOSED", proposal=self.proposal(proposal_id="closed"), context=self.context(market_session_valid=False))

    def test_fx_currency_and_gbp_minor_unit_handling(self):
        usd = self.proposal(proposal_id="usd", symbol="AAPL", market="NASDAQ", quantity="1", expected_execution_currency="USD")
        usd_context = self.context(reference_price=Decimal("200"), reference_price_timestamp=NOW, fx_rate_to_base=None, fx_timestamp=None)
        self.assert_reason("FX_RATE_MISSING", proposal=usd, context=usd_context)
        self.assert_reason("FX_RATE_STALE", proposal=replace(usd, proposal_id="usd-stale"), context=self.context(reference_price=Decimal("200"), reference_price_timestamp=NOW, fx_rate_to_base=Decimal("0.8"), fx_timestamp=NOW-timedelta(hours=4)))
        approved = self.engine.evaluate(replace(usd, proposal_id="usd-ok"), self.context(reference_price=Decimal("200"), reference_price_timestamp=NOW, fx_rate_to_base=Decimal("0.8"), fx_timestamp=NOW))
        self.assertTrue(approved.approved)
        gbp_minor = self.proposal(proposal_id="gbp-minor", symbol="IUSA.L", market="LSE", quantity="10", expected_execution_currency="GBP")
        minor_context = self.context(reference_price=Decimal("5000"), reference_price_timestamp=NOW)
        decision = self.engine.evaluate(gbp_minor, minor_context)
        self.assertTrue(decision.approved)

    def test_accounting_and_portfolio_unavailability_fail_closed(self):
        self.assert_reason("ACCOUNTING_INACTIVE", context=self.context(accounting_active=False))
        self.assert_reason("ACCOUNTING_UNVERIFIED", proposal=self.proposal(proposal_id="unverified"), context=self.context(accounting_verified=False))
        self.assert_reason("PORTFOLIO_STATE_UNAVAILABLE", proposal=self.proposal(proposal_id="missing-portfolio"), context=self.context(cash_base=None))
        self.assert_reason("ACCOUNTING_UNVERIFIED", proposal=self.proposal(proposal_id="wrong-base"), context=self.context(accounting_base_currency="USD"))

    def test_affordability_and_projected_exposure_limits(self):
        self.assert_reason("INSUFFICIENT_CASH", context=self.context(cash_base=Decimal("100")))
        self.assert_reason("ORDER_NOTIONAL_LIMIT_EXCEEDED", proposal=self.proposal(proposal_id="order-limit", quantity="0.03"))
        self.assert_reason("POSITION_LIMIT_EXCEEDED", proposal=self.proposal(proposal_id="position-limit", quantity="0.02"), context=self.context(positions_base={"BTC-GBP": Decimal("1600")}, position_quantities={"BTC-GBP": Decimal("0.032")}))
        concentration_config = replace(
            self.config,
            maximum_order_notional_base=Decimal("99999"),
            maximum_position_notional_base=Decimal("99999"),
        )
        engine = PreTradeRiskEngine(configuration=concentration_config, audit=RiskDecisionAudit(self.root/"concentration.jsonl"), kill_switch_path=self.kill_path)
        decision = engine.evaluate(self.proposal(proposal_id="concentration", quantity="0.06"), self.context())
        self.assertEqual(decision.primary_reason_code, "CONCENTRATION_LIMIT_EXCEEDED")
        self.assert_reason("GROSS_EXPOSURE_LIMIT_EXCEEDED", proposal=self.proposal(proposal_id="gross"), context=self.context(positions_base={"ETH-GBP": Decimal("7800")}, position_quantities={"ETH-GBP": Decimal("5")}))
        net_config = replace(self.config, maximum_gross_exposure_ratio=Decimal("1"))
        net_engine = PreTradeRiskEngine(configuration=net_config, audit=RiskDecisionAudit(self.root/"net.jsonl"), kill_switch_path=self.kill_path)
        net_decision = net_engine.evaluate(self.proposal(proposal_id="net"), self.context(positions_base={"ETH-GBP": Decimal("7800")}, position_quantities={"ETH-GBP": Decimal("5")}))
        self.assertEqual(net_decision.primary_reason_code, "NET_EXPOSURE_LIMIT_EXCEEDED")
        positions = {f"P{i}": Decimal("100") for i in range(8)}
        self.assert_reason("MAX_OPEN_POSITIONS_EXCEEDED", proposal=self.proposal(proposal_id="count"), context=self.context(positions_base=positions, position_quantities={key: Decimal("1") for key in positions}))

    def test_loss_and_drawdown_limits(self):
        self.assert_reason("DAILY_LOSS_LIMIT_EXCEEDED", context=self.context(daily_realised_pnl_base=Decimal("-251")))
        self.assert_reason("DAILY_LOSS_LIMIT_EXCEEDED", proposal=self.proposal(proposal_id="total-loss"), context=self.context(daily_total_pnl_base=Decimal("-401")))
        self.assert_reason("DRAWDOWN_LIMIT_EXCEEDED", proposal=self.proposal(proposal_id="drawdown"), context=self.context(portfolio_equity_base=Decimal("8000"), equity_high_water_mark_base=Decimal("10000")))

    def test_operational_controls(self):
        monitor = self.assert_reason("MONITOR_ONLY", context=self.context(runtime_mode="monitor_only"))
        self.assertEqual(monitor.status, DecisionStatus.MONITOR_ONLY)
        self.assert_reason("TRADING_DISABLED", proposal=self.proposal(proposal_id="disabled"), context=self.context(trading_enabled=False))
        self.assert_reason("RUNTIME_UNHEALTHY", proposal=self.proposal(proposal_id="runtime"), context=self.context(runtime_healthy=False))
        self.assert_reason("SCHEDULER_UNHEALTHY", proposal=self.proposal(proposal_id="scheduler"), context=self.context(scheduler_healthy=False))
        self.assert_reason("BROKER_UNAVAILABLE", proposal=self.proposal(proposal_id="adapter"), context=self.context(adapter_ready=False))
        set_kill_switch(True, actor="unit-test", reason="stop", correlation_id="kill", state_path=self.kill_path, audit_path=self.root/"kill-audit.jsonl", now=NOW)
        self.assert_reason("KILL_SWITCH_ACTIVE", proposal=self.proposal(proposal_id="kill"))

    def test_sell_validation_and_valid_risk_reduction(self):
        sell = self.proposal(proposal_id="sell", side="SELL", quantity="0.02")
        self.assert_reason("SELL_EXCEEDS_POSITION", proposal=sell, context=self.context(positions_base={"BTC-GBP": Decimal("500")}, position_quantities={"BTC-GBP": Decimal("0.01")}))
        reducing = replace(sell, proposal_id="reduce", quantity=Decimal("0.01"))
        context = self.context(positions_base={"BTC-GBP": Decimal("2500")}, position_quantities={"BTC-GBP": Decimal("0.05")})
        self.assertTrue(self.engine.evaluate(reducing, context).approved)

    def test_approval_tampering_modified_order_and_expiry(self):
        proposal = self.proposal()
        decision = self.engine.evaluate(proposal, self.context())
        with self.assertRaises(RiskAuthorizationError):
            verify_risk_authorization(replace(proposal, quantity=Decimal("0.02")), decision, configuration=self.config, now=NOW)
        with self.assertRaises(RiskAuthorizationError):
            verify_risk_authorization(proposal, decision, configuration=self.config, now=decision.expires_at+timedelta(seconds=1))
        with self.assertRaises(RiskAuthorizationError):
            verify_risk_authorization(proposal, replace(decision, approved=False), configuration=self.config, now=NOW)

    def test_kill_switch_persistence_and_invalid_state(self):
        state = load_kill_switch(self.kill_path)
        self.assertTrue(state.valid)
        self.assertFalse(state.active)
        invalid = self.root / "invalid-kill.json"
        invalid.write_text("{", encoding="utf-8")
        self.assertTrue(load_kill_switch(invalid).active)
        self.assertFalse(load_kill_switch(self.root/"missing.json").valid)

    def test_configuration_missing_malformed_and_unknown_fields(self):
        with self.assertRaises(RiskConfigurationError):
            load_risk_configuration(self.root/"missing-config.json")
        malformed = self.root/"malformed-config.json"
        malformed.write_text("{", encoding="utf-8")
        with self.assertRaises(RiskConfigurationError):
            load_risk_configuration(malformed)
        payload = json.loads((ROOT/"risk_engine/risk_config.json").read_text(encoding="utf-8"))
        payload["misspelled_limit"] = 1
        unknown = self.root/"unknown-config.json"
        unknown.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RiskConfigurationError):
            load_risk_configuration(unknown)

    def test_audit_failure_and_internal_exception_block(self):
        engine = PreTradeRiskEngine(configuration=self.config, audit=FailingAudit(self.root/"fail.jsonl"), kill_switch_path=self.kill_path)
        decision = engine.evaluate(self.proposal(), self.context())
        self.assertFalse(decision.approved)
        self.assertEqual(decision.primary_reason_code, "AUDIT_WRITE_FAILED")
        broken = self.context(reference_price_timestamp="not-a-timestamp")
        decision = self.engine.evaluate(self.proposal(proposal_id="internal"), broken)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.primary_reason_code, "INTERNAL_RISK_ERROR")

    def test_decimal_precision_and_concurrent_idempotent_evaluation(self):
        precise = self.proposal(proposal_id="precise", quantity="0.00000001")
        self.assertTrue(self.engine.evaluate(precise, self.context()).approved)
        proposal = self.proposal(proposal_id="concurrent")
        decisions = []
        threads = [threading.Thread(target=lambda: decisions.append(self.engine.evaluate(proposal, self.context()))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(decisions), 4)
        self.assertEqual(len({item.decision_id for item in decisions}), 1)
        self.assertTrue(all(item.approved for item in decisions))

    def test_default_production_configuration_cannot_approve(self):
        config = load_risk_configuration()
        engine = PreTradeRiskEngine(configuration=config, audit=RiskDecisionAudit(self.root/"default.jsonl"), kill_switch_path=self.root/"missing-kill.json")
        decision = engine.evaluate(self.proposal(), self.context())
        self.assertFalse(decision.approved)
        self.assertIn(decision.primary_reason_code, {"TRADING_DISABLED", "RISK_LIMITS_UNAPPROVED", "KILL_SWITCH_ACTIVE"})


if __name__ == "__main__":
    unittest.main()
