from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import (  # noqa: E402
    BROKER_COLUMNS,
    commit_broker_account_frame,
    validate_broker_frame,
)
from execution.atomic_io import assert_no_atomic_artifacts  # noqa: E402


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def broker_frame():
    return pd.DataFrame(
        [
            {
                "cash": 10000.0,
                "buying_power": 10000.0,
                "positions_value": 125.0,
                "portfolio_value": 10125.0,
                "realised_pnl": 25.0,
                "unrealised_pnl": 10.0,
            }
        ]
    )


def scratch_path(token):
    return ROOT / f"atomic_broker_{token}_broker_account.csv"


def cleanup(path):
    path.unlink(missing_ok=True)
    for artifact in ROOT.glob(f".{path.name}.atomic-*"):
        artifact.unlink(missing_ok=True)


def simulate_failure(stage_to_fail):
    token = uuid4().hex
    path = scratch_path(token)
    original = "cash,buying_power,positions_value,portfolio_value,realised_pnl,unrealised_pnl\n1,1,2,3,4,5\n"
    path.write_text(original, encoding="utf-8")
    replaced = 0

    def failure_hook(stage, _target):
        nonlocal replaced
        if stage_to_fail == "after_temp_writes" and stage == "after_temp_writes":
            raise RuntimeError("simulated temp barrier failure")
        if stage_to_fail == "after_first_replace" and stage == "after_replace":
            replaced += 1
            if replaced == 1:
                raise RuntimeError("simulated replace failure")

    try:
        try:
            commit_broker_account_frame(
                broker_frame(),
                path,
                failure_hook=failure_hook,
            )
        except Exception:
            pass

        artifacts = list(ROOT.glob(f".{path.name}.atomic-*"))
        return path.read_text(encoding="utf-8") == original and not artifacts
    finally:
        cleanup(path)


def production_broker_parseable():
    path = ROOT / "broker_account.csv"
    if path.exists():
        pd.read_csv(path)
    return True


def accounting_has_no_direct_broker_to_csv():
    source = (ROOT / "execution" / "accounting.py").read_text(encoding="utf-8")
    return "commit_broker_account_frame" in source and ".to_csv(" not in source


def invalid_frame_rejected():
    invalid = broker_frame()
    invalid.loc[0, "portfolio_value"] = 1.0
    try:
        validate_broker_frame(invalid)
    except ValueError:
        return True
    return False


def main():
    issues = []

    try:
        assert_no_atomic_artifacts(ROOT)
        no_artifacts = True
    except Exception as exc:
        print(exc)
        no_artifacts = False

    check(no_artifacts, "no unfinished atomic artifacts exist", issues)
    check(production_broker_parseable(), "broker_account.csv is parseable", issues)
    check(
        accounting_has_no_direct_broker_to_csv(),
        "reconcile_broker_account_file has no direct CSV write path",
        issues,
    )
    check(invalid_frame_rejected(), "invalid broker frame is rejected before write", issues)
    check(
        simulate_failure("after_temp_writes"),
        "temp-write failure leaves broker file unchanged",
        issues,
    )
    check(
        simulate_failure("after_first_replace"),
        "replace failure rolls back broker file",
        issues,
    )

    if issues:
        print("\nAtomic broker reconciliation validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nAtomic broker reconciliation validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
