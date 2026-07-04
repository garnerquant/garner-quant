from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.trade_audit import (
    build_trade_audit_trail_from_ledger,
    clean_ledger_events,
    ledger_open_positions,
)
from execution.trade_ledger import load_trade_ledger
from execution.trade_reports import LEDGER_AUDIT_REQUIRED_COLUMNS


LEDGER_FILE = ROOT / "trade_ledger_v1.csv"
AUDIT_FILE = ROOT / "trade_audit_trail.csv"
ANALYTICS_FILE = ROOT / "trade_analytics_v3.csv"
QUARANTINE_FILE = ROOT / "data" / "legacy_trade_migration_quarantine.csv"


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric(frame, column):
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def check(condition, severity, message, issues):
    if condition:
        print(f"OK: {message}")
        return
    print(f"{severity}: {message}")
    issues.append((severity, message))


def main():
    issues = []
    ledger = load_trade_ledger(LEDGER_FILE)
    clean_events = clean_ledger_events(ledger)
    expected_audit = build_trade_audit_trail_from_ledger(ledger)
    actual_audit = read_csv(AUDIT_FILE)
    analytics = read_csv(ANALYTICS_FILE)
    quarantine = read_csv(QUARANTINE_FILE)
    open_positions = ledger_open_positions(ledger)

    print("Authoritative trade report validation")
    print(f"ledger_events={len(clean_events)}")
    print(f"expected_closed_trades={len(expected_audit)}")
    print(f"actual_audit_rows={len(actual_audit)}")
    print(f"open_positions={len(open_positions)}")

    check(not ledger.empty, "CRITICAL", "trade ledger exists and has rows", issues)
    check(
        len(actual_audit) == len(expected_audit),
        "CRITICAL",
        "audit row count matches ledger lot matching",
        issues,
    )
    missing_audit_columns = [
        column
        for column in LEDGER_AUDIT_REQUIRED_COLUMNS
        if column not in actual_audit.columns
    ]
    check(
        not missing_audit_columns,
        "CRITICAL",
        "audit file has ledger event id/source columns",
        issues,
    )

    if (
        not expected_audit.empty
        and not actual_audit.empty
        and not missing_audit_columns
    ):
        expected_pairs = set(
            zip(
                expected_audit["entry_event_id"].astype(str),
                expected_audit["exit_event_id"].astype(str),
            )
        )
        actual_pairs = set(
            zip(
                actual_audit["entry_event_id"].astype(str),
                actual_audit["exit_event_id"].astype(str),
            )
        )
        check(
            actual_pairs == expected_pairs,
            "CRITICAL",
            "audit closed trade event pairs reconcile to ledger",
            issues,
        )
        expected_pnl = round(float(numeric(expected_audit, "pnl").sum()), 6)
        actual_pnl = round(float(numeric(actual_audit, "pnl").sum()), 6)
        check(
            actual_pnl == expected_pnl,
            "HIGH",
            "audit realised PnL reconciles to ledger lot matching",
            issues,
        )

    check(not analytics.empty, "CRITICAL", "trade analytics file exists", issues)
    if not analytics.empty:
        row = analytics.iloc[0]
        analytics_closed = int(row.get("closed_trades", row.get("total_trades", 0)) or 0)
        analytics_total = int(row.get("total_trades", 0) or 0)
        analytics_open = int(row.get("open_positions", 0) or 0)
        analytics_pnl = round(float(row.get("realised_pnl", 0) or 0), 6)
        audit_pnl = round(float(numeric(actual_audit, "pnl").sum()), 6)

        check(
            str(row.get("source", "")) == "trade_ledger_v1.csv",
            "HIGH",
            "analytics source is trade ledger",
            issues,
        )
        check(
            analytics_closed == len(expected_audit)
            and analytics_total == len(expected_audit),
            "CRITICAL",
            "analytics trade count is based only on closed ledger trades",
            issues,
        )
        check(
            analytics_open == len(open_positions),
            "HIGH",
            "analytics open position count matches ledger open lots",
            issues,
        )
        check(
            analytics_pnl == audit_pnl,
            "HIGH",
            "analytics realised PnL matches audit closed trades",
            issues,
        )

    if not quarantine.empty and not actual_audit.empty:
        quarantine_source = quarantine.get(
            "source_file",
            pd.Series([""] * len(quarantine)),
        ).fillna("").astype(str)
        journal_quarantine = quarantine[
            quarantine_source.eq("trade_journal_v3.csv")
        ]
        quarantined_rows = set(
            pd.to_numeric(
                journal_quarantine.get(
                    "legacy_row_number",
                    pd.Series(dtype=float),
                ),
                errors="coerce",
            )
            .dropna()
            .astype(int)
        )
        audit_rows = set()
        for column in ["entry_legacy_row_number", "exit_legacy_row_number"]:
            if column in actual_audit.columns:
                audit_rows.update(
                    pd.to_numeric(actual_audit[column], errors="coerce")
                    .dropna()
                    .astype(int)
                    .tolist()
                )
        check(
            not bool(quarantined_rows & audit_rows),
            "CRITICAL",
            "quarantined legacy rows are excluded from audit",
            issues,
        )

    critical_or_high = [
        issue
        for issue in issues
        if issue[0] in {"CRITICAL", "HIGH"}
    ]
    print(
        "summary="
        + f"{len(issues)} issue(s), {len(critical_or_high)} critical/high issue(s)"
    )
    return 1 if critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
