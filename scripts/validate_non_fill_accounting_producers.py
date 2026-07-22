from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTECTED=("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")
FORBIDDEN=("SuccessorGenerationWriter","publish_prepared","commit_trade_state","submit_order","place_order","broker_adapter","reconcile_broker_account_file")

def hashes(): return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PROTECTED}
def check(value,label,issues): print(("PASS" if value else "FAIL")+": "+label); issues.append(label) if not value else None

def main():
    issues=[]; before=hashes(); pointer=ROOT/"data/accounting_generations/accounting_generation.json"; generations=ROOT/"data/accounting_generations/generations"
    generation_before=sorted(path.name for path in generations.iterdir()) if generations.exists() else []
    result=subprocess.run([sys.executable,"-m","unittest","tests.test_non_fill_accounting_producers","-q"],cwd=ROOT,check=False)
    check(result.returncode==0,"focused non-fill producer tests",issues)
    producer=(ROOT/"canonical_accounting/non_fill_producers.py").read_text(encoding="utf-8")
    event=(ROOT/"canonical_accounting/non_fill_events.py").read_text(encoding="utf-8")
    ast.parse(producer); ast.parse(event)
    check(all(token not in producer+event for token in FORBIDDEN),"producer subsystem imports or invokes no accounting publication, execution, broker, or reconciliation path",issues)
    check("AccountingObservationEnvelope" in producer and "AccountingObservationStore" in producer,"existing envelope and append-only store are reused",issues)
    for kind in ("DEPOSIT","WITHDRAWAL","DIVIDEND","FEE","FX_ADJUSTMENT","CORPORATE_ACTION"):
        check(kind in event and kind in producer,"typed producer schema loads for "+kind,issues)
    check("production_source_available: bool=False" in producer,"all production non-fill producers default unavailable",issues)
    dashboard=(ROOT/"pages/99_admin_health.py").read_text(encoding="utf-8")
    check("Non-fill accounting observation producers" in dashboard and "button(" not in dashboard[dashboard.index("Non-fill accounting observation producers"):dashboard.index("try:",dashboard.index("Non-fill accounting observation producers"))],"Operations producer section is read-only",issues)
    config=json.loads((ROOT/"runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config.get("mode")=="monitor_only" and config.get("paper_execution_enabled") is False,"monitor_only and paper execution disabled are preserved",issues)
    check(not pointer.exists(),"production pointer remains absent",issues)
    generation_after=sorted(path.name for path in generations.iterdir()) if generations.exists() else []
    check(generation_before==generation_after,"no production generation is created",issues)
    check(before==hashes(),"protected accounting files remain byte-identical",issues)
    if issues: raise SystemExit("Non-fill producer validation failed: "+"; ".join(issues))
    print("Non-fill accounting producer validation passed.")

if __name__=="__main__": main()
