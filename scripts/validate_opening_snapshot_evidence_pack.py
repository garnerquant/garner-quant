from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROTECTED = ("trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv", "broker_account.csv", "paper_30_day_tracker.csv")
FORBIDDEN = ("SuccessorGenerationWriter", "publish_prepared", "freeze_inactive_candidate", "build_candidate",
             "commit_trade_state", "submit_order", "place_order", "broker_adapter", "open(\"w", "write_text(", "write_bytes(")


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).is_file()}


def check(value, label, issues):
    print(("PASS" if value else "FAIL") + ": " + label)
    if not value:
        issues.append(label)


def main():
    issues = []
    before = hashes()
    pointer = ROOT / "data/accounting_generations/accounting_generation.json"
    generations = ROOT / "data/accounting_generations/generations"
    candidate_root = ROOT / "data/opening_snapshot_candidates"
    generation_before = sorted(path.name for path in generations.iterdir()) if generations.exists() else []
    candidate_before = sorted(path.name for path in candidate_root.iterdir()) if candidate_root.exists() else []
    result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_opening_snapshot_evidence_pack", "-q"], cwd=ROOT, check=False)
    check(result.returncode == 0, "focused evidence-pack tests", issues)
    path = ROOT / "canonical_accounting/evidence_pack.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    check(all(token not in source for token in FORBIDDEN), "evidence subsystem has no persistence, candidate, generation, pointer, accounting, execution, or broker write path", issues)
    check("build_evidence_pack" in source and "OpeningSnapshotEvidencePack" in source and "EvidenceGap" in source,
          "evidence, inventory, and immutable gap-register contracts exist", issues)
    from canonical_accounting.evidence_pack import build_evidence_pack
    pack = build_evidence_pack(ROOT, as_of=datetime(2026, 7, 22, tzinfo=timezone.utc))
    check(pack.pack_hash == build_evidence_pack(ROOT, as_of=datetime(2026, 7, 22, tzinfo=timezone.utc)).pack_hash,
          "production evidence report and hashes are deterministic", issues)
    check(pack.opening_snapshot_readiness == "NOT_READY" and pack.replay_readiness == "NOT_READY",
          "unproven evidence fails closed", issues)
    check(bool(pack.gaps) and len({gap.gap_id for gap in pack.gaps}) == len(pack.gaps), "gap register identities are unique", issues)
    dashboard = (ROOT / "pages/99_admin_health.py").read_text(encoding="utf-8")
    section = dashboard[dashboard.index('Opening snapshot evidence'):dashboard.index('Accounting observation envelopes')]
    check("button(" not in section and "opening_evidence_status" in dashboard, "Operations evidence section is read-only", issues)
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config["mode"] == "monitor_only" and config["paper_execution_enabled"] is False,
          "monitor_only and paper execution disabled remain enforced", issues)
    check(not pointer.exists(), "production pointer remains absent", issues)
    generation_after = sorted(path.name for path in generations.iterdir()) if generations.exists() else []
    candidate_after = sorted(path.name for path in candidate_root.iterdir()) if candidate_root.exists() else []
    check(generation_before == generation_after, "no production generation is created", issues)
    check(candidate_before == candidate_after, "no production opening candidate is created", issues)
    check(before == hashes(), "protected accounting files remain byte-identical", issues)
    if issues:
        raise SystemExit("Evidence-pack validation failed: " + "; ".join(issues))
    print("Verified opening snapshot evidence pack and gap register validation passed.")


if __name__ == "__main__":
    main()
