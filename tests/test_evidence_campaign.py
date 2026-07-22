from __future__ import annotations

import ast
import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from canonical_accounting.evidence_campaign import (
    EvidenceCampaignError, build_campaign, campaign_reports, close_campaign, export_campaign_bundle,
)
from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.frozen_evidence import freeze_evidence_pack, load_frozen_evidence_pack
from dashboard.evidence_campaign_reader import evidence_campaign_status

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


class EvidenceCampaignTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "evidence_campaign_tests"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.write("trade_ledger_v1.csv", "event_id,timestamp,ticker,action,shares,price,value,fees,currency\nb1,2026-01-01T00:00:00+00:00,MSFT,BUY,1,400,400,0,USD\n")
        self.write("paper_portfolio_v3.csv", "ticker,shares,entry_price\nMSFT,1,400\n")
        self.write("holdings_report.csv", "ticker,market_value\nMSFT,450\n")
        self.write("broker_account.csv", "cash\n500\n")
        evidence = build_evidence_pack(self.root, as_of=NOW)
        path = freeze_evidence_pack(evidence, (), self.root / "frozen", pack_version="1",
                                    repository_commit="abc123", created_at=NOW, evidence_cutoff=NOW)
        self.pack = load_frozen_evidence_pack(path)
        self.campaign = build_campaign(self.pack, title="Opening evidence", owner="Operations", created=NOW)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, value):
        (self.root / name).write_text(value, encoding="utf-8", newline="")

    def test_model_checklists_priority_and_unknowns_are_explicit(self):
        self.assertEqual(self.campaign.status, "OPEN")
        self.assertEqual(self.campaign.coverage, self.pack.coverage.overall)
        self.assertEqual({item.state for item in self.campaign.requirements} - {"PRESENT", "MISSING", "PARTIAL", "UNKNOWN"}, set())
        position = self.campaign.positions[0]
        self.assertEqual(position.symbol, "MSFT")
        self.assertEqual(position.strategy_attribution, "UNKNOWN")
        self.assertNotEqual(position.acquisition_fx, "COMPLETE")
        self.assertEqual(tuple(item.rank for item in self.campaign.priorities), tuple(range(1, len(self.campaign.priorities) + 1)))
        self.assertTrue(self.campaign.remaining_unknowns)

    def test_readiness_explains_not_ready_without_estimation(self):
        self.assertEqual(self.campaign.readiness.state, "NOT_READY")
        self.assertTrue(any("Cash statements" in reason for reason in self.campaign.readiness.reasons))
        self.assertTrue(any("MSFT" in reason for reason in self.campaign.readiness.reasons))
        self.assertEqual(self.campaign.estimated_remaining_work, len(self.campaign.priorities))

    def test_closed_campaign_is_immutable_and_cannot_close_twice(self):
        closed = close_campaign(self.campaign, closed_at=NOW.replace(hour=13))
        self.assertEqual(closed.status, "CLOSED")
        with self.assertRaisesRegex(EvidenceCampaignError, "immutable"):
            close_campaign(closed, closed_at=NOW.replace(hour=14))

    def test_reporting_and_export_are_deterministic_and_hash_bound(self):
        reports = campaign_reports(self.campaign)
        self.assertEqual(set(reports), {"campaign_report", "coverage_report", "evidence_inventory",
            "outstanding_requirements", "resolved_evidence", "remaining_unknowns", "critical_blockers", "bundle_hash"})
        first = export_campaign_bundle(self.campaign)
        self.assertEqual(first, export_campaign_bundle(self.campaign))
        payload = json.loads(first)
        self.assertEqual(payload["bundle_hash"], self.campaign.bundle_hash)
        self.assertEqual(len(payload["export_hash"]), 64)

    def test_dashboard_reader_is_read_only_and_fails_closed(self):
        before = {path: path.read_bytes() for path in (self.root / "frozen").rglob("*") if path.is_file()}
        status = evidence_campaign_status(self.root / "frozen")
        self.assertTrue(status["campaign_id"].startswith("campaign-"))
        self.assertEqual(status["readiness"], "NOT_READY")
        self.assertEqual(before, {path: path.read_bytes() for path in (self.root / "frozen").rglob("*") if path.is_file()})
        absent = evidence_campaign_status(self.root / "absent")
        self.assertEqual(absent["readiness"], "NOT_READY")

    def test_module_has_no_forbidden_accounting_dependencies(self):
        source = (ROOT / "canonical_accounting" / "evidence_campaign.py").read_text(encoding="utf-8")
        imports = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)}
        forbidden = {"canonical_accounting.opening_snapshot", "canonical_accounting.generation",
                     "canonical_accounting.migration_approval", "canonical_accounting.ledger"}
        self.assertFalse(imports & forbidden)
        for phrase in ("estimate_fifo", "estimate_acquisition_fx", "create_candidate", "publish_generation"):
            self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
