from __future__ import annotations
import shutil,unittest
from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
from pathlib import Path
from canonical_accounting.evidence_pack import build_evidence_pack
from canonical_accounting.migration_approval import build_migration_approval_pack,MigrationPackError
from canonical_accounting.review_workflow import *
ROOT=Path(__file__).resolve().parents[1];NOW=datetime(2026,7,22,12,tzinfo=timezone.utc)
class Tests(unittest.TestCase):
 def setUp(self):
  self.root=ROOT/".tmp/review_tests";shutil.rmtree(self.root,ignore_errors=True);self.root.mkdir(parents=True);(self.root/"trade_ledger_v1.csv").write_text("event_id,timestamp,ticker,action,shares,price,value,fees,currency\nb1,2026-01-01T00:00:00+00:00,AAPL,BUY,1,200,200,0,USD\n");(self.root/"paper_portfolio_v3.csv").write_text("ticker,shares,entry_price\nAAPL,1,200\n");(self.root/"holdings_report.csv").write_text("ticker,market_value\nAAPL,250\n");(self.root/"broker_account.csv").write_text("cash\n750\n");self.e=build_evidence_pack(self.root,as_of=NOW);self.p=build_migration_approval_pack(self.e,repository_commit="abc",created_at=NOW);self.proposal=self.p.proposals[0]
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def review(self,state="APPROVED"):return create_review(self.p,self.proposal.proposal_id,reviewer_identity="operator",review_timestamp=NOW,review_state=state,comments="explicit decision",supporting_reference="statement:1",digital_signature_placeholder="sig:pending")
 def test_immutable_stable_hash_and_states(self):
  r=self.review();self.assertEqual(r.review_hash,self.review().review_hash);self.assertIn(r.review_state,{x.value for x in ReviewState});
  with self.assertRaises(FrozenInstanceError):r.comments="x"
 def test_all_hash_dependencies_invalidate(self):
  r=self.review()
  for field in ("proposal_hash","approval_pack_hash","evidence_pack_hash","repository_commit","schema_version"):
   with self.assertRaises(MigrationPackError):replace(r,**{field:"changed"}).validate(self.p)
 def test_duplicate_history_rejected_and_ordered(self):
  r=self.review()
  with self.assertRaises(MigrationPackError):validate_review_history(self.p,(r,r))
  self.assertEqual(validate_review_history(self.p,(r,)),(r,))
 def test_export_integrity_and_metrics(self):
  r=self.review();b=export_review_bundle(self.p,(r,),created_at=NOW);self.assertEqual(b.serialize(),b.serialize());self.assertIn(b.bundle_hash,b.serialize());m=decision_metrics(self.p,(r,));self.assertEqual(m["APPROVED"],1);self.assertEqual(m["PENDING"],len(self.p.proposals)-1)
 def test_explicit_fields_and_read_only(self):
  with self.assertRaises(MigrationPackError):create_review(self.p,self.proposal.proposal_id,reviewer_identity="",review_timestamp=NOW,review_state="APPROVED",comments="",supporting_reference="",digital_signature_placeholder="")
  before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()};export_review_bundle(self.p,(self.review(),),created_at=NOW);self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()});self.assertFalse((self.root/"data/accounting_generations/accounting_generation.json").exists())
if __name__=="__main__":unittest.main()
