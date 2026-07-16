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

ALLOWED_TRACKED_IGNORED_EXACT = set()


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
        "generated runtime artifacts are absent from the Git index",
        issues,
    )
    if unexpected:
        for path in unexpected:
            print(f"  unexpected_tracked_ignored={path}")

    doc = (ROOT / "docs" / "ARTIFACT_CLASSIFICATION.md").read_text(encoding="utf-8")
    manifest = (ROOT / "runtime" / "generated_runtime_files.txt").read_text(encoding="utf-8")
    check("Runtime Ownership" in doc, "artifact doc defines server-owned runtime state", issues)
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
