from __future__ import annotations

import shutil
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

from research.continuous_improvement.evidence import build_evidence_snapshot
from research.continuous_improvement.features import feature_catalogue

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 20, tzinfo=timezone.utc)


class ContinuousResearchEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "continuous_research_evidence"
        shutil.rmtree(self.root, ignore_errors=True); (self.root / "data").mkdir(parents=True)
        (self.root / "trade_audit_trail.csv").write_text(
            "symbol,open_time,close_time,pnl_pct,strategy,close_reason,entry_event_id,exit_event_id\n"
            "AAA,2026-01-01T10:00:00+00:00,2026-01-03T10:00:00+00:00,2.5,Momentum,TAKE PROFIT,b1,s1\n"
            "FUTURE,2026-08-01T10:00:00+00:00,2026-08-02T10:00:00+00:00,9,Momentum,EXIT,b2,s2\n",
            encoding="utf-8")
        (self.root / "trade_ledger_v1.csv").write_text(
            "event_id,timestamp,ticker,action,shares,price,fees,source,mode,status,reason\n"
            "b1,2026-01-01T10:00:00+00:00,AAA,BUY,1,100,0,fixture,paper,RECORDED,ENTRY\n", encoding="utf-8")
        (self.root / "data/runtime_decision_trace.json").write_text(
            '{"decisions":[{"timestamp":"2026-01-02T10:00:00+00:00","ticker":"BBB","signal":"BUY","portfolio_decision":"NO_TRADE","reason":"trading_disabled","details":{"risk_status":"MONITOR_ONLY"}}]}', encoding="utf-8")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def test_snapshot_is_deterministic_immutable_and_provenanced(self):
        first = build_evidence_snapshot(self.root, cutoff=NOW, created_at=NOW)
        second = build_evidence_snapshot(self.root, cutoff=NOW, created_at=NOW)
        self.assertEqual(first, second); self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(len(first.records), 3)
        self.assertTrue(all(item.source_artifact and item.source_record_identifier and item.content_hash for item in first.records))
        with self.assertRaises(FrozenInstanceError): first.snapshot_id = "changed"

    def test_future_records_are_excluded_and_unknowns_stay_explicit(self):
        snapshot = build_evidence_snapshot(self.root, cutoff=NOW, created_at=NOW)
        self.assertNotIn("FUTURE", str(snapshot.records))
        self.assertIn("market_regime", snapshot.unsupported_fields)
        completed = next(item for item in snapshot.records if item.evidence_type == "COMPLETED_TRADE")
        self.assertNotIn("market_regime", dict(completed.fields))

    def test_catalogue_is_controlled_versioned_and_leakage_aware(self):
        catalogue = feature_catalogue()
        self.assertEqual(len(catalogue), 10)
        self.assertEqual(len({item.feature_name for item in catalogue}), 10)
        self.assertTrue(all(item.calculation_version and item.look_ahead_safety_rule and item.minimum_evidence_requirement > 0 for item in catalogue))
        self.assertEqual(next(item for item in catalogue if item.feature_name == "risk_rejected_outcome").leakage_risk, "HIGH")


if __name__ == "__main__": unittest.main()
