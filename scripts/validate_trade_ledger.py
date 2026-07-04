from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.trade_audit import build_trade_audit_trail
from execution.trade_reports import LEDGER_AUDIT_REQUIRED_COLUMNS
from execution.trade_ledger import (
    LEDGER_COLUMNS,
    LEDGER_FILE,
    event_signature,
    load_trade_ledger,
)


def read_csv(path):
    path = ROOT / path
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def normalise_date(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def numeric_series(frame, column):
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def check(condition, severity, message, issues):
    if condition:
        print(f"OK: {message}")
        return
    print(f"{severity}: {message}")
    issues.append((severity, message))


def ledger_to_legacy_key(frame):
    if frame.empty:
        return pd.DataFrame(columns=["date", "action", "ticker", "value"])

    rows = frame.copy()
    rows["date"] = rows["trade_date"].apply(normalise_date)
    rows["action"] = rows["action"].astype(str).str.upper().str.strip()
    rows["ticker"] = rows["ticker"].astype(str).str.upper().str.strip()
    rows["value"] = numeric_series(rows, "value").round(6)
    return rows[["date", "action", "ticker", "value"]]


def csv_to_legacy_key(frame):
    if frame.empty:
        return pd.DataFrame(columns=["date", "action", "ticker", "value"])

    rows = frame.copy()
    rows["date"] = rows["date"].apply(normalise_date)
    rows["action"] = rows["action"].astype(str).str.upper().str.strip()
    rows["ticker"] = rows["ticker"].astype(str).str.upper().str.strip()
    rows["value"] = numeric_series(rows, "value").round(6)
    return rows[["date", "action", "ticker", "value"]]


def grouped_counts(frame, label):
    if frame.empty:
        return pd.DataFrame(columns=["date", "action", "ticker", "value", label])
    return (
        frame.groupby(["date", "action", "ticker", "value"])
        .size()
        .rename(label)
        .reset_index()
    )


def compare_counts(left, left_label, right, right_label):
    left_counts = grouped_counts(left, left_label)
    right_counts = grouped_counts(right, right_label)
    merged = left_counts.merge(
        right_counts,
        how="outer",
        on=["date", "action", "ticker", "value"],
    ).fillna(0)
    return merged[merged[left_label] != merged[right_label]]


def missing_left_rows(left, left_label, right, right_label):
    left_counts = grouped_counts(left, left_label)
    right_counts = grouped_counts(right, right_label)
    merged = left_counts.merge(
        right_counts,
        how="left",
        on=["date", "action", "ticker", "value"],
    ).fillna(0)
    return merged[merged[left_label] > merged[right_label]]


def main():
    issues = []
    ledger_path = ROOT / LEDGER_FILE
    ledger = load_trade_ledger(ledger_path)
    journal = read_csv("trade_journal_v3.csv")
    transactions = read_csv("trade_transactions_v1.csv")
    portfolio = read_csv("paper_portfolio_v3.csv")
    holdings = read_csv("holdings_report.csv")
    audit_file = read_csv("trade_audit_trail.csv")

    print("Trade ledger validation")
    print(f"ledger_path={ledger_path}")
    print(f"ledger_rows={len(ledger)}")
    print(f"journal_rows={len(journal)}")
    print(f"transaction_rows={len(transactions)}")

    check(
        list(ledger.columns) == LEDGER_COLUMNS,
        "CRITICAL",
        "ledger has canonical columns",
        issues,
    )

    if not ledger_path.exists():
        print("INFO: trade_ledger_v1.csv does not exist yet; no new trades have been ledgered.")
    else:
        check(
            ledger["event_id"].astype(str).str.strip().ne("").all(),
            "CRITICAL",
            "all ledger rows have event_id",
            issues,
        )
        check(
            not ledger["event_id"].duplicated().any(),
            "CRITICAL",
            "ledger event_id values are unique",
            issues,
        )
        signatures = ledger.apply(event_signature, axis=1)
        check(
            not signatures.duplicated().any(),
            "CRITICAL",
            "ledger natural event signatures are unique",
            issues,
        )

        for column in ["shares", "price", "value"]:
            values = numeric_series(ledger, column)
            check(
                values.gt(0).all(),
                "CRITICAL",
                f"ledger {column} values are positive",
                issues,
            )

    ledger_key = ledger_to_legacy_key(ledger)
    journal_key = csv_to_legacy_key(journal)
    transaction_key = csv_to_legacy_key(transactions)

    if not ledger.empty:
        ledger_vs_journal = missing_left_rows(
            ledger_key,
            "ledger",
            journal_key,
            "journal",
        )
        check(
            ledger_vs_journal.empty,
            "HIGH",
            "all ledger rows are present in trade_journal_v3.csv",
            issues,
        )
        if not ledger_vs_journal.empty:
            print(ledger_vs_journal.to_string(index=False))

        ledger_vs_transactions = missing_left_rows(
            ledger_key,
            "ledger",
            transaction_key,
            "transactions",
        )
        check(
            ledger_vs_transactions.empty,
            "HIGH",
            "all ledger rows are present in trade_transactions_v1.csv",
            issues,
        )
        if not ledger_vs_transactions.empty:
            print(ledger_vs_transactions.to_string(index=False))

    check(
        not journal.empty,
        "HIGH",
        "legacy trade journal is present for backward compatibility",
        issues,
    )
    if not journal.empty:
        duplicate_legacy = journal.duplicated().sum()
        check(
            duplicate_legacy == 0,
            "MEDIUM",
            "legacy trade journal has no exact duplicate rows",
            issues,
        )
        if {"price", "shares", "value"}.issubset(journal.columns):
            calc_value = numeric_series(journal, "price") * numeric_series(journal, "shares")
            diff = (calc_value - numeric_series(journal, "value")).abs().max()
            check(
                diff <= 1e-6,
                "HIGH",
                "legacy trade journal price * shares equals value",
                issues,
            )

    if not portfolio.empty and not holdings.empty:
        portfolio_tickers = set(portfolio["ticker"].dropna().astype(str).str.upper())
        holdings_tickers = set(holdings["ticker"].dropna().astype(str).str.upper())
        check(
            portfolio_tickers == holdings_tickers,
            "HIGH",
            "paper portfolio tickers match holdings report tickers",
            issues,
        )

    missing_audit_columns = [
        column
        for column in LEDGER_AUDIT_REQUIRED_COLUMNS
        if column not in audit_file.columns
    ]
    audit_source = ""
    if not audit_file.empty and "source" in audit_file.columns:
        source_values = audit_file["source"].dropna().astype(str).str.strip()
        if not source_values.empty:
            audit_source = str(source_values.iloc[0])
    if not ledger.empty:
        check(
            not audit_file.empty,
            "HIGH",
            "trade_audit_trail.csv exists for authoritative ledger output",
            issues,
        )
        check(
            not missing_audit_columns,
            "HIGH",
            "trade_audit_trail.csv has ledger event id/source columns",
            issues,
        )
        check(
            audit_source == "trade_ledger_v1.csv",
            "HIGH",
            "trade_audit_trail.csv is authoritative ledger output",
            issues,
        )
    else:
        rebuilt_audit = build_trade_audit_trail(journal)
        check(
            len(rebuilt_audit) == len(audit_file),
            "MEDIUM",
            "trade_audit_trail.csv row count matches rebuilt legacy audit",
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
