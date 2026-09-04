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
FORBIDDEN_IMPORTS = {
    "canonical_accounting.successor", "canonical_accounting.opening_snapshot",
    "execution", "execution.broker_adapter", "execution.trade_state",
}


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).is_file()}


def check(value, label, issues):
    print(("PASS" if value else "FAIL") + ": " + label)
    if not value: issues.append(label)


def main():
    issues = []; before = hashes()
    pointer = ROOT / "data/accounting_generations/accounting_generation.json"
    generations = ROOT / "data/accounting_generations/generations"
    candidates = ROOT / "data/opening_snapshot_candidates"
    frozen = ROOT / "data/frozen_evidence_packs"
    snapshots = {path: sorted(item.name for item in path.iterdir()) if path.exists() else []
                 for path in (generations, candidates, frozen)}
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_frozen_evidence_pack", "-q"], cwd=ROOT)
    check(result.returncode == 0, "focused frozen-evidence tests", issues)
    source_path = ROOT / "canonical_accounting/frozen_evidence.py"
    source = source_path.read_text(encoding="utf-8"); tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    check(not imports & FORBIDDEN_IMPORTS, "freeze subsystem has no candidate, generation, pointer, execution, or broker dependency", issues)
    check(all(token not in source for token in ("publish_prepared", "build_candidate", "OpeningLot", "submit_order", "place_order")),
          "freeze subsystem has no accounting publication, migration-lot, or order call", issues)
    for name in ("opening_evidence_reader.py", "migration_approval_reader.py", "review_workflow_reader.py"):
        reader = (ROOT / "dashboard" / name).read_text(encoding="utf-8")
        check("build_evidence_pack" not in reader and "datetime.now" not in reader and
              ("load_frozen_evidence" in reader or "load_current_frozen_evidence" in reader),
              f"{name} consumes only explicitly frozen evidence", issues)
    dashboard = (ROOT / "pages/99_admin_health.py").read_text(encoding="utf-8")
    section = dashboard[dashboard.index('Opening snapshot evidence'):dashboard.index('Accounting observation envelopes')]
    check("button(" not in section, "frozen evidence and linked governance dashboard remain read-only", issues)
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config["mode"] == "monitor_only" and config["paper_execution_enabled"] is False,
          "monitor_only and paper execution disabled remain enforced", issues)
    check(not pointer.exists(), "production accounting pointer remains absent", issues)
    check(before == hashes(), "protected accounting files remain byte-identical", issues)
    check(all(snapshots[path] == (sorted(item.name for item in path.iterdir()) if path.exists() else []) for path in snapshots),
          "no production frozen pack, candidate, or generation is created", issues)
    if issues: raise SystemExit("Frozen evidence validation failed: " + "; ".join(issues))
    print("Immutable frozen Evidence Pack and authoritative ingestion validation passed.")


if __name__ == "__main__": main()
