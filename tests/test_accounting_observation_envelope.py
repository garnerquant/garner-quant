from __future__ import annotations

import hashlib
import shutil
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from canonical_accounting.observation import (
    AccountingObservationError, AccountingObservationStore, SCHEMA_VERSION,
    REPLAY_METADATA, envelope_from_risk_evaluation, observe_monitor_only_evaluation,
)
from risk_engine.audit import RiskDecisionAudit
from risk_engine.configuration import load_risk_configuration
from risk_engine.engine import PreTradeRiskEngine
from risk_engine.models import OrderProposal, RiskContext

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)


class AccountingObservationEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "accounting_observation_tests"; shutil.rmtree(self.root, ignore_errors=True); self.root.mkdir(parents=True)
        self.engine = PreTradeRiskEngine(configuration=load_risk_configuration(), audit=RiskDecisionAudit(self.root / "risk.jsonl"), kill_switch_path=self.root / "kill.json")
        self.store = AccountingObservationStore(self.root / "envelopes.jsonl", self.root / "failures.jsonl")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def proposal(self, **changes):
        values = {"proposal_id":"p1", "strategy_id":"alpha", "signal_id":"bar-1", "symbol":"BTC-GBP", "market":"Crypto",
                  "side":"BUY", "quantity":"0.01", "order_type":"MARKET", "limit_price":None, "stop_price":None,
                  "time_in_force":"DAY", "strategy_timestamp":NOW, "source_bar_timestamp":NOW,
                  "expected_execution_currency":"GBP", "reason":"fixture", "correlation_id":"corr",
                  "metadata":{"timeframe":"1d", "strategy_version":"garner-strategy-v1", "fx_source":"fixture"}, "created_at":NOW}
        values.update(changes); return OrderProposal.create(**values)

    def context(self, **changes):
        values = {"now":NOW, "runtime_mode":"monitor_only", "trading_enabled":False, "runtime_healthy":True,
                  "scheduler_healthy":True, "adapter_ready":False, "market_session_valid":True, "source_bar_complete":True,
                  "reference_price":Decimal("50000"), "reference_price_timestamp":NOW, "fx_rate_to_base":Decimal("1"), "fx_timestamp":NOW,
                  "accounting_active":False, "accounting_verified":False, "accounting_generation_id":None,
                  "accounting_base_currency":None, "accounting_reconciled":False, "cash_base":None, "portfolio_equity_base":None,
                  "positions_base":None, "position_quantities":None, "open_order_notional_base":None,
                  "daily_realised_pnl_base":None, "daily_total_pnl_base":None, "equity_high_water_mark_base":None,
                  "strategy_exposure_base":None, "market_exposure_base":None, "currency_exposure_base":None,
                  "estimated_fees_base":Decimal("1.25"), "seen_proposal_ids":frozenset(), "trace_id":"corr", "shadow_mode":True}
        values.update(changes); return RiskContext(**values)

    def envelope(self, proposal=None, context=None):
        proposal=proposal or self.proposal(); context=context or self.context(); decision=self.engine.evaluate(proposal, context)
        return envelope_from_risk_evaluation(proposal, context, decision, created_at=NOW), decision

    def test_buy_sell_gbp_gbp_minor_usd_fees_and_multiple_strategies(self):
        buy, _ = self.envelope(); self.assertEqual(buy.event_type, "BUY_FILL"); self.assertEqual(buy.fees_base, Decimal("1.25"))
        sell, _ = self.envelope(self.proposal(proposal_id="p2", side="SELL", strategy_id="beta")); self.assertEqual(sell.event_type, "SELL_FILL"); self.assertEqual(sell.position_impact, Decimal("0.01"))
        minor, _ = self.envelope(self.proposal(proposal_id="p3", symbol="IUSA.L", market="LSE", quantity="10"), self.context(reference_price=Decimal("5000")))
        self.assertEqual(minor.price_units, "GBp"); self.assertEqual(minor.instrument_metadata["price_scale"], "0.01")
        usd_proposal = self.proposal(proposal_id="p4", symbol="AAPL", market="NASDAQ", expected_execution_currency="USD", metadata={"timeframe":"1d", "strategy_version":"v2", "fx_source":"fixture-usd"})
        usd, _ = self.envelope(usd_proposal, self.context(reference_price=Decimal("200"), fx_rate_to_base=Decimal("0.8")))
        self.assertEqual(usd.native_currency, "USD"); self.assertEqual(usd.fx_rate_to_base, Decimal("0.8"))

    def test_validation_missing_fx_strategy_metadata_eur_and_nonfinite(self):
        proposal=self.proposal(proposal_id="missing-fx", symbol="AAPL", market="NASDAQ", expected_execution_currency="USD"); context=self.context(reference_price=Decimal("200"), fx_rate_to_base=None, fx_timestamp=None)
        decision=self.engine.evaluate(proposal, context)
        with self.assertRaises(AccountingObservationError): envelope_from_risk_evaluation(proposal, context, decision)
        with self.assertRaises(AccountingObservationError): self.envelope(self.proposal(proposal_id="missing-strategy", strategy_id=""))
        with self.assertRaises((AccountingObservationError, KeyError)): self.envelope(self.proposal(proposal_id="eur", symbol="EUR-CASH", market="CASH", expected_execution_currency="EUR"), self.context(fx_rate_to_base=Decimal("0.9")))
        nan_context=self.context(reference_price=Decimal("NaN")); nan_decision=self.engine.evaluate(self.proposal(proposal_id="nan"), nan_context)
        with self.assertRaises(AccountingObservationError): envelope_from_risk_evaluation(self.proposal(proposal_id="nan"), nan_context, nan_decision)

    def test_serialization_hash_version_duplicate_restart_and_append_only(self):
        envelope, _ = self.envelope(); first=envelope.serialize(); self.assertEqual(first, envelope.serialize()); self.assertEqual(len(envelope.envelope_hash), 64)
        self.assertEqual(envelope.to_dict()["schema_version"], SCHEMA_VERSION); self.assertTrue(self.store.append(envelope)); before=(self.root/"envelopes.jsonl").read_bytes()
        self.assertFalse(AccountingObservationStore(self.root/"envelopes.jsonl", self.root/"failures.jsonl").append(envelope)); self.assertEqual(before, (self.root/"envelopes.jsonl").read_bytes())
        with self.assertRaises(AccountingObservationError): self.store.append(replace(envelope, created_at=NOW.replace(hour=11)))
        with self.assertRaises(AccountingObservationError): replace(envelope, schema_version="2.0").serialize()

    def test_future_cash_fee_dividend_fx_and_corporate_types_are_schema_supported(self):
        envelope, _ = self.envelope()
        for event_type in ("DEPOSIT", "WITHDRAWAL", "DIVIDEND", "FEE", "FX_ADJUSTMENT", "CORPORATE_ACTION"):
            future = replace(envelope, event_id=f"future-{event_type}", event_type=event_type, side="NONE",
                             quantity=Decimal("0"), position_impact=Decimal("0"))
            self.assertEqual(future.to_dict()["event_type"], event_type)
        eur_policy = REPLAY_METADATA["EUR-CASH"]
        eur_metadata = {"instrument_id": eur_policy.instrument_id, "price_precision": eur_policy.price_precision,
                        "quantity_precision": eur_policy.quantity_precision, "minimum_lot": str(eur_policy.minimum_lot),
                        "lot_increment": str(eur_policy.lot_increment), "fractional_support": eur_policy.fractional_support,
                        "market_calendar": eur_policy.market_calendar, "timezone": eur_policy.timezone,
                        "metadata_source": "internal cash-balance policy v1", "price_scale": "1"}
        eur = replace(envelope, event_id="future-eur-deposit", instrument_id=eur_policy.instrument_id,
                      symbol="EUR-CASH", market="CASH", venue="CASH", asset_class="Cash", side="NONE",
                      event_type="DEPOSIT", quantity=Decimal("0"), native_price=Decimal("100"),
                      price_units="EUR", native_currency="EUR", fx_rate_to_base=Decimal("0.9"),
                      fx_source="fixture-eur", position_impact=Decimal("0"), instrument_metadata=eur_metadata)
        self.assertEqual(eur.to_dict()["native_currency"], "EUR")

    def test_monitor_only_pipeline_records_or_fails_without_execution_or_accounting(self):
        protected=[ROOT/name for name in ("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")]
        before={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        proposal=self.proposal(); context=self.context(); decision=self.engine.evaluate(proposal, context)
        result=observe_monitor_only_evaluation(proposal, context, decision, store=self.store); self.assertEqual(result["status"], "VALID")
        bad=self.proposal(proposal_id="bad", symbol="AAPL", market="NASDAQ", expected_execution_currency="USD", metadata={"timeframe":"1d","strategy_version":"v","fx_source":""})
        bad_context=self.context(reference_price=Decimal("200"), fx_rate_to_base=None, fx_timestamp=None); bad_decision=self.engine.evaluate(bad,bad_context)
        self.assertEqual(observe_monitor_only_evaluation(bad,bad_context,bad_decision,store=self.store)["status"],"INVALID")
        self.assertEqual(before,{path:hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}); self.assertFalse((ROOT/"data/accounting_generations/accounting_generation.json").exists())


if __name__ == "__main__": unittest.main()
