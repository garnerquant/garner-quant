from __future__ import annotations
import shutil,unittest
from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
from pathlib import Path
from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.migration_approval import *

ROOT=Path(__file__).resolve().parents[1];NOW=datetime(2026,7,22,12,tzinfo=timezone.utc)
class Tests(unittest.TestCase):
 def setUp(self):
  self.root=ROOT/".tmp/migration_pack_tests";shutil.rmtree(self.root,ignore_errors=True);self.root.mkdir(parents=True)
  (self.root/"trade_ledger_v1.csv").write_text("event_id,timestamp,ticker,action,shares,price,value,fees,currency\nb1,2026-01-01T00:00:00+00:00,AAPL,BUY,1,200,200,0,USD\n")
  (self.root/"paper_portfolio_v3.csv").write_text("ticker,shares,entry_price\nAAPL,1,200\n")
  (self.root/"holdings_report.csv").write_text("ticker,market_value\nAAPL,250\n")
  (self.root/"broker_account.csv").write_text("cash\n750\n")
  self.evidence=build_evidence_pack(self.root,as_of=NOW);self.pack=build_migration_approval_pack(self.evidence,repository_commit="abc123",created_at=NOW)
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def test_stable_hash_and_every_proposal_links_gap(self):
  other=build_migration_approval_pack(self.evidence,repository_commit="abc123",created_at=NOW);self.assertEqual(self.pack.pack_hash,other.pack_hash);self.assertTrue(all(set(x.linked_gap_ids)<=set(g.gap_id for g in self.evidence.gaps) for x in self.pack.proposals))
 def test_immutable_pending_not_ready_and_no_strategy_guess(self):
  self.assertEqual(self.pack.readiness,"NOT_READY");self.assertTrue(all(x.approval_state=="PENDING" for x in self.pack.proposals));self.assertTrue(all(x.affected_strategy is None for x in self.pack.proposals))
  with self.assertRaises(FrozenInstanceError):self.pack.readiness="READY"
 def test_expected_proposals_and_materiality(self):
  types={x.proposal_type for x in self.pack.proposals};self.assertTrue({"STRATEGY_ALLOCATION","FX_ACQUISITION","OPENING_CASH","DIVIDEND_HISTORY","FEE_HISTORY","TAX_HISTORY","WITHHOLDING","CORPORATE_ACTION","UNKNOWN"}<=types);self.assertTrue(all(x.materiality.severity in {"LOW","MEDIUM","HIGH","CRITICAL"} for x in self.pack.proposals))
 def test_duplicate_and_unlinked_fail_closed(self):
  with self.assertRaises(MigrationPackError):replace(self.pack,proposals=(self.pack.proposals[0],self.pack.proposals[0])).validate({x.gap_id for x in self.evidence.gaps})
  with self.assertRaises(MigrationPackError):replace(self.pack.proposals[0],linked_gap_ids=("missing",)).validate({x.gap_id for x in self.evidence.gaps})
 def test_approval_binding_and_invalidation(self):
  p=self.pack.proposals[0];r=ApprovalRecord("a1",self.pack.pack_id,self.pack.pack_hash,p.proposal_id,p.proposal_hash,"APPROVED","operator",NOW,"reviewed");r.validate(self.pack)
  with self.assertRaises(MigrationPackError):replace(r,pack_hash="stale").validate(self.pack)
 def test_read_only_guarantees(self):
  before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()};build_migration_approval_pack(self.evidence,repository_commit="abc123",created_at=NOW);self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()});self.assertFalse((self.root/"data/accounting_generations/accounting_generation.json").exists());self.assertFalse((self.root/"data/opening_snapshot_candidates").exists())
 def test_timestamp_and_repository_identity_required(self):
  with self.assertRaises(MigrationPackError):build_migration_approval_pack(self.evidence,repository_commit="abc",created_at=NOW.replace(tzinfo=None))
  with self.assertRaises(MigrationPackError):build_migration_approval_pack(self.evidence,repository_commit="",created_at=NOW)
if __name__=="__main__":unittest.main()
