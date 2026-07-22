from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTECTED=("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")

def hashes(): return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PROTECTED}
def check(value,label,issues): print(("PASS" if value else "FAIL")+": "+label); issues.append(label) if not value else None

def main():
    issues=[]; before=hashes(); pointer=ROOT/"data/accounting_generations/accounting_generation.json"; pointer_before=pointer.exists()
    result=subprocess.run([sys.executable,"-m","unittest","tests.test_accounting_observation_envelope","-q"],cwd=ROOT,check=False)
    check(result.returncode==0,"accounting observation envelope tests",issues)
    source=(ROOT/"execution/portfolio_manager.py").read_text(encoding="utf-8"); tree=ast.parse(source)
    check(source.count("observe_monitor_only_evaluation(proposal, risk_context, risk_decision)")==2,"both production BUY and SELL monitor evaluations are observed",issues)
    check("if shadow_mode:" in source and "if not shadow_mode:" in source,"observation and execution branches remain separated",issues)
    check("commit_trade_state" not in (ROOT/"canonical_accounting/observation.py").read_text(encoding="utf-8"),"observer has no legacy accounting writer",issues)
    check("SuccessorGenerationWriter" not in (ROOT/"canonical_accounting/observation.py").read_text(encoding="utf-8"),"observer has no canonical generation writer",issues)
    config=json.loads((ROOT/"runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config["mode"]=="monitor_only" and config["paper_execution_enabled"] is False,"monitor_only and execution-disabled state preserved",issues)
    check(before==hashes(),"protected accounting files remain byte-identical",issues)
    check(pointer.exists()==pointer_before==False,"production accounting pointer remains absent",issues)
    check("Accounting observation envelopes" in (ROOT/"pages/99_admin_health.py").read_text(encoding="utf-8"),"read-only Operations status is present",issues)
    if issues: raise SystemExit("Accounting observation validation failed: "+"; ".join(issues))
    print("Accounting observation envelope validation passed.")

if __name__=="__main__": main()
