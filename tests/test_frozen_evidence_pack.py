from __future__ import annotations

import json
import shutil
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.frozen_evidence import (
    EvidenceDocumentRequest, FrozenEvidenceError, NormalizedEvidenceRecord,
    collect_evidence, export_frozen_evidence_bundle, freeze_evidence_pack,
    load_current_frozen_evidence, load_frozen_evidence_pack,
)
from canonical_accounting.migration_approval import build_migration_approval_pack
from dashboard.migration_approval_reader import migration_approval_status
from dashboard.opening_evidence_reader import opening_evidence_status
from dashboard.review_workflow_reader import review_workflow_status

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


class FrozenEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "frozen_evidence_tests"
        shutil.rmtree(self.root, ignore_errors=True); self.root.mkdir(parents=True)
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\nb1,2026-01-01T00:00:00+00:00,AAPL,BUY,1,200,200,0,USD\n")
        self.write("paper_portfolio_v3.csv", "ticker,shares,entry_price\nAAPL,1,200\n")
        self.write("holdings_report.csv", "ticker,market_value\nAAPL,250\n")
        self.write("broker_account.csv", "cash\n750\n")
        self.write("statement.pdf", "authoritative statement bytes")
        self.evidence = build_evidence_pack(self.root, as_of=NOW)
        self.approval = build_migration_approval_pack(self.evidence, repository_commit="abc123", created_at=NOW)
        gap = self.evidence.gaps[0]
        record = NormalizedEvidenceRecord("cash-1", "CASH_MOVEMENT", NOW, "GBP", "100", unknown_fields=("counterparty",))
        self.request = EvidenceDocumentRequest("BROKER", "statement-1", NOW, "BROKER_STATEMENT", NOW, NOW,
            "HIGH", "VERIFIED", (gap.gap_id,), associated_positions=("AAPL",), associated_lots=("b1",), normalized_records=(record,))
        self.request = replace(self.request, issue_date=NOW, import_timestamp=NOW)
        self.collected = collect_evidence(self.root / "statement.pdf", self.request, gap_ids={g.gap_id for g in self.evidence.gaps})
        self.store = self.root / "frozen"

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)
    def write(self, name, value): (self.root / name).write_text(value, encoding="utf-8", newline="")
    def freeze(self, destination=None, version="1", collection=None, hook=None):
        return freeze_evidence_pack(self.evidence, (self.collected,) if collection is None else collection,
            destination or self.store, pack_version=version, repository_commit="abc123", created_at=NOW,
            evidence_cutoff=NOW, approval_pack=self.approval, failure_hook=hook)

    def test_creation_load_hash_and_export_are_stable(self):
        path = self.freeze(); pack = load_frozen_evidence_pack(path)
        self.assertEqual(pack, load_current_frozen_evidence(self.store))
        self.assertEqual(pack.evidence_hash, self.evidence.pack_hash)
        first = export_frozen_evidence_bundle(path); self.assertEqual(first, export_frozen_evidence_bundle(path))
        payload = json.loads(first); self.assertEqual(payload["export_hash"], json.loads(first)["export_hash"])
        with self.assertRaises(FrozenInstanceError): pack.pack_version = "2"

    def test_reproducible_pack_identity_and_version_is_immutable(self):
        first = load_frozen_evidence_pack(self.freeze(self.root / "one"))
        second = load_frozen_evidence_pack(self.freeze(self.root / "two"))
        self.assertEqual((first.pack_id, first.bundle_hash), (second.pack_id, second.bundle_hash))
        self.freeze()
        with self.assertRaisesRegex(FrozenEvidenceError, "version already exists"): self.freeze()
        with self.assertRaisesRegex(FrozenEvidenceError, "version already exists"): self.freeze(collection=())

    def test_duplicate_is_idempotent_and_conflict_fails_closed(self):
        path = self.freeze(collection=(self.collected, self.collected))
        self.assertEqual(len(load_frozen_evidence_pack(path).evidence_inventory), 1)
        conflict = replace(self.collected, content=b"changed")
        with self.assertRaisesRegex(FrozenEvidenceError, "content changed"): self.freeze(self.root / "conflict", collection=(conflict,))

    def test_unknowns_and_unverified_evidence_do_not_become_coverage(self):
        self.assertEqual(self.collected.item.normalized_records[0].unknown_fields, ("counterparty",))
        unverified = replace(self.collected, item=replace(self.collected.item, verification_status="UNVERIFIED"))
        pack = load_frozen_evidence_pack(self.freeze(self.root / "unknown", collection=(unverified,)))
        self.assertEqual(pack.coverage.position, 0); self.assertEqual(pack.coverage.cash, 0)
        self.assertGreater(pack.coverage.unknown, 0)

    def test_proposals_link_only_explicit_gap_evidence(self):
        pack = load_frozen_evidence_pack(self.freeze())
        linked = dict(pack.proposal_evidence_links)
        self.assertTrue(any("statement-1" in values for values in linked.values()))
        self.assertTrue(pack.missing_evidence)

    def test_invalid_requests_and_cutoff_fail_closed(self):
        with self.assertRaises(FrozenEvidenceError): collect_evidence(self.root / "statement.pdf", replace(self.request, linked_gap_ids=("unknown",)), gap_ids={g.gap_id for g in self.evidence.gaps})
        with self.assertRaisesRegex(FrozenEvidenceError, "cut-off differ"):
            freeze_evidence_pack(self.evidence, (), self.store, pack_version="1", repository_commit="abc", created_at=NOW,
                evidence_cutoff=NOW.replace(hour=13))

    def test_artifact_tampering_and_interrupted_freeze_are_rejected(self):
        path = self.freeze(); (path / "documents" / "statement-1.pdf").write_bytes(b"tampered")
        with self.assertRaisesRegex(FrozenEvidenceError, "artifact is invalid"): load_frozen_evidence_pack(path)
        def fail(stage, _path):
            if stage == "after_artifacts": raise OSError("injected")
        with self.assertRaises(OSError): self.freeze(self.root / "failed", hook=fail)
        self.assertFalse(any((self.root / "failed").glob("*")))

    def test_dashboard_consumes_frozen_pack_without_regeneration(self):
        path = self.freeze(); before = {p: p.read_bytes() for p in path.rglob("*") if p.is_file()}
        opening = opening_evidence_status(self.store); migration = migration_approval_status(self.store); review = review_workflow_status(self.store)
        self.assertEqual(opening["pack_id"], load_frozen_evidence_pack(path).pack_id)
        self.assertEqual(migration["status"], "PENDING_REVIEW"); self.assertEqual(review["status"], "PENDING_REVIEW")
        self.assertEqual(before, {p: p.read_bytes() for p in path.rglob("*") if p.is_file()})
        self.assertFalse((self.root / "data/accounting_generations").exists())
        self.assertFalse((self.root / "data/opening_snapshot_candidates").exists())

    def test_no_pack_fails_closed(self):
        status = opening_evidence_status(self.root / "absent")
        self.assertEqual(status["status"], "NOT_FROZEN"); self.assertEqual(status["opening_snapshot_readiness"], "NOT_READY")


if __name__ == "__main__": unittest.main()
