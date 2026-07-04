from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ASSETS
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from execution.trade_ledger import (
    LEDGER_FILE,
    append_trade_events,
    build_trade_event,
    load_trade_ledger,
)


JOURNAL_FILE = "trade_journal_v3.csv"
TRANSACTION_FILE = "trade_transactions_v1.csv"
PORTFOLIO_FILE = "paper_portfolio_v3.csv"
AUDIT_FILE = "trade_audit_trail.csv"
QUARANTINE_FILE = Path("data") / "legacy_trade_migration_quarantine.csv"
REPORT_FILE = Path("data") / "legacy_trade_migration_report.json"
BACKFILLED_FILE = Path("data") / "legacy_trade_migration_backfilled.csv"

ROUND_DP = 6
TOLERANCE = 1e-6


def read_csv(relative_path):
    path = ROOT / relative_path
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def clean_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def safe_float(value, default=None):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


def normalise_date(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def normalise_time(value):
    text = clean_text(value)
    if not text:
        return "00:00:00"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.strftime("%H:%M:%S")


def timestamp_from_row(row):
    date_text = normalise_date(row.get("date"))
    time_text = normalise_time(row.get("time"))
    if not date_text:
        return ""
    return f"{date_text} {time_text}"


def legacy_key(row):
    return (
        normalise_date(row.get("date")),
        clean_text(row.get("action")).upper(),
        clean_text(row.get("ticker")).upper(),
        round(safe_float(row.get("value"), 0.0), ROUND_DP),
    )


def row_payload(row, source_file, reason, details=""):
    return {
        "source_file": source_file,
        "legacy_row_number": int(row.get("legacy_row_number", 0) or 0),
        "date": clean_text(row.get("date")),
        "time": clean_text(row.get("time")),
        "action": clean_text(row.get("action")).upper(),
        "ticker": clean_text(row.get("ticker")).upper(),
        "price": row.get("price", ""),
        "shares": row.get("shares", ""),
        "value": row.get("value", ""),
        "reason": reason,
        "details": details,
    }


def prepare_journal():
    journal = read_csv(JOURNAL_FILE)
    if journal.empty:
        return journal

    journal = journal.copy()
    journal["legacy_row_number"] = journal.index + 2
    for column in ["price", "shares", "value", "pnl", "pnl_percent"]:
        if column not in journal.columns:
            journal[column] = 0.0
        journal[column] = pd.to_numeric(journal[column], errors="coerce")
    for column in ["date", "time", "action", "ticker", "reason"]:
        if column not in journal.columns:
            journal[column] = ""
    journal["_timestamp"] = journal.apply(timestamp_from_row, axis=1)
    journal["_date_norm"] = journal["date"].apply(normalise_date)
    journal["_action_norm"] = journal["action"].astype(str).str.upper().str.strip()
    journal["_ticker_norm"] = journal["ticker"].astype(str).str.upper().str.strip()
    journal["_legacy_key"] = journal.apply(legacy_key, axis=1)
    return journal


def prepare_transactions():
    transactions = read_csv(TRANSACTION_FILE)
    if transactions.empty:
        return transactions

    transactions = transactions.copy()
    transactions["legacy_row_number"] = transactions.index + 2
    for column in ["price", "shares", "value"]:
        if column not in transactions.columns:
            transactions[column] = 0.0
        transactions[column] = pd.to_numeric(transactions[column], errors="coerce")
    for column in ["date", "action", "ticker", "reason"]:
        if column not in transactions.columns:
            transactions[column] = ""
    transactions["_legacy_key"] = transactions.apply(legacy_key, axis=1)
    return transactions


def prepare_portfolio():
    portfolio = read_csv(PORTFOLIO_FILE)
    if portfolio.empty:
        return {}

    by_ticker = {}
    for _, row in portfolio.iterrows():
        ticker = clean_text(row.get("ticker")).upper()
        if not ticker:
            continue
        by_ticker[ticker] = {
            "entry_date": normalise_date(row.get("entry_date")),
            "entry_price": safe_float(row.get("entry_price"), 0.0),
            "shares": safe_float(row.get("shares"), 0.0),
            "position_value": safe_float(row.get("position_value"), 0.0),
        }
    return by_ticker


def exact_duplicate_extra_rows(journal):
    if journal.empty:
        return set()
    legacy_columns = [
        column
        for column in [
            "date",
            "time",
            "action",
            "ticker",
            "price",
            "shares",
            "value",
            "pnl",
            "pnl_percent",
            "reason",
        ]
        if column in journal.columns
    ]
    duplicates = journal.duplicated(subset=legacy_columns, keep="first")
    return set(journal.loc[duplicates, "legacy_row_number"].astype(int))


def transaction_match_flags(journal, transactions):
    remaining = Counter(transactions["_legacy_key"].tolist()) if not transactions.empty else Counter()
    matched = {}
    for _, row in journal.iterrows():
        row_number = int(row["legacy_row_number"])
        key = row["_legacy_key"]
        if remaining[key] > 0:
            matched[row_number] = True
            remaining[key] -= 1
        else:
            matched[row_number] = False
    return matched, remaining


def transaction_rows_missing_from_journal(journal, transactions):
    journal_counts = Counter(journal["_legacy_key"].tolist()) if not journal.empty else Counter()
    rows = []
    if transactions.empty:
        return rows

    for _, row in transactions.iterrows():
        key = row["_legacy_key"]
        if journal_counts[key] > 0:
            journal_counts[key] -= 1
            continue
        rows.append(
            row_payload(
                row,
                TRANSACTION_FILE,
                "transaction_log_row_missing_from_journal",
                "Transaction event has no matching journal row by date/action/ticker/value.",
            )
        )
    return rows


def is_current_open_buy(row, current_portfolio):
    ticker = row["_ticker_norm"]
    current = current_portfolio.get(ticker)
    if current is None:
        return False

    return (
        abs(safe_float(row.get("shares"), 0.0) - current["shares"]) <= TOLERANCE
        and abs(safe_float(row.get("price"), 0.0) - current["entry_price"]) <= TOLERANCE
        and abs(safe_float(row.get("value"), 0.0) - current["position_value"]) <= TOLERANCE
    )


def row_to_event(row, migration_status):
    ticker = row["_ticker_norm"]
    action = row["_action_norm"]
    row_number = int(row["legacy_row_number"])
    legacy_trade_id = f"{JOURNAL_FILE}:{row_number}"
    currency = ASSETS.get(ticker, {}).get("listing_currency") or "UNKNOWN"

    return build_trade_event(
        timestamp=row["_timestamp"],
        trade_date=row["_date_norm"],
        trade_time=normalise_time(row.get("time")),
        ticker=ticker,
        action=action,
        shares=safe_float(row.get("shares"), 0.0),
        price=safe_float(row.get("price"), 0.0),
        value=safe_float(row.get("value"), 0.0),
        fees=0.0,
        currency=currency,
        source="legacy_migration",
        mode="paper",
        status="RECORDED",
        reason=clean_text(row.get("reason")),
        legacy_trade_id=legacy_trade_id,
        run_id="legacy_trade_history_migration_v1",
        position_id=f"{ticker}_{row['_date_norm']}",
        pnl=safe_float(row.get("pnl"), 0.0),
        pnl_percent=safe_float(row.get("pnl_percent"), 0.0),
        legacy_source_file=JOURNAL_FILE,
        legacy_row_number=row_number,
        migration_status=migration_status,
        quarantine_reason="",
    )


def analyse_legacy_history():
    journal = prepare_journal()
    transactions = prepare_transactions()
    current_portfolio = prepare_portfolio()
    audit = read_csv(AUDIT_FILE)

    quarantine = []
    valid_events = []
    valid_row_numbers = set()
    duplicate_rows = exact_duplicate_extra_rows(journal)
    transaction_matched, unmatched_transaction_counts = transaction_match_flags(
        journal,
        transactions,
    )

    for _, row in journal.iterrows():
        row_number = int(row["legacy_row_number"])
        reasons = []

        if row_number in duplicate_rows:
            reasons.append("exact_duplicate_journal_row")
        if not transaction_matched.get(row_number, False):
            reasons.append("journal_row_missing_from_transaction_log")
        if not row["_date_norm"]:
            reasons.append("invalid_trade_date")
        if row["_action_norm"] not in {"BUY", "SELL"}:
            reasons.append("invalid_action")
        if not row["_ticker_norm"]:
            reasons.append("missing_ticker")
        for column in ["price", "shares", "value"]:
            if safe_float(row.get(column), 0.0) <= 0:
                reasons.append(f"invalid_{column}")

        if reasons:
            quarantine.append(
                row_payload(
                    row,
                    JOURNAL_FILE,
                    "; ".join(reasons),
                    "Rejected before lifecycle matching.",
                )
            )
            continue

        valid_row_numbers.add(row_number)

    open_lots = defaultdict(deque)
    paired_buy_rows = set()
    paired_sell_rows = set()
    open_buy_rows = set()

    for _, row in journal.sort_values(["_timestamp", "legacy_row_number"]).iterrows():
        row_number = int(row["legacy_row_number"])
        if row_number not in valid_row_numbers:
            continue

        ticker = row["_ticker_norm"]
        if row["_action_norm"] == "BUY":
            open_lots[ticker].append(row)
            continue

        if not open_lots[ticker]:
            quarantine.append(
                row_payload(
                    row,
                    JOURNAL_FILE,
                    "orphan_sell_no_prior_valid_buy",
                    "SELL cannot be matched to a previous valid BUY lot.",
                )
            )
            valid_row_numbers.remove(row_number)
            continue

        buy_row = open_lots[ticker].popleft()
        paired_buy_rows.add(int(buy_row["legacy_row_number"]))
        paired_sell_rows.add(row_number)

    for lots in open_lots.values():
        for row in lots:
            row_number = int(row["legacy_row_number"])
            if is_current_open_buy(row, current_portfolio):
                open_buy_rows.add(row_number)
            else:
                quarantine.append(
                    row_payload(
                        row,
                        JOURNAL_FILE,
                        "unmatched_buy_not_current_open_position",
                        "BUY was not closed by a valid SELL and does not match current paper portfolio.",
                    )
                )
                valid_row_numbers.discard(row_number)

    for _, row in journal.sort_values(["_timestamp", "legacy_row_number"]).iterrows():
        row_number = int(row["legacy_row_number"])
        if row_number not in valid_row_numbers:
            continue

        if row_number in paired_buy_rows:
            migration_status = "BACKFILLED_CLOSED_BUY"
        elif row_number in paired_sell_rows:
            migration_status = "BACKFILLED_CLOSED_SELL"
        elif row_number in open_buy_rows:
            migration_status = "BACKFILLED_OPEN_BUY"
        else:
            quarantine.append(
                row_payload(
                    row,
                    JOURNAL_FILE,
                    "unclassified_valid_candidate",
                    "Row passed early checks but was not classified as closed or current-open.",
                )
            )
            continue

        valid_events.append(row_to_event(row, migration_status))

    quarantine.extend(transaction_rows_missing_from_journal(journal, transactions))

    audit_rebuildable = len(paired_sell_rows)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "journal_rows": int(len(journal)),
        "transaction_rows": int(len(transactions)),
        "audit_rows": int(len(audit)),
        "valid_backfill_events": int(len(valid_events)),
        "quarantined_rows": int(len(quarantine)),
        "duplicate_journal_rows": int(len(duplicate_rows)),
        "orphan_sells": int(
            sum(1 for row in quarantine if row["reason"] == "orphan_sell_no_prior_valid_buy")
        ),
        "unmatched_open_buys_backfilled": int(len(open_buy_rows)),
        "unmatched_buys_quarantined": int(
            sum(
                1
                for row in quarantine
                if row["reason"] == "unmatched_buy_not_current_open_position"
            )
        ),
        "transaction_rows_missing_from_journal": int(
            sum(
                1
                for row in quarantine
                if row["reason"] == "transaction_log_row_missing_from_journal"
            )
        ),
        "journal_rows_missing_from_transaction_log": int(
            sum(
                1
                for row in quarantine
                if "journal_row_missing_from_transaction_log" in row["reason"]
            )
        ),
        "audit_rows_rebuildable_from_valid_pairs": int(audit_rebuildable),
        "audit_rows_not_rebuilt_from_valid_pairs": int(max(0, len(audit) - audit_rebuildable)),
        "unmatched_transaction_key_counts": {
            "|".join(str(part) for part in key): int(count)
            for key, count in unmatched_transaction_counts.items()
            if count
        },
        "backfill_status_counts": dict(
            Counter(event["migration_status"] for event in valid_events)
        ),
        "quarantine_reason_counts": dict(
            Counter(row["reason"] for row in quarantine)
        ),
    }
    return valid_events, quarantine, report


