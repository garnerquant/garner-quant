from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


MUST_BE_IGNORED = [
    "broker_account.csv",
    "paper_portfolio_v3.csv",
    "trade_ledger_v1.csv",
    "data/live_runtime_status.json",
    "data/accounting_reconciliation_report.json",
    "data/global_scanner/latest_rankings.csv",
    "data/legacy_sandbox/paper_portfolio.csv",
    "research/experiments/experiments.jsonl",
    "research/report_exports/campaign_reports/example.md",
    "logs/runtime.log",
    ".tmp/scratch.txt",
]

MUST_NOT_BE_IGNORED = [
    "main_v2.py",
    "execution/atomic_io.py",
    "runtime/live_runtime.py",
    "docs/ARTIFACT_CLASSIFICATION.md",
    "runtime/generated_runtime_files.txt",
    "data/universes/current_assets.csv",
]

ALLOWED_TRACKED_IGNORED_EXACT = {
    "broker_account.csv",
    "holdings_report.csv",
    "paper_30_day_tracker.csv",
    "paper_portfolio_v3.csv",
    "portfolio_v2.csv",
    "signal_report_v2.csv",
    "trade_analytics_v3.csv",
    "trade_audit_trail.csv",
    "trade_journal_v3.csv",
    "trade_snapshots.csv",
    "v3_trades.csv",
    "data/live_monitor_runtime.json",
    "data/live_monitor_snapshot.json",
    "data/live_runtime_execution_log.json",
    "data/live_runtime_status.json",
    "data/market_intelligence.json",
    "data/news_events.json",
    "data/notification_state.json",
    "data/runtime_operations_log.json",
    "research/report_exports/campaign_reports/campaign_001_exit_optimisation_38504693-4616-43d4-8887-62adefbc3a50.md",
    "research/report_exports/campaign_reports/campaign_001_exit_optimisation_latest.md",
}


def run_git(args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def git_check_ignore(path):
    result = run_git(["check-ignore", "-q", "--no-index", "--", path])
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(result.stderr.strip() or f"git check-ignore failed for {path}")


def tracked_ignored_files():
    result = run_git(["ls-files", "-c", "-i", "--exclude-standard"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def main():
    issues = []

    for path in MUST_BE_IGNORED:
        check(git_check_ignore(path), f"generated artifact ignored: {path}", issues)

    for path in MUST_NOT_BE_IGNORED:
        check(not git_check_ignore(path), f"source/fixture tracked by default: {path}", issues)

    tracked_ignored = tracked_ignored_files()
    unexpected = sorted(tracked_ignored - ALLOWED_TRACKED_IGNORED_EXACT)
    check(
        not unexpected,
        "tracked ignored files are limited to documented historical runtime artifacts",
        issues,
    )
    if unexpected:
        for path in unexpected:
            print(f"  unexpected_tracked_ignored={path}")

    doc = (ROOT / "docs" / "ARTIFACT_CLASSIFICATION.md").read_text(encoding="utf-8")
    manifest = (ROOT / "runtime" / "generated_runtime_files.txt").read_text(encoding="utf-8")
    check("Existing Tracked Runtime Files" in doc, "artifact doc explains tracked runtime history", issues)
    check("research/report_exports/" in manifest, "runtime manifest includes research exports", issues)
    check("data/global_scanner/" in manifest, "runtime manifest includes scanner output", issues)
    check("data/legacy_sandbox/" in manifest, "runtime manifest includes legacy sandbox output", issues)

    if issues:
        print("\nArtifact hygiene validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nArtifact hygiene validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
