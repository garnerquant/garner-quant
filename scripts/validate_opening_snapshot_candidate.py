from __future__ import annotations
import ast,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PROTECTED=("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")
FORBIDDEN=("SuccessorGenerationWriter","publish_prepared","load_active_generation","POINTER_FILE","commit_trade_state","submit_order","place_order","broker_adapter")
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in PROTECTED if (ROOT/n).is_file()}
def check(v,l,i):print(("PASS"if v else"FAIL")+": "+l);i.append(l)if not v else None
def main():
 issues=[];before=hashes();pointer=ROOT/"data/accounting_generations/accounting_generation.json";generations=ROOT/"data/accounting_generations/generations";g0=sorted(p.name for p in generations.iterdir())if generations.exists()else[]
 result=subprocess.run([sys.executable,"-m","unittest","tests.test_opening_snapshot_candidate","-q"],cwd=ROOT,check=False);check(result.returncode==0,"opening snapshot fixture tests",issues)
 source=(ROOT/"canonical_accounting/opening_snapshot.py").read_text(encoding="utf-8");ast.parse(source);check(all(x not in source for x in FORBIDDEN),"snapshot subsystem imports no pointer, successor, accounting, execution, or broker publication",issues)
 for token in ("SourceManifest","CutOffContract","OpeningSnapshotCandidate","ReconciliationReport","OpeningApprovalRecord","freeze_inactive_candidate"):
  check(token in source,token+" contract exists",issues)
 check("APPROVED_FOR_PRODUCTION_ACTIVATION"not in source,"approval cannot authorize production activation",issues)
 dashboard=(ROOT/"pages/99_admin_health.py").read_text(encoding="utf-8");section=dashboard[dashboard.index('Canonical opening snapshot'):];check("button("not in section,"Opening Snapshot Operations section is read-only",issues)
 cfg=json.loads((ROOT/"runtime/live_runtime_config.json").read_text());check(cfg["mode"]=="monitor_only"and cfg["paper_execution_enabled"]is False,"monitor_only and paper execution disabled remain enforced",issues)
 check(not pointer.exists(),"production pointer remains absent",issues);g1=sorted(p.name for p in generations.iterdir())if generations.exists()else[];check(g0==g1,"no production generation is created",issues);check(before==hashes(),"protected accounting files remain byte-identical",issues)
 check(not (ROOT/"data/opening_snapshot_candidates").exists(),"validation creates no production-data candidate",issues)
 if issues:raise SystemExit("Opening snapshot validation failed: "+"; ".join(issues))
 print("Verified opening snapshot candidate validation passed.")
if __name__=="__main__":main()