def write_reports(valid_events, quarantine, report):
    atomic_write_csv_frames(
        {
            ROOT / QUARANTINE_FILE: pd.DataFrame(quarantine),
            ROOT / BACKFILLED_FILE: pd.DataFrame(valid_events),
        }
    )
    atomic_write_json(report, ROOT / REPORT_FILE)


def apply_backfill(valid_events):
    ledger = load_trade_ledger(ROOT / LEDGER_FILE)
    existing_legacy_ids = {
        clean_text(value)
        for value in ledger.get("legacy_trade_id", pd.Series(dtype=str)).dropna()
        if clean_text(value)
    }
    new_events = [
        event
        for event in valid_events
        if clean_text(event.get("legacy_trade_id")) not in existing_legacy_ids
    ]
    if new_events:
        append_trade_events(new_events, path=ROOT / LEDGER_FILE)
    return new_events, len(valid_events) - len(new_events)


def print_report(report, applied=False, appended=0, skipped_existing=0):
    mode = "APPLY" if applied else "DRY_RUN"
    print(f"legacy_trade_migration_mode={mode}")
    for key in [
        "journal_rows",
        "transaction_rows",
        "audit_rows",
        "valid_backfill_events",
        "quarantined_rows",
        "duplicate_journal_rows",
        "orphan_sells",
        "unmatched_open_buys_backfilled",
        "unmatched_buys_quarantined",
        "transaction_rows_missing_from_journal",
        "journal_rows_missing_from_transaction_log",
        "audit_rows_rebuildable_from_valid_pairs",
        "audit_rows_not_rebuilt_from_valid_pairs",
    ]:
        print(f"{key}={report[key]}")
    if applied:
        print(f"ledger_events_appended={appended}")
        print(f"ledger_events_skipped_existing={skipped_existing}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyse and backfill valid legacy trade history into trade_ledger_v1.csv."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write valid backfill events to the ledger and write migration reports.",
    )
    args = parser.parse_args(argv)

    valid_events, quarantine, report = analyse_legacy_history()
    appended = 0
    skipped_existing = 0

    if args.apply:
        new_events, skipped_existing = apply_backfill(valid_events)
        appended = len(new_events)
        refreshed_ledger = load_trade_ledger(ROOT / LEDGER_FILE)
        backfilled_present = int(
            refreshed_ledger["migration_status"]
            .astype(str)
            .str.startswith("BACKFILLED")
            .sum()
            if not refreshed_ledger.empty
            else 0
        )
        report["ledger_events_appended"] = appended
        report["ledger_events_skipped_existing"] = skipped_existing
        report["ledger_backfilled_events_present"] = backfilled_present
        report["ledger_file"] = LEDGER_FILE
        report["quarantine_file"] = str(QUARANTINE_FILE)
        report["backfilled_file"] = str(BACKFILLED_FILE)
        write_reports(valid_events, quarantine, report)

    print_report(
        report,
        applied=args.apply,
        appended=appended,
        skipped_existing=skipped_existing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
