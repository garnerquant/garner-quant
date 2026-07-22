from __future__ import annotations

import json
import shutil
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.evidence_reconciliation import (
    SOURCE_ADAPTERS, AuthoritativeImportRequest, acquire_authoritative_evidence,
    reconcile_cash_evidence, reconcile_evidence, reconstruct_evidenced_lot_links,
)
from canonical_accounting.frozen_evidence import (
    FrozenEvidenceError, NormalizedEvidenceRecord, export_frozen_evidence_bundle,
    freeze_evidence_pack, load_current_frozen_evidence, load_frozen_evidence_history,
)
from canonical_accounting.migration_approval import build_migration_approval_pack
from dashboard.opening_evidence_reader import opening_evidence_status

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


class AcquisitionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "evidence_reconciliation_tests"
        shutil.rmtree(self.root, ignore_errors=True); self.root.mkdir(parents=True)
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\nb1,2026-01-01T00:00:00+00:00,AAPL,BUY,1,200,200,0,USD\n")
        self.write("paper_portfolio_v3.csv", "ticker,shares,entry_price\nAAPL,1,200\n")
        self.write("holdings_report.csv", "ticker,market_value\nAAPL,250\n")
        self.write("broker_account.csv", "cash\n750\n")
        self.write("broker.pdf", "broker authoritative bytes"); self.write("confirmation.pdf", "confirmation authoritative bytes")
        self.evidence = build_evidence_pack(self.root, as_of=NOW)
        self.approval = build_migration_approval_pack(self.evidence, repository_commit="abc", created_at=NOW)
        self.gap = self.evidence.gaps[0]
        self.trade = NormalizedEvidenceRecord("trade-1", "TRADE", NOW, "USD", quantity="1", price="200", fields=(("symbol", "AAPL"),))

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)
    def write(self, name, text): (self.root / name).write_text(text, encoding="utf-8", newline="")
    def request(self, source, identifier, adapter="BROKER_TRADE_STATEMENT", record=None):
        return AuthoritativeImportRequest(adapter, source, identifier, NOW, NOW, NOW, NOW, "HIGH", "VERIFIED",
            (self.gap.gap_id,), associated_positions=("AAPL",), associated_cash_flows=("cash-1",),
            associated_lots=("b1",), normalized_records=(record or self.trade,))
    def collect(self, file, request):
        return acquire_authoritative_evidence(self.root / file, request, gap_ids={gap.gap_id for gap in self.evidence.gaps})

    def test_all_authoritative_source_adapters_are_explicit(self):
        self.assertEqual(set(SOURCE_ADAPTERS), {"BROKER_TRADE_STATEMENT", "BROKER_ACCOUNT_STATEMENT", "CASH_STATEMENT",
            "DIVIDEND_STATEMENT", "FX_CONFIRMATION", "CORPORATE_ACTION_NOTICE", "TAX_DOCUMENT", "MANUAL_OPERATOR_EVIDENCE"})
        for adapter in SOURCE_ADAPTERS:
            request = self.request("SOURCE-" + adapter, "id-" + adapter.lower().replace("_", "-"), adapter)
            self.assertEqual(request.to_document_request().document_type, SOURCE_ADAPTERS[adapter])

    def test_import_records_hashes_dates_coverage_and_identity(self):
        item = self.collect("broker.pdf", self.request("BROKER", "broker-1")).item
        self.assertEqual(item.checksum, item.document_hash); self.assertEqual(item.issue_date, NOW)
        self.assertEqual(item.import_timestamp, NOW); self.assertEqual(item.coverage_start, NOW)
        self.assertEqual(item.source, "BROKER"); self.assertEqual(item.identifier, "broker-1")

    def test_exact_partial_conflict_and_unknown_are_deterministic(self):
        broker = self.collect("broker.pdf", self.request("BROKER", "broker-1"))
        confirmation = self.collect("confirmation.pdf", self.request("CONFIRMATION", "confirmation-1"))
        exact = reconcile_evidence(self.evidence, (broker, confirmation), created_at=NOW, evidence_cutoff=NOW)
        self.assertEqual(exact.results[0].state, "EXACT_MATCH"); self.assertEqual(exact.gaps[0].state, "RESOLVED")
        partial = reconcile_evidence(self.evidence, (broker,), created_at=NOW, evidence_cutoff=NOW)
        self.assertEqual(partial.results[0].state, "PARTIAL_MATCH"); self.assertEqual(partial.gaps[0].state, "OPEN")
        changed = replace(self.trade, price="201")
        conflict = reconcile_evidence(self.evidence, (broker, self.collect("confirmation.pdf", self.request("CONFIRMATION", "confirmation-1", record=changed))), created_at=NOW, evidence_cutoff=NOW)
        self.assertEqual(conflict.results[0].state, "CONFLICT"); self.assertEqual(conflict.conflicts, 1)
        unknown = replace(self.trade, unknown_fields=("settlement_fx",))
        report = reconcile_evidence(self.evidence, (self.collect("broker.pdf", self.request("BROKER", "broker-2", record=unknown)),), created_at=NOW, evidence_cutoff=NOW)
        self.assertEqual(report.results[0].state, "UNKNOWN"); self.assertIn("settlement_fx", report.unknown_fields)

    def test_lot_and_cash_links_require_exact_explicit_associations(self):
        rows = (self.collect("broker.pdf", self.request("BROKER", "broker-1")), self.collect("confirmation.pdf", self.request("CONFIRMATION", "confirmation-1")))
        report = reconcile_evidence(self.evidence, rows, created_at=NOW, evidence_cutoff=NOW)
        self.assertEqual(reconstruct_evidenced_lot_links(report), (("trade-1", ("b1",), ("cash-1",)),))
        self.assertEqual(reconcile_cash_evidence(report), ())

    def test_new_pack_preserves_previous_and_trends_reconciled_coverage(self):
        store = self.root / "packs"
        first_path = freeze_evidence_pack(self.evidence, (), store, pack_version="1", repository_commit="abc", created_at=NOW,
            evidence_cutoff=NOW, approval_pack=self.approval)
        first = load_current_frozen_evidence(store)
        with self.assertRaisesRegex(FrozenEvidenceError, "bind the current"):
            freeze_evidence_pack(self.evidence, (), store, pack_version="2", repository_commit="abc", created_at=NOW,
                evidence_cutoff=NOW, approval_pack=self.approval)
        rows = (self.collect("broker.pdf", self.request("BROKER", "broker-1")), self.collect("confirmation.pdf", self.request("CONFIRMATION", "confirmation-1")))
        report = reconcile_evidence(self.evidence, rows, created_at=NOW, evidence_cutoff=NOW)
        freeze_evidence_pack(self.evidence, rows, store, pack_version="2", repository_commit="abc", created_at=NOW,
            evidence_cutoff=NOW, approval_pack=self.approval, reconciliation_report=report, previous_pack=first)
        history = load_frozen_evidence_history(store); second = history[-1]
        self.assertEqual(len(history), 2); self.assertEqual(second.previous_pack_id, first.pack_id)
        self.assertGreater(second.coverage.position, first.coverage.position)
        self.assertEqual(second.reconciliation_report["conflicts"], 0)
        status = opening_evidence_status(store)
        self.assertEqual(status["previous_pack_id"], first.pack_id); self.assertEqual(status["resolved_gaps"], 1)

    def test_unreconciled_single_source_does_not_improve_coverage(self):
        row = self.collect("broker.pdf", self.request("BROKER", "broker-1"))
        report = reconcile_evidence(self.evidence, (row,), created_at=NOW, evidence_cutoff=NOW)
        path = freeze_evidence_pack(self.evidence, (row,), self.root / "packs", pack_version="1", repository_commit="abc",
            created_at=NOW, evidence_cutoff=NOW, approval_pack=self.approval, reconciliation_report=report)
        self.assertEqual(load_current_frozen_evidence(self.root / "packs").coverage.position, 0)
        self.assertTrue(path.exists())

    def test_duplicate_tamper_chronology_and_unsupported_adapter_fail_closed(self):
        with self.assertRaisesRegex(FrozenEvidenceError, "chronology"):
            replace(self.request("BROKER", "broker-1"), import_timestamp=NOW.replace(year=2025)).to_document_request()
        with self.assertRaisesRegex(FrozenEvidenceError, "unsupported"):
            replace(self.request("BROKER", "broker-1"), adapter_type="UNKNOWN").to_document_request()
        row = self.collect("broker.pdf", self.request("BROKER", "broker-1")); changed = replace(row, content=b"tampered")
        with self.assertRaisesRegex(FrozenEvidenceError, "content changed"):
            freeze_evidence_pack(self.evidence, (changed,), self.root / "packs", pack_version="1", repository_commit="abc", created_at=NOW, evidence_cutoff=NOW)

    def test_export_contains_reports_and_is_deterministic(self):
        rows = (self.collect("broker.pdf", self.request("BROKER", "broker-1")), self.collect("confirmation.pdf", self.request("CONFIRMATION", "confirmation-1")))
        report = reconcile_evidence(self.evidence, rows, created_at=NOW, evidence_cutoff=NOW)
        path = freeze_evidence_pack(self.evidence, rows, self.root / "packs", pack_version="1", repository_commit="abc", created_at=NOW,
            evidence_cutoff=NOW, approval_pack=self.approval, reconciliation_report=report)
        one = export_frozen_evidence_bundle(path); two = export_frozen_evidence_bundle(path)
        self.assertEqual(one, two); payload = json.loads(one)
        self.assertIn("reconciliation_report", payload); self.assertIn("coverage_change", payload); self.assertIn("export_hash", payload)
        self.assertFalse((self.root / "data/accounting_generations").exists())
        self.assertFalse((self.root / "data/opening_snapshot_candidates").exists())


if __name__ == "__main__": unittest.main()
