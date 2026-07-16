from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import STARTING_CASH  # noqa: E402
from execution.trade_ledger import LEDGER_COLUMNS  # noqa: E402
from runtime.bootstrap_state import bootstrap_runtime_state  # noqa: E402
from runtime.startup_validation import validate_runtime_startup  # noqa: E402


TRACKED_GENERATED_EXPECTED = set()


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def tracked_ignored_files():
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "-c", "-i", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scratch_root(label):
    return ROOT / "data" / f"bootstrap_validation_{label}_{uuid4().hex}"


def bootstrap_creates_expected_files():
    temp_root = scratch_root("missing")
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        dry_run = bootstrap_runtime_state(temp_root, apply=False)
        if not dry_run.planned or dry_run.created:
            return False

        applied = bootstrap_runtime_state(temp_root, apply=True)
        if sorted(applied.created) != sorted(dry_run.planned):
            return False

        broker = pd.read_csv(temp_root / "broker_account.csv")
        ledger = pd.read_csv(temp_root / "trade_ledger_v1.csv")
        status = read_json(temp_root / "data" / "live_runtime_status.json")
        notification_state = read_json(temp_root / "data" / "notification_state.json")

        return (
            float(broker.loc[0, "cash"]) == float(STARTING_CASH)
            and list(ledger.columns) == LEDGER_COLUMNS
            and status["status"] == "not_started"
            and "sent_alerts" in notification_state
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def bootstrap_is_idempotent_and_preserves_existing():
    temp_root = scratch_root("existing")
    try:
        (temp_root / "data").mkdir(parents=True, exist_ok=True)
        broker_path = temp_root / "broker_account.csv"
        pd.DataFrame(
            [
                {
                    "cash": 123.45,
                    "buying_power": 123.45,
                    "positions_value": 0.0,
                    "portfolio_value": 123.45,
                    "realised_pnl": 0.0,
                    "unrealised_pnl": 0.0,
                }
            ]
        ).to_csv(broker_path, index=False)

        first = bootstrap_runtime_state(temp_root, apply=True)
        second = bootstrap_runtime_state(temp_root, apply=True)
        broker = pd.read_csv(broker_path)
        return (
            "broker_account.csv" in first.existing
            and not second.created
            and float(broker.loc[0, "cash"]) == 123.45
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def startup_bootstraps_missing_root():
    temp_root = scratch_root("startup")
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        result = validate_runtime_startup(temp_root)
        return (
            result.ok
            and (temp_root / "broker_account.csv").exists()
            and (temp_root / "data" / "live_runtime_status.json").exists()
            and result.checked_files > 0
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def docs_include_untrack_command():
    text = (ROOT / "docs" / "RUNTIME_BOOTSTRAP_AND_INDEX.md").read_text(encoding="utf-8")
    return (
        "index cleanup is complete" in text
        and "No generated runtime artifact is required as Git-tracked seed state" in text
    )


def main():
    issues = []
    tracked = tracked_ignored_files()
    check(
        tracked == TRACKED_GENERATED_EXPECTED,
        "generated runtime artifacts are absent from the Git index",
        issues,
    )
    if tracked != TRACKED_GENERATED_EXPECTED:
        print("  missing=" + ",".join(sorted(TRACKED_GENERATED_EXPECTED - tracked)))
        print("  unexpected=" + ",".join(sorted(tracked - TRACKED_GENERATED_EXPECTED)))

    check(bootstrap_creates_expected_files(), "bootstrap creates safe missing seed state", issues)
    check(
        bootstrap_is_idempotent_and_preserves_existing(),
        "bootstrap is idempotent and preserves existing state",
        issues,
    )
    check(startup_bootstraps_missing_root(), "startup validation bootstraps missing state", issues)
    check(docs_include_untrack_command(), "bootstrap docs record completed index cleanup", issues)

    if issues:
        print("\nRuntime bootstrap validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nRuntime bootstrap validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
