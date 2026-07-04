from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import (
    broker_values_from_ledger_and_holdings,
    reconcile_broker_account_file,
    numeric,
)
from execution.atomic_io import atomic_write_json


LEDGER_FILE = ROOT / "trade_ledger_v1.csv"
BROKER_FILE = ROOT / "broker_account.csv"
HOLDINGS_FILE = ROOT / "holdings_report.csv"
REPORT_FILE = ROOT / "data" / "broker_account_reconciliation_report.json"

BROKER_COLUMNS = [
    "cash",
    "buying_power",
    "positions_value",
    "portfolio_value",
    "realised_pnl",
    "unrealised_pnl",
]

VALUE_TOLERANCE = 0.01


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def broker_row(frame):
    if frame.empty:
        return {column: 0.0 for column in BROKER_COLUMNS}

    row = frame.iloc[0].to_dict()
    return {column: numeric(row.get(column)) for column in BROKER_COLUMNS}


def target_broker_values():
    holdings = read_csv(HOLDINGS_FILE)
    return broker_values_from_ledger_and_holdings(holdings=holdings, base_dir=ROOT)


def build_reconciled_broker(existing, target):
    return pd.DataFrame(
        [
            {
                column: target[column]
                for column in BROKER_COLUMNS
            }
        ]
    )


def changed_fields(before, target):
    changes = {}
    for column in BROKER_COLUMNS:
        before_value = before.get(column, 0.0)
        after_value = target[column]
        if abs(before_value - after_value) > VALUE_TOLERANCE:
            changes[column] = {
                "before": before_value,
                "after": after_value,
                "difference": after_value - before_value,
            }
    return changes


def write_report(*, applied, before, target, changes):
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "applied": bool(applied),
        "broker_file": str(BROKER_FILE.relative_to(ROOT)),
        "ledger_file": str(LEDGER_FILE.relative_to(ROOT)),
        "holdings_file": str(HOLDINGS_FILE.relative_to(ROOT)),
        "before": before,
        "after": {column: target[column] for column in BROKER_COLUMNS},
        "open_cost_basis": target["open_cost_basis"],
        "clean_ledger_events": target["clean_ledger_events"],
        "orphan_sell_count": target["orphan_sell_count"],
        "changed_fields": changes,
    }
    atomic_write_json(report, REPORT_FILE)
    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile broker_account.csv from clean trade_ledger_v1.csv "
            "cashflows and current holdings_report.csv market value."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write broker_account.csv. Without this, only reports before/after.",
    )
    args = parser.parse_args()

    existing = read_csv(BROKER_FILE)
    before = broker_row(existing)
    target = target_broker_values()

    if target["orphan_sell_count"]:
        raise SystemExit(
            "Refusing broker reconciliation because clean ledger has orphan SELL events."
        )

    changes = changed_fields(before, target)
    if args.apply and changes:
        reconcile_result = reconcile_broker_account_file(base_dir=ROOT)
        changes = reconcile_result["differences"]

    report = write_report(
        applied=args.apply and bool(changes),
        before=before,
        target=target,
        changes=changes,
    )

    print("Broker account reconciliation")
    print(f"apply_requested={args.apply}")
    print(f"applied={report['applied']}")
    print(f"clean_ledger_events={target['clean_ledger_events']}")
    print(f"open_cost_basis={target['open_cost_basis']:.6f}")
    print("before")
    for column in BROKER_COLUMNS:
        print(f"  {column}={before.get(column, 0.0):.6f}")
    print("after")
    for column in BROKER_COLUMNS:
        print(f"  {column}={target[column]:.6f}")
    print(f"changed_fields={','.join(changes) if changes else 'none'}")
    print(f"wrote={REPORT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
