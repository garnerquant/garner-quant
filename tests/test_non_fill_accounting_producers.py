from __future__ import annotations

import hashlib
import shutil
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from canonical_accounting.non_fill_events import NonFillEventRequest
from canonical_accounting.non_fill_producers import build_non_fill_envelope, observe_non_fill_event, producer_framework_status
from canonical_accounting.observation import AccountingObservationError, AccountingObservationStore
from dashboard.accounting_observation_reader import accounting_observation_status
from risk_engine.configuration import load_risk_configuration

ROOT=Path(__file__).resolve().parents[1]; NOW=datetime(2026,7,22,12,tzinfo=timezone.utc)


class NonFillProducerTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/".tmp/non_fill_tests"; shutil.rmtree(self.root,ignore_errors=True); self.root.mkdir(parents=True)
        self.store=AccountingObservationStore(self.root/"envelopes.jsonl",self.root/"invalid.jsonl")
    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)

    def request(self,event_type="DEPOSIT",**changes):
        values={"source_event_id":"source-1","event_type":event_type,"producer_id":"controlled-non-fill-import","producer_version":"1.0",
                "source_system":"authorised-statement","source_reference":"statement:1","authority_method":"signed controlled statement fixture",
                "correlation_id":"corr-1","strategy_id":"ACCOUNT","instrument_id":"instrument:GBP-CASH","symbol":"GBP-CASH",
                "native_currency":"GBP","base_currency":"GBP","amount":"100","quantity":"0","effective_timestamp":NOW,
                "source_timestamp":NOW,"received_timestamp":NOW,"valuation_timestamp":NOW,"fx_rate_to_base":"1","fx_timestamp":NOW,
                "fx_source":"GBP identity","reason":"fixture","description":"authoritative fixture","supporting_metadata":{},
                "configuration_version":load_risk_configuration().configuration_version,"runtime_mode":"monitor_only","monitor_only":True}
        values.update(changes); return NonFillEventRequest.create(**values)

    def test_immutable_stable_hash_idempotency_conflict_and_restart(self):
        request=self.request(); self.assertEqual(request.serialize(),request.serialize()); self.assertEqual(len(request.request_hash),64)
        with self.assertRaises(FrozenInstanceError): request.amount=Decimal("2")
        first=observe_non_fill_event(request,store=self.store); self.assertTrue(first["appended"])
        before=(self.root/"envelopes.jsonl").read_bytes(); second=observe_non_fill_event(request,store=AccountingObservationStore(self.root/"envelopes.jsonl",self.root/"invalid.jsonl")); self.assertFalse(second["appended"]); self.assertEqual(before,(self.root/"envelopes.jsonl").read_bytes())
        with self.assertRaises(AccountingObservationError): observe_non_fill_event(replace(request,description="conflict"),store=self.store)
        self.assertEqual(len(self.store.records()),1)

    def test_deposit_withdrawal_signs_gbp_and_foreign_fx(self):
        deposit=build_non_fill_envelope(self.request()); self.assertEqual(deposit.cash_impact_base,Decimal("100")); self.assertEqual(deposit.observation_metadata["performance_classification"],"EXTERNAL_FLOW")
        withdrawal=build_non_fill_envelope(self.request("WITHDRAWAL",source_event_id="w")); self.assertEqual(withdrawal.cash_impact_base,Decimal("-100"))
        eur=build_non_fill_envelope(self.request(source_event_id="eur",instrument_id="instrument:EUR-CASH",symbol="EUR-CASH",native_currency="EUR",fx_rate_to_base="0.9",fx_source="authoritative-eur",amount="50")); self.assertEqual(eur.cash_impact_base,Decimal("45.0"))
        for amount in ("0","-1"):
            with self.assertRaises(AccountingObservationError): self.request(source_event_id="bad"+amount,amount=amount)
        with self.assertRaises(AccountingObservationError): self.request(source_event_id="inferred",supporting_metadata={"derived_from_balance":True})
        with self.assertRaises(AccountingObservationError): self.request(source_event_id="missing-fx",instrument_id="instrument:EUR-CASH",symbol="EUR-CASH",native_currency="EUR",fx_rate_to_base=None,fx_timestamp=None,fx_source="")

    def test_dividend_withholding_entitlement_and_attribution(self):
        request=self.request("DIVIDEND",source_event_id="div",instrument_id="instrument:AAPL",symbol="AAPL",native_currency="USD",amount="10",net_amount="8.5",withholding_tax="1.5",strategy_id="alpha",attribution_policy="STRATEGY",supporting_metadata={"entitlement_reference":"record-date-lot-1"},fx_rate_to_base="0.8",fx_source="statement-fx")
        envelope=build_non_fill_envelope(request); self.assertEqual(envelope.cash_impact_base,Decimal("6.80")); self.assertEqual(envelope.estimated_costs_base,Decimal("1.20")); self.assertEqual(envelope.fees_base,0)
        with self.assertRaises(AccountingObservationError): self.request("DIVIDEND",source_event_id="bad-div",amount="10",net_amount="10",attribution_policy="STRATEGY")

    def test_standalone_fee_categories_attribution_and_fill_duplicate(self):
        portfolio=self.request("FEE",source_event_id="fee",amount="12",fee_category="PLATFORM",attribution_policy="PORTFOLIO"); envelope=build_non_fill_envelope(portfolio); self.assertEqual(envelope.cash_impact_base,Decimal("-12")); self.assertEqual(envelope.fees_base,Decimal("12"))
        strategy=self.request("FEE",source_event_id="fee-s",amount="2",fee_category="TAX",attribution_policy="STRATEGY",strategy_id="alpha"); self.assertEqual(build_non_fill_envelope(strategy).strategy_id,"alpha")
        with self.assertRaises(AccountingObservationError): self.request("FEE",source_event_id="bad-fee",fee_category="MYSTERY",attribution_policy="PORTFOLIO")
        with self.assertRaises(AccountingObservationError): self.request("FEE",source_event_id="dup-fee",fee_category="REGULATORY",attribution_policy="PORTFOLIO",fill_linked=True,related_event_id="fill-1")

    def test_realised_and_valuation_fx_direction_and_reconciliation(self):
        realised=self.request("FX_ADJUSTMENT",source_event_id="fx",instrument_id="instrument:EUR-CASH",symbol="EUR-CASH",native_currency="EUR",amount="0",fx_rate_to_base="0.9",fx_source="executed-confirmation",fx_adjustment_kind="REALISED_CONVERSION",from_currency="EUR",to_currency="GBP",from_amount="100",to_amount="90",executed_fx_rate="0.9",rate_convention="TO_PER_FROM")
        self.assertEqual(build_non_fill_envelope(realised).cash_impact_base,0)
        valuation=self.request("FX_ADJUSTMENT",source_event_id="fx-v",instrument_id="instrument:EUR-CASH",symbol="EUR-CASH",native_currency="EUR",amount="0",fx_rate_to_base="0.91",fx_source="valuation-source",fx_adjustment_kind="VALUATION_ONLY",from_currency="EUR",to_currency="GBP",rate_convention="TO_PER_FROM")
        self.assertEqual(build_non_fill_envelope(valuation).observation_metadata["fx_adjustment_kind"],"VALUATION_ONLY")
        with self.assertRaises(AccountingObservationError): replace(realised,rate_convention="FROM_PER_TO").validate()
        with self.assertRaises(AccountingObservationError): replace(realised,to_amount=Decimal("91")).validate()

    def test_corporate_action_split_reverse_symbol_and_unsupported_terms(self):
        split=self.request("CORPORATE_ACTION",source_event_id="split",instrument_id="instrument:AAPL",symbol="AAPL",native_currency="USD",amount="0",fx_rate_to_base="0.8",fx_source="action-statement",corporate_action_kind="STOCK_SPLIT",action_ratio="2")
        self.assertEqual(build_non_fill_envelope(split).event_type,"CORPORATE_ACTION")
        self.assertEqual(build_non_fill_envelope(replace(split,source_event_id="reverse",corporate_action_kind="REVERSE_SPLIT",action_ratio=Decimal("0.1"))).native_price,Decimal("0.1"))
        symbol=replace(split,source_event_id="symbol",corporate_action_kind="SYMBOL_CHANGE",action_ratio=Decimal("0"),destination_instrument_id="instrument:MSFT",destination_symbol="MSFT")
        self.assertEqual(build_non_fill_envelope(symbol).observation_metadata["destination_symbol"],"MSFT")
        with self.assertRaises(AccountingObservationError): replace(split,action_ratio=Decimal("0")).validate()
        with self.assertRaises(AccountingObservationError): replace(split,source_event_id="merger",corporate_action_kind="MERGER",action_ratio=Decimal("0")).validate()
        unsupported=replace(split,source_event_id="unsupported",corporate_action_kind="OTHER_UNSUPPORTED",action_ratio=Decimal("0"))
        with self.assertRaises(AccountingObservationError): observe_non_fill_event(unsupported,store=self.store)
        self.assertFalse(self.store.records()); self.assertTrue((self.root/"invalid.jsonl").exists())

    def test_fail_closed_authority_metadata_timestamp_nan_store_and_safety(self):
        for field in ("producer_id","authority_method","source_reference"):
            with self.assertRaises(AccountingObservationError): self.request(**{field:""})
        with self.assertRaises(AccountingObservationError): self.request(effective_timestamp="2026-01-01")
        for value in ("NaN","Infinity"):
            with self.assertRaises(AccountingObservationError): self.request(amount=value)
        with self.assertRaises(Exception): self.request(native_currency="ZZZ")
        protected=[ROOT/name for name in ("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")]; before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        observe_non_fill_event(self.request(),store=self.store)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}); self.assertFalse((ROOT/"data/accounting_generations/accounting_generation.json").exists())
        self.assertEqual(producer_framework_status()["active_production_producers"],[])
        class FailedStore:
            def append(self,_envelope): raise OSError("fixture storage failure")
            def append_invalid(self,**_values): raise OSError("fixture diagnostic failure")
        with self.assertRaises(Exception): observe_non_fill_event(self.request(source_event_id="storage"),store=FailedStore())

    def test_operations_counts_and_invalid_diagnostics_are_read_only(self):
        observe_non_fill_event(self.request(),store=self.store); observe_non_fill_event(self.request("WITHDRAWAL",source_event_id="w"),store=self.store)
        before=(self.root/"envelopes.jsonl").read_bytes(); status=accounting_observation_status(self.root/"envelopes.jsonl",self.root/"invalid.jsonl")
        self.assertEqual(status["count"],2); self.assertEqual(before,(self.root/"envelopes.jsonl").read_bytes())


if __name__=="__main__": unittest.main()
