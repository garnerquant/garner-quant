from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROTECTED = ("trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv", "broker_account.csv", "paper_30_day_tracker.csv")


def hashes(): return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).is_file()}
def check(value, label, issues):
    print(("PASS" if value else "FAIL") + ": " + label)
    if not value: issues.append(label)


def main():
    issues = []; before = hashes()
    pointer = ROOT / "data/accounting_generations/accounting_generation.json"
    generations = ROOT / "data/accounting_generations/generations"
    candidates = ROOT / "data/opening_snapshot_candidates"
    frozen = ROOT / "data/frozen_evidence_packs"
    snapshots = {path: sorted(item.name for item in path.iterdir()) if path.exists() else [] for path in (generations, candidates, frozen)}
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_evidence_acquisition_reconciliation", "-q"], cwd=ROOT)
    check(result.returncode == 0, "focused acquisition and reconciliation tests", issues)
    paths = (ROOT / "canonical_accounting/evidence_reconciliation.py", ROOT / "canonical_accounting/frozen_evidence.py")
    imports = set(); source = ""
    for path in paths:
        text = path.read_text(encoding="utf-8"); source += text; tree = ast.parse(text)
        imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    check(not any(name and (name.startswith("execution") or name in {"canonical_accounting.successor", "canonical_accounting.opening_snapshot"}) for name in imports),
          "acquisition subsystem has no execution, generation, pointer, candidate, or migration-lot dependency", issues)
    check(all(token not in source for token in ("publish_prepared", "build_candidate", "OpeningLot", "submit_order", "place_order")),
          "acquisition and reconciliation contain no accounting publication or broker-order call", issues)
    check(all(name in source for name in ("EXACT_MATCH", "PARTIAL_MATCH", "CONFLICT", "MISSING", "UNKNOWN")),
          "all reconciliation outcomes are explicit", issues)
    dashboard = (ROOT / "pages/99_admin_health.py").read_text(encoding="utf-8")
    section = dashboard[dashboard.index('Opening snapshot evidence'):dashboard.index('Accounting observation envelopes')]
    check("button(" not in section and all(label in section for label in ("Previous Frozen Pack", "Coverage Improvement", "Resolved Gaps", "Conflict Count", "Import History")),
          "Operations acquisition and reconciliation section is complete and read-only", issues)
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config["mode"] == "monitor_only" and config["paper_execution_enabled"] is False,
          "monitor_only and paper execution disabled remain enforced", issues)
    check(not pointer.exists(), "production accounting pointer remains absent", issues)
    check(before == hashes(), "protected historical accounting remains byte-identical", issues)
    check(all(snapshots[path] == (sorted(item.name for item in path.iterdir()) if path.exists() else []) for path in snapshots),
          "no production frozen pack, candidate, or generation is created", issues)
    if issues: raise SystemExit("Evidence acquisition validation failed: " + "; ".join(issues))
    print("Authoritative evidence acquisition and reconciliation validation passed.")


if __name__ == "__main__": main()
