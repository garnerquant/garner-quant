from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from risk_engine.operations import activation_readiness, decision_history, risk_metrics
from risk_engine.shadow_simulation import run_shadow_simulations

PROTECTED = ("trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv", "broker_account.csv", "paper_30_day_tracker.csv")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).is_file()}


def main():
    before = hashes()
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    require(config["mode"] == "monitor_only", "runtime is not monitor_only")
    require(config["paper_execution_enabled"] is False, "paper execution is enabled")
    require(not (ROOT / "data/accounting_generations/accounting_generation.json").exists(), "canonical accounting pointer is active")
    runtime = (ROOT / "runtime/live_runtime.py").read_text(encoding="utf-8")
    portfolio = (ROOT / "execution/portfolio_manager.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "pages/99_admin_health.py").read_text(encoding="utf-8")
    require("run_shadow_evaluation(" in runtime and "shadow_mode=True" in runtime, "runtime shadow path is absent")
    require("if shadow_mode and risk_decision.approved" in portfolio, "shadow approval defence is absent")
    require("if not shadow_mode:" in portfolio and "commit_trade_state(" in portfolio, "shadow path can reach trade commit")
    require("activation_readiness" in dashboard and "decision_history" in dashboard and "risk_metrics" in dashboard, "dashboard is not sourced from risk operations")
    require("submit_order" not in runtime and "place_order" not in runtime, "broker submission appeared in runtime")

    output = ROOT / ".tmp" / "risk_shadow_validator"
    shutil.rmtree(output, ignore_errors=True)
    try:
        prices_path = ROOT / "prices_v2.csv"
        if not prices_path.is_file():
            # Runtime prices are ignored server state; use an isolated fixture
            # when validating a clean source checkout in CI.
            output.mkdir(parents=True, exist_ok=True)
            prices_path = output / "prices_v2.csv"
            pd.DataFrame({"BTC-GBP": [50000]}).to_csv(prices_path)
        report = run_shadow_simulations(output, prices_path=prices_path)
        require(report["execution_attempts"] == 0 and len(report["scenarios"]) == 16, "shadow scenarios are incomplete")
        rows = decision_history(audit_path=output / "decisions.jsonl")
        require(rows and all(row["execution_eligible"] is False for row in rows), "shadow history contains execution eligibility")
        metrics = risk_metrics(audit_path=output / "decisions.jsonl", kill_audit_path=output / "kill-audit.jsonl",
                               now=datetime(2026, 7, 22, tzinfo=timezone.utc))
        require(metrics["MONITOR_ONLY"] > 0 and metrics["average_latency_ms"] is not None, "shadow metrics did not update")
        readiness = activation_readiness(accounting_root=output / "missing-accounting", kill_switch_path=output / "missing-kill.json")
        require(readiness["ready"] is False and readiness["answer"] == "No", "readiness report is not fail closed")
        original = (output / "decisions.jsonl").read_bytes()
        decision_history(audit_path=output / "decisions.jsonl", symbol="AAPL")
        require((output / "decisions.jsonl").read_bytes() == original, "history reader is not read-only")
    finally:
        shutil.rmtree(output, ignore_errors=True)
    require(before == hashes(), "shadow validator modified protected production files")
    print("PASS: risk shadow mode and activation readiness validation")


if __name__ == "__main__":
    main()
