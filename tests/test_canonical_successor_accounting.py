from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from canonical_accounting.dual_run import compare_legacy_to_canonical
from canonical_accounting.events import AccountingEvent, AccountingEventError
from canonical_accounting.generation import load_generation
from canonical_accounting.successor import (
    SuccessorGenerationError, SuccessorGenerationWriter, accounting_transaction_status,
    create_transactional_genesis, load_transactional_generation, validate_lineage,
)
from dashboard.accounting_reader import load_dashboard_accounting_status
from risk_engine.integration import _canonical_state


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)


class CanonicalSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "canonical_successor_tests"
        shutil.rmtree(self.root, ignore_errors=True)
        self.generation_root = self.root / "generations"
        genesis = self.generation_root / "g0"
        create_transactional_genesis(genesis, generation_id="g0", timestamp=NOW, legacy_root=ROOT)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "accounting_generation.json").write_text(json.dumps({"generation_id": "g0"}), encoding="utf-8")
        self.counter = 0

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def current(self):
        return json.loads((self.root / "accounting_generation.json").read_text(encoding="utf-8"))["generation_id"]

    def event(self, event_type, *, event_id=None, strategy="alpha", instrument="GBP-CASH",
              currency="GBP", amount="1", quantity="0", fx="1", metadata=None):
        self.counter += 1
        return AccountingEvent.create(
            event_id=event_id or f"event-{self.counter}", event_type=event_type,
            timestamp=NOW + timedelta(minutes=self.counter), strategy_id=strategy,
            instrument=instrument, currency=currency, amount=amount, quantity=quantity,
            reference_generation=self.current(), correlation_id=f"corr-{self.counter}", source="unit-test",
            fx_rate_to_base=fx, fx_timestamp=NOW if currency != "GBP" else None,
            fx_source="fixture" if currency != "GBP" else "identity", metadata=metadata or {},
        )

    def publish(self, event, valuations=None, writer=None):
        return (writer or SuccessorGenerationWriter(self.root)).transact(event, valuations=valuations or {}, publish=True)

    def test_multiple_generations_currencies_fees_cashflows_and_exits(self):
        valuations = {"IUSA.L": {"price": "5100", "fx_rate_to_base": "1"}}
        buy_gbp = self.publish(self.event("BUY_FILL", instrument="IUSA.L", amount="5000", quantity="10"), valuations)
        self.assertEqual(buy_gbp.snapshot.cash, Decimal("9500"))
        self.assertEqual(buy_gbp.snapshot.positions[0].base_market_value, Decimal("510"))

        valuations["AAPL"] = {"price": "105", "fx_rate_to_base": "0.8", "fx_timestamp": NOW.isoformat()}
        buy_usd = self.publish(self.event("BUY_FILL", strategy="beta", instrument="AAPL", currency="USD", amount="100", quantity="10", fx="0.8"), valuations)
        self.assertEqual(buy_usd.snapshot.cash, Decimal("8700"))
        fee = self.publish(self.event("FEE", strategy="beta", instrument="AAPL", currency="USD", amount="10", fx="0.8"), valuations)
        self.assertEqual(fee.snapshot.fees, Decimal("8.0"))
        eur = self.publish(self.event("DEPOSIT", currency="EUR", amount="100", fx="0.9"), valuations)
        self.assertEqual(eur.snapshot.external_cash_flow, Decimal("10090.0"))
        dividend = self.publish(self.event("DIVIDEND", strategy="beta", instrument="AAPL", currency="USD", amount="5", fx="0.8"), valuations)
        self.assertEqual(dividend.snapshot.dividends, Decimal("4.0"))
        withdrawn = self.publish(self.event("WITHDRAWAL", amount="50"), valuations)
        self.assertEqual(withdrawn.snapshot.external_cash_flow, Decimal("10040.0"))

        valuations["AAPL"] = {"price": "120", "fx_rate_to_base": "0.8", "fx_timestamp": NOW.isoformat()}
        partial = self.publish(self.event("SELL_FILL", strategy="beta", instrument="AAPL", currency="USD", amount="120", quantity="4", fx="0.8"), valuations)
        self.assertEqual(next(item for item in partial.snapshot.positions if item.instrument == "AAPL").quantity, Decimal("6"))
        self.assertEqual(partial.snapshot.realised_pnl, Decimal("64.0"))
        self.publish(self.event("FX_ADJUSTMENT", strategy="ACCOUNT", instrument="USD-CASH", currency="USD", amount="0.82", fx="0.82"), valuations)
        fx = self.publish(self.event("FX_ADJUSTMENT", strategy="ACCOUNT", instrument="USD-CASH", currency="USD", amount="0.85", fx="0.85"), valuations)
        self.assertNotEqual(fx.snapshot.fx_effects, Decimal("0"))
        split = self.publish(self.event("CORPORATE_ACTION", instrument="IUSA.L", amount="2", metadata={"action": "SPLIT"}), valuations)
        self.assertEqual(next(item for item in split.snapshot.positions if item.instrument == "IUSA.L").quantity, Decimal("20"))
        valuations["AAPL"] = {"price": "110", "fx_rate_to_base": "0.85", "fx_timestamp": NOW.isoformat()}
        complete = self.publish(self.event("SELL_FILL", strategy="beta", instrument="AAPL", currency="USD", amount="110", quantity="6", fx="0.85"), valuations)
        self.assertNotIn("AAPL", {item.instrument for item in complete.snapshot.positions})
        self.assertEqual(complete.snapshot.strategy_exposure["alpha"].position_count, 1)
        self.assertEqual(len(validate_lineage(self.root, complete.generation_id)), self.counter + 1)

    def test_duplicate_replay_and_conflicting_duplicate(self):
        event = self.event("DEPOSIT", event_id="idempotent", amount="10")
        first = self.publish(event)
        generations = set(path.name for path in self.generation_root.iterdir())
        replay = SuccessorGenerationWriter(self.root).transact(event, publish=True)
        self.assertTrue(replay.duplicate)
        self.assertEqual(replay.generation_id, first.generation_id)
        self.assertEqual(generations, set(path.name for path in self.generation_root.iterdir()))
        conflicting = AccountingEvent.create(**{**event.to_dict(), "amount": "11"})
        with self.assertRaises(SuccessorGenerationError):
            SuccessorGenerationWriter(self.root).transact(conflicting, publish=True)

    def test_prepared_successor_is_inert_until_atomic_publication(self):
        parent = self.current()
        writer = SuccessorGenerationWriter(self.root)
        prepared = writer.transact(self.event("DEPOSIT", amount="10"), publish=False)
        self.assertFalse(prepared.published)
        self.assertEqual(self.current(), parent)
        load_transactional_generation(prepared.path, expected_id=prepared.generation_id)
        published = writer.publish_prepared(prepared.generation_id)
        self.assertTrue(published.published)
        self.assertEqual(self.current(), prepared.generation_id)
        with self.assertRaises(SuccessorGenerationError):
            writer.publish_prepared(prepared.generation_id)

    def test_same_instrument_fifo_isolated_by_authoritative_strategy(self):
        valuations = {"BTC-GBP": {"price": "110"}}
        self.publish(self.event("BUY_FILL", strategy="alpha", instrument="BTC-GBP", amount="100", quantity="1"), valuations)
        self.publish(self.event("BUY_FILL", strategy="beta", instrument="BTC-GBP", amount="105", quantity="1"), valuations)
        with self.assertRaises(SuccessorGenerationError):
            self.publish(self.event("SELL_FILL", strategy="gamma", instrument="BTC-GBP", amount="110", quantity="1"), valuations)
        sold = self.publish(self.event("SELL_FILL", strategy="beta", instrument="BTC-GBP", amount="110", quantity="1"), valuations)
        self.assertEqual(sold.snapshot.realised_pnl, Decimal("5"))
        self.assertEqual(sold.snapshot.positions[0].strategy_ids, ("alpha",))
        self.assertEqual(set(sold.snapshot.strategy_exposure), {"alpha"})

    def test_crash_before_and_after_generation_publication_preserves_pointer(self):
        parent = self.current(); event = self.event("DEPOSIT", amount="10")
        def fail_before(phase, _path):
            if phase == "after_validation": raise RuntimeError("fixture crash")
        with self.assertRaises(SuccessorGenerationError):
            self.publish(event, writer=SuccessorGenerationWriter(self.root, failure_hook=fail_before))
        self.assertEqual(self.current(), parent)
        self.assertFalse(any(path.name.startswith(".staging-") for path in self.root.iterdir()))
        def fail_after(phase, _path):
            if phase == "after_generation_publish": raise RuntimeError("fixture crash")
        with self.assertRaises(SuccessorGenerationError):
            self.publish(event, writer=SuccessorGenerationWriter(self.root, failure_hook=fail_after))
        self.assertEqual(self.current(), parent)
        self.assertEqual(load_transactional_generation(self.generation_root / parent)[1].generation_id, parent)

    def test_concurrent_readers_observe_only_complete_generations(self):
        observed, errors, stop = [], [], threading.Event()
        def reader():
            while not stop.is_set():
                try:
                    generation_id = self.current()
                    bundle, snapshot, _ = load_transactional_generation(self.generation_root / generation_id, expected_id=generation_id)
                    observed.append((bundle.generation_id, snapshot.total_equity))
                except Exception as exc: errors.append(str(exc))
        threads = [threading.Thread(target=reader) for _ in range(3)]
        for thread in threads: thread.start()
        try:
            self.publish(self.event("DEPOSIT", amount="25"))
            time.sleep(0.03)
        finally:
            stop.set()
            for thread in threads: thread.join()
        self.assertFalse(errors)
        self.assertTrue(observed)
        self.assertTrue({item[0] for item in observed}.issubset({"g0", self.current()}))

    def test_hash_snapshot_reader_risk_and_dual_run_consistency(self):
        result = self.publish(self.event("BUY_FILL", instrument="BTC-GBP", amount="100", quantity="2"), {"BTC-GBP": {"price": "110"}})
        dashboard = load_dashboard_accounting_status(self.root)
        self.assertEqual(dashboard.state, "active")
        self.assertIsNotNone(dashboard.bundle.snapshot)
        state = _canonical_state(self.root)
        self.assertEqual(state[-1]["alpha"], Decimal("220"))
        legacy = {"cash": "9800", "realised_pnl": "0", "unrealised_pnl": "20", "total_equity": "10020",
                  "gross_exposure": "220", "net_exposure": "220", "positions": {"BTC-GBP": "2"}}
        comparison = compare_legacy_to_canonical(legacy, result.snapshot)
        self.assertTrue(comparison["matches"])
        self.assertEqual(comparison["automatic_corrections"], 0)
        snapshot_path = result.path / "canonical_snapshot.json"
        snapshot_path.write_text(snapshot_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaises(SuccessorGenerationError):
            load_transactional_generation(result.path)

    def test_event_validation_and_read_only_operations_status(self):
        with self.assertRaises(AccountingEventError):
            self.event("WITHDRAWAL", amount="0")
        before = hashlib.sha256((self.root / "accounting_generation.json").read_bytes()).hexdigest()
        status = accounting_transaction_status(self.root)
        self.assertEqual(status["pointer_status"], "VALID")
        self.assertEqual(status["lineage_health"], "VALID (1 generations)")
        self.assertEqual(before, hashlib.sha256((self.root / "accounting_generation.json").read_bytes()).hexdigest())
        (self.root / "accounting_generation.json").write_text(json.dumps({"generation_id": "../g0"}), encoding="utf-8")
        with self.assertRaises(SuccessorGenerationError):
            SuccessorGenerationWriter(self.root).transact(self.event("DEPOSIT", amount="1"), publish=False)


if __name__ == "__main__":
    unittest.main()
