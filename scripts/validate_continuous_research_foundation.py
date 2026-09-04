"""Precise dependency, immutability and safety validator for continuous research."""
from __future__ import annotations

import ast, hashlib, json, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTECTED=("trade_ledger_v1.csv","trade_journal_v3.csv","paper_portfolio_v3.csv","paper_30_day_tracker.csv","broker_account.csv","config.py","risk_engine/risk_config.json","strategy/signals.py","strategy/portfolio.py")


def hashes(): return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT/name).is_file()}


def main():
    before=hashes(); result=subprocess.run([sys.executable,"-m","unittest","tests.test_continuous_research_evidence","tests.test_continuous_research_analysis","tests.test_continuous_research_workflow","-q"],cwd=ROOT)
    modules=list((ROOT/"research/continuous_improvement").glob("*.py")); imports=set(); source=""
    for path in modules:
        text=path.read_text(encoding="utf-8"); source+=text; tree=ast.parse(text)
        imports|={node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module}
        imports|={alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
    forbidden_prefixes=("execution","canonical_accounting","risk_engine","strategy","runtime")
    config=json.loads((ROOT/"runtime/live_runtime_config.json").read_text())
    dashboard_source=(ROOT/"dashboard/continuous_research_reader.py").read_text(encoding="utf-8")
    page_source="".join((ROOT/name).read_text(encoding="utf-8") for name in ("pages/97_research_intelligence.py","pages/98_research_lab.py"))
    checks={"focused foundation tests":result.returncode==0,
      "no production dependency":not any(name.startswith(forbidden_prefixes) for name in imports),
      "no strategy, order, broker, pointer, or accounting mutation API":all(token not in source for token in ("submit_order","place_order","publish_prepared","accounting_generation","paper_portfolio_v3","risk_config.json","strategy/signals.py")),
      "monitor_only":config["mode"]=="monitor_only","paper disabled":config["paper_execution_enabled"] is False,
      "no accounting pointer":not (ROOT/"data/accounting_generations/accounting_generation.json").exists(),
      "dashboard uses immutable reader": "load_latest_report_payload" in dashboard_source,
      "research dashboards are read-only": all(token not in page_source for token in ("st.button(","st.form(","publish_morning_report","write_text(","write_bytes(")),
      "protected artifacts unchanged":before==hashes()}
    for label,passed in checks.items(): print(("PASS" if passed else "FAIL")+": "+label)
    return 0 if all(checks.values()) else 1


if __name__=="__main__": raise SystemExit(main())
