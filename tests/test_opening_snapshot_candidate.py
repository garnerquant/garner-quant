from __future__ import annotations
import hashlib,shutil,unittest
from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from canonical_accounting.opening_snapshot import *
from risk_engine.configuration import load_risk_configuration

ROOT=Path(__file__).resolve().parents[1];NOW=datetime(2026,7,22,12,tzinfo=timezone.utc)
class OpeningSnapshotTests(unittest.TestCase):
 def setUp(self):self.root=ROOT/".tmp/opening_snapshot_tests";shutil.rmtree(self.root,ignore_errors=True);self.root.mkdir(parents=True)
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def manifest(self,classification="AUTHORITATIVE",content="abc",latest=None):
  entry=SourceManifestEntry("fixture-ledger",classification,"fixture://ledger","1",3,1,NOW-timedelta(hours=1),hashlib.sha256(content.encode()).hexdigest(),NOW-timedelta(days=1),latest or NOW-timedelta(minutes=1),True,"controlled fixture evidence","fixture-writer",NOW)
  return SourceManifest("manifest-1","1.0",NOW,(entry,))
 def cutoff(self,manifest=None,at=NOW):
  manifest=manifest or self.manifest();return CutOffContract(at,"UTC","ADMINISTRATIVE","fixture-session","fixture-bar",(("fixture-ledger",(at-timedelta(minutes=1)).isoformat()),),at-timedelta(minutes=1),"GBP identity; foreign max age 3h",load_risk_configuration().configuration_version,"1","explicit-fixture-strategy-v1",manifest.manifest_hash)
 def parts(self,symbol="BTC-GBP",strategy="alpha",currency="GBP",fx=Decimal("1"),price=Decimal("50000"),quantity=Decimal("0.01")):
  from canonical_accounting.instruments import get_instrument_metadata
  meta=get_instrument_metadata(symbol);scale=meta.price_scale;native=price*scale*quantity;base=native*fx;instrument=f"instrument:{symbol}";cash=(OpeningCash("GBP",Decimal("9500"),Decimal("0"),Decimal("0"),Decimal("9500"),Decimal("1"),NOW-timedelta(minutes=1),"GBP identity","GBP_PER_GBP","cash-source"),)
  lot=(OpeningLot("lot-1",strategy,instrument,symbol,NOW-timedelta(days=1),quantity,quantity,price*scale,native,Decimal("0"),base,fx,NOW-timedelta(days=1),"fixture-acquisition-fx","fill-1"),)
  position=(OpeningPosition("position-1",strategy,instrument,symbol,meta.exchange,meta.exchange,meta.asset_class,currency,quantity,quantity,Decimal("0"),meta.provider_price_unit,12,8,price,NOW-timedelta(minutes=1),"fixture-price",fx,NOW-timedelta(minutes=1),"fixture-valuation-fx",native,base,base,Decimal("0"),"holding-1"),)
  pnl=(PnlCarryForward(strategy,instrument,currency,Decimal("5"),Decimal("0"),Decimal("1"),Decimal("2"),Decimal("0.5"),Decimal("10000"),Decimal("0"),Decimal("0"),Decimal("0"),Decimal("0"),Decimal("0"),"pnl-source"),)
  return cash,position,lot,pnl
 def candidate(self,manifest=None,cutoff=None,**kwargs):
  manifest=manifest or self.manifest();cutoff=cutoff or self.cutoff(manifest);cash,pos,lots,pnl=self.parts(**kwargs);return build_candidate(manifest=manifest,cut_off=cutoff,cash=cash,positions=pos,lots=lots,pnl=pnl,created_at=NOW)
 def expected(self):return {"cash_base":"9500","positions_base":"500","lot_cost_base":"500","lot_quantity":"0.01","realised_pnl":"5","unrealised_pnl":"0","fees":"1","dividends":"2","taxes_withholding":"0.5","deposits":"10000","withdrawals":"0","gross_exposure":"500","net_exposure":"500","position:BTC-GBP":"0.01","strategy_exposure:alpha":"500","equity":"10000"}
 def test_immutable_stable_hash_manifest_and_changes(self):
  c=self.candidate();self.assertEqual(c.serialize(),c.serialize());self.assertEqual(c.candidate_hash,c.candidate_hash);self.assertEqual(self.manifest().manifest_hash,self.manifest().manifest_hash)
  with self.assertRaises(FrozenInstanceError):c.active=True
  m2=self.manifest(content="changed");self.assertNotEqual(c.candidate_hash,self.candidate(manifest=m2,cutoff=self.cutoff(m2)).candidate_hash)
  m3=self.manifest(latest=NOW-timedelta(minutes=2));cut=self.cutoff(m3,at=NOW+timedelta(minutes=1));self.assertNotEqual(c.candidate_hash,self.candidate(manifest=m3,cutoff=cut).candidate_hash)
 def test_source_cutoff_schema_and_authority_fail_closed(self):
  for classification in ("DERIVED","REPAIR_ONLY","MIGRATION_ONLY","TEST_ONLY"):
   with self.assertRaises(OpeningSnapshotError):self.candidate(manifest=self.manifest(classification),cutoff=self.cutoff(self.manifest(classification)))
  m=self.manifest(latest=NOW+timedelta(seconds=1));
  with self.assertRaises(OpeningSnapshotError):m.validate()
  with self.assertRaises(OpeningSnapshotError):replace(self.candidate(),schema_version="2").validate()
  with self.assertRaises(OpeningSnapshotError):replace(self.cutoff(),cut_off_timestamp=NOW.replace(tzinfo=None)).validate()
 def test_cash_fx_restricted_unsettled_and_flow_semantics(self):
  c=self.candidate();self.assertEqual(c.cash[0].fx_rate,1);self.assertEqual(c.pnl[0].deposits,10000);self.assertEqual(c.pnl[0].dividends,2);self.assertEqual(c.pnl[0].fees,1);self.assertEqual(c.pnl[0].taxes_withholding,Decimal("0.5"))
  cash,pos,lots,pnl=self.parts(symbol="AAPL",currency="USD",fx=Decimal("0.8"),price=Decimal("200"),quantity=Decimal("1"));cash=(OpeningCash("USD",Decimal("100"),Decimal("5"),Decimal("2"),Decimal("80"),Decimal("0.8"),NOW-timedelta(minutes=1),"fixture-usd","GBP_PER_USD","cash-usd"),)
  m=self.manifest();c=build_candidate(manifest=m,cut_off=self.cutoff(m),cash=cash,positions=pos,lots=lots,pnl=pnl,created_at=NOW);self.assertEqual(c.cash[0].restricted,5)
  with self.assertRaises(OpeningSnapshotError):build_candidate(manifest=m,cut_off=self.cutoff(m),cash=(replace(cash[0],fx_source=""),),positions=pos,lots=lots,pnl=pnl,created_at=NOW)
  with self.assertRaises(OpeningSnapshotError):build_candidate(manifest=m,cut_off=self.cutoff(m),cash=cash,positions=(replace(pos[0],fx_timestamp=NOW-timedelta(hours=4)),),lots=lots,pnl=pnl,created_at=NOW)
 def test_positions_fifo_strategy_gbp_and_migration_rules(self):
  c=self.candidate(symbol="IUSA.L",price=Decimal("5000"),quantity=Decimal("10"));self.assertEqual(c.positions[0].price_units,"GBp");self.assertEqual(c.positions[0].native_market_value,Decimal("500"))
  with self.assertRaises(OpeningSnapshotError):replace(c,positions=(replace(c.positions[0],strategy_id=""),)).validate()
  with self.assertRaises(OpeningSnapshotError):replace(c,lots=(replace(c.lots[0],remaining_quantity=Decimal("11")),)).validate()
  with self.assertRaises(OpeningSnapshotError):replace(c,lots=(replace(c.lots[0],strategy_id="beta"),)).validate()
  migration=replace(c.lots[0],migration_classification="EXPLICIT_OPENING_MIGRATION");replace(c,lots=(migration,)).validate()
  with self.assertRaises(OpeningSnapshotError):replace(c,lots=(replace(migration,migration_classification="ORDINARY_FILL"),)).validate()
 def test_pnl_unknown_and_fx_acquisition_valuation_separation(self):
  c=self.candidate();self.assertNotEqual(c.lots[0].acquisition_fx_timestamp,c.positions[0].fx_timestamp)
  unknown=replace(c.pnl[0],unknown_historical_pnl=Decimal("1"));
  with self.assertRaises(OpeningSnapshotError):replace(c,pnl=(unknown,),unresolved_items=()).validate()
  replace(c,pnl=(unknown,),unresolved_items=("unknown historical P&L",)).validate()
  with self.assertRaises(OpeningSnapshotError):replace(c,positions=(replace(c.positions[0],currency="GBp"),)).validate()
 def test_reconciliation_classification_largest_and_readiness(self):
  c=self.candidate();exact=reconcile_candidate(c,self.expected());self.assertFalse(exact.blocking);self.assertTrue(all(x.classification=="EXACT" for x in exact.differences))
  rounding=reconcile_candidate(c,{**self.expected(),"cash_base":"9500.005"});self.assertEqual(next(x for x in rounding.differences if x.metric=="cash_base").classification,"ROUNDING")
  bad=reconcile_candidate(c,{**self.expected(),"equity":"9000"});self.assertTrue(bad.blocking);self.assertEqual(bad.largest_difference,1000);self.assertEqual(readiness(c,bad)["status"],"NOT_READY")
  for classification in ("TIMING","FX","ATTRIBUTION_GAP"):
   report=reconcile_candidate(c,{**self.expected(),"equity":"9000"},classifications={"equity":classification});self.assertEqual(next(x for x in report.differences if x.metric=="equity").classification,classification)
 def test_approval_binding_rejection_and_no_activation(self):
  c=self.candidate();r=reconcile_candidate(c,self.expected());a=OpeningApprovalRecord("approval-1",c.candidate_id,"operator-fixture","accounting-reviewer",NOW,c.candidate_hash,r.reconciliation_hash,"APPROVED_FOR_REPLAY_TESTING","fixture",(),None);a.validate(c,r);self.assertFalse(c.active)
  with self.assertRaises(OpeningSnapshotError):replace(a,candidate_hash="bad").validate(c,r)
  replace(a,decision="REJECTED").validate(c,r);replace(a,decision="CHANGES_REQUIRED").validate(c,r)
 def test_inactive_freeze_restart_and_safety(self):
  c=self.candidate();r=reconcile_candidate(c,self.expected());protected=[ROOT/n for n in ("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")];before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
  path=freeze_inactive_candidate(c,r,self.root/"candidates");self.assertTrue((path/"candidate.json").exists());self.assertFalse((ROOT/"data/accounting_generations/accounting_generation.json").exists());self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()})
  with self.assertRaises(OpeningSnapshotError):freeze_inactive_candidate(c,r,self.root/"candidates")
  with self.assertRaises(OpeningSnapshotError):freeze_inactive_candidate(c,reconcile_candidate(c,{**self.expected(),"equity":"1"}),self.root/"bad")
if __name__=="__main__":unittest.main()
