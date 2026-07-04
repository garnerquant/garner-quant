from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.atomic_io import (  # noqa: E402
    assert_no_atomic_artifacts,
    atomic_write_csv_frames,
)


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def simulate_temp_write_failure():
    token = uuid4().hex
    first = ROOT / f"atomic_validation_{token}_first.csv"
    second = ROOT / f"atomic_validation_{token}_second.csv"
    try:
        first.write_text("id,value\n1,original\n", encoding="utf-8")
        second.write_text("id,value\n2,original\n", encoding="utf-8")

        def fail_after_temp_writes(stage, _target):
            if stage == "after_temp_writes":
                raise RuntimeError("simulated temp-write barrier failure")

        try:
            atomic_write_csv_frames(
                {
                    first: pd.DataFrame([{"id": 1, "value": "updated"}]),
                    second: pd.DataFrame([{"id": 2, "value": "updated"}]),
                },
                failure_hook=fail_after_temp_writes,
            )
        except Exception:
            pass

        return (
            read_text(first) == "id,value\n1,original\n"
            and read_text(second) == "id,value\n2,original\n"
            and not list(ROOT.glob(f".atomic_validation_{token}_*.atomic-*"))
        )
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
        for artifact in ROOT.glob(f".atomic_validation_{token}_*.atomic-*"):
            artifact.unlink(missing_ok=True)


def simulate_replace_failure_rollback():
    token = uuid4().hex
    first = ROOT / f"atomic_validation_{token}_first.csv"
    second = ROOT / f"atomic_validation_{token}_second.csv"
    try:
        first.write_text("id,value\n1,original\n", encoding="utf-8")
        second.write_text("id,value\n2,original\n", encoding="utf-8")
        replaced = 0

        def fail_after_first_replace(stage, _target):
            nonlocal replaced
            if stage == "after_replace":
                replaced += 1
                if replaced == 1:
                    raise RuntimeError("simulated replace failure")

        try:
            atomic_write_csv_frames(
                {
                    first: pd.DataFrame([{"id": 1, "value": "updated"}]),
                    second: pd.DataFrame([{"id": 2, "value": "updated"}]),
                },
                failure_hook=fail_after_first_replace,
            )
        except Exception:
            pass

        return (
            read_text(first) == "id,value\n1,original\n"
            and read_text(second) == "id,value\n2,original\n"
            and not list(ROOT.glob(f".atomic_validation_{token}_*.atomic-*"))
        )
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
        for artifact in ROOT.glob(f".atomic_validation_{token}_*.atomic-*"):
            artifact.unlink(missing_ok=True)


def production_csvs_are_parseable():
    files = [
        ROOT / "trade_ledger_v1.csv",
        ROOT / "paper_portfolio_v3.csv",
        ROOT / "trade_journal_v3.csv",
        ROOT / "trade_transactions_v1.csv",
        ROOT / "trade_snapshots.csv",
    ]
    for path in files:
        if path.exists():
            pd.read_csv(path)
    return True


def main():
    issues = []

    try:
        assert_no_atomic_artifacts(ROOT)
        no_artifacts = True
    except Exception as exc:
        print(exc)
        no_artifacts = False

    check(no_artifacts, "no unfinished atomic trade-state artifacts exist", issues)
    check(
        production_csvs_are_parseable(),
        "trade-state CSV files are parseable",
        issues,
    )
    check(
        simulate_temp_write_failure(),
        "temp-write failure leaves existing files unchanged",
        issues,
    )
    check(
        simulate_replace_failure_rollback(),
        "replace failure rolls back already replaced files",
        issues,
    )

    if issues:
        print("\nAtomic trade-state validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic trade-state validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
