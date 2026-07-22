from __future__ import annotations

import hashlib
import shutil
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

from canonical_accounting.evidence_pack import EvidencePackError, build_evidence_pack

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


class EvidencePackTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "evidence_pack_tests"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\n"
                   "buy-1,2026-07-01T10:00:00+00:00,AAPL,BUY,2,200,400,1,USD\n"
                   "sell-1,2026-07-02T10:00:00+00:00,AAPL,SELL,1,210,210,1,USD\n")
        self.write("paper_portfolio_v3.csv", "ticker,entry_date,entry_price,shares,position_value\nAAPL,2026-07-01,200,1,200\n")
        self.write("holdings_report.csv", "date,ticker,shares,entry_price,current_price,market_value\n2026-07-22,AAPL,1,200,220,220\n")
        self.write("broker_account.csv", "cash,buying_power,positions_value,portfolio_value\n800,800,220,1020\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")

    def pack(self):
        return build_evidence_pack(self.root, as_of=NOW)

    def test_deterministic_inventory_serialization_and_hashes(self):
        first = self.pack(); second = self.pack()
        self.assertEqual(first.serialize(), second.serialize())
        self.assertEqual(first.pack_hash, second.pack_hash)
        self.assertEqual(first.gap_register_hash, second.gap_register_hash)
        self.assertEqual([item.logical_name for item in first.sources], sorted(item.logical_name for item in first.sources))
        self.assertEqual(len(first.sources), 13)

    def test_position_lot_fx_and_strategy_gaps_are_fail_closed(self):
        pack = self.pack()
        self.assertEqual(pack.positions[0].confidence, "PARTIAL")
        self.assertIsNone(pack.positions[0].strategy_evidence)
        self.assertEqual(pack.lots[0].missing, ("strategy_id", "acquisition_fx_source", "acquisition_fx_timestamp", "quote_convention"))
        self.assertEqual(pack.fx[0].classification, "MISSING")
        self.assertEqual(pack.coverage.strategy, 0)
        self.assertEqual(pack.coverage.fx, 0)
        self.assertEqual(pack.coverage.fifo, 0)
        self.assertEqual(pack.opening_snapshot_readiness, "NOT_READY")
        self.assertEqual(pack.replay_readiness, "NOT_READY")

    def test_gap_register_contains_required_blockers(self):
        gaps = {item.category: item for item in self.pack().gaps}
        self.assertTrue({"STRATEGY_ATTRIBUTION", "ACQUISITION_FX", "CASH_PROVENANCE", "NON_FILL_HISTORY"} <= set(gaps))
        self.assertTrue(all(item.blocks_opening_snapshot and item.blocks_replay for item in gaps.values()))
        self.assertTrue(all(item.operator_action_required for item in gaps.values()))

    def test_non_fill_coverage_does_not_infer_history(self):
        coverage = self.pack().non_fill
        self.assertEqual({item.category for item in coverage}, {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "FEE", "TAX_WITHHOLDING", "FX_ADJUSTMENT", "CORPORATE_ACTION"})
        self.assertTrue(all(item.status == "MISSING" and item.evidence_count == 0 for item in coverage))

    def test_conflicting_duplicate_and_orphan_sell_rejected(self):
        original = (self.root / "trade_ledger_v1.csv").read_text(encoding="utf-8")
        self.write("trade_ledger_v1.csv", original + "buy-1,2026-07-03T10:00:00+00:00,AAPL,BUY,3,200,600,1,USD\n")
        with self.assertRaisesRegex(EvidencePackError, "conflicting duplicate"):
            self.pack()
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\nsell-only,2026-07-01T10:00:00+00:00,AAPL,SELL,1,200,200,0,USD\n")
        with self.assertRaisesRegex(EvidencePackError, "orphan sell"):
            self.pack()

    def test_identical_duplicate_is_idempotent(self):
        path = self.root / "trade_ledger_v1.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines + [lines[1]]) + "\n", encoding="utf-8")
        self.assertEqual(len(self.pack().lots), 1)

    def test_missing_lots_marks_position_unproven(self):
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\n")
        pack = self.pack()
        self.assertEqual(pack.positions[0].confidence, "UNPROVEN")
        self.assertIn("POSITION_RECONCILIATION", {item.category for item in pack.gaps})

    def test_models_are_immutable_and_as_of_is_aware(self):
        pack = self.pack()
        with self.assertRaises(FrozenInstanceError):
            pack.replay_readiness = "READY"
        with self.assertRaises(EvidencePackError):
            build_evidence_pack(self.root, as_of=NOW.replace(tzinfo=None))

    def test_content_change_changes_hash(self):
        before = self.pack().pack_hash
        self.write("holdings_report.csv", "date,ticker,shares,entry_price,current_price,market_value\n2026-07-22,AAPL,1,200,221,221\n")
        self.assertNotEqual(before, self.pack().pack_hash)

    def test_build_is_read_only_and_creates_no_accounting_artifacts(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        self.pack()
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / "data/accounting_generations/accounting_generation.json").exists())
        self.assertFalse((self.root / "data/opening_snapshot_candidates").exists())


if __name__ == "__main__":
    unittest.main()
