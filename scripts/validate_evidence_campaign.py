"""Production validator for the read-only Evidence Campaign Manager."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROTECTED = ("trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv", "broker_account.csv")


def _hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED}


def main() -> int:
    before = _hashes()
    tracked = tuple(ROOT.glob("data/accounting_generations/**/*")) + tuple(ROOT.glob("data/opening_snapshot_candidates/**/*"))
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_evidence_campaign", "-q"], cwd=ROOT)
    source = (ROOT / "canonical_accounting/evidence_campaign.py").read_text(encoding="utf-8")
    imports = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)}
    forbidden = {"canonical_accounting.opening_snapshot", "canonical_accounting.generation",
                 "canonical_accounting.migration_approval", "canonical_accounting.ledger", "execution.accounting"}
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    checks = {
        "focused tests": result.returncode == 0,
        "no forbidden accounting dependencies": not imports & forbidden,
        "monitor_only": config.get("mode") == "monitor_only",
        "paper disabled": config.get("paper_execution_enabled") is False,
        "live disabled": config.get("live_execution_enabled", False) is False,
        "canonical inactive": config.get("canonical_accounting_enabled", False) is False,
        "no pointer": not (ROOT / "data/accounting_generations/accounting_generation.json").exists(),
        "no production artifact creation": tracked == tuple(ROOT.glob("data/accounting_generations/**/*")) + tuple(ROOT.glob("data/opening_snapshot_candidates/**/*")),
        "historical accounting unchanged": before == _hashes(),
    }
    for label, passed in checks.items():
        print(("PASS" if passed else "FAIL") + ": " + label)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
