from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ASSETS
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event, load_trade_ledger


LEDGER_FILE = ROOT / "trade_ledger_v1.csv"
PORTFOLIO_FILE = ROOT / "paper_portfolio_v3.csv"
HOLDINGS_FILE = ROOT / "holdings_report.csv"
JOURNAL_FILE = ROOT / "trade_journal_v3.csv"
REPORT_FILE = ROOT / "data" / "ledger_open_lot_reconciliation_report.json"
ACTIONS_FILE = ROOT / "data" / "ledger_open_lot_reconciliation_actions.csv"

QUARANTINE_STATUS = "QUARANTINED_OPEN_LOT_MISMATCH"
QUARANTINE_REASON = (
    "Ledger open lot is absent from current paper_portfolio_v3.csv and "
    "holdings_report.csv; treated as invalid legacy migration residue."
)
CORRECTION_STATUS = "RECONCILED_CURRENT_OPEN_BUY"
CORRECTION_REASON = (
    "Ledger open lot was stale; replaced from current journal-backed paper "
    "portfolio open BUY."
)
VALUE_TOLERANCE = 1e-6
SHARE_TOLERANCE = 1e-9


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def clean_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def safe_float(value, default=0.0) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


def normalise_date(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def normalise_time(value) -> str:
    text = clean_text(value)
    if not text:
        return "00:00:00"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.strftime("%H:%M:%S")


def timestamp_from_parts(date_value, time_value) -> str:
    date_text = normalise_date(date_value)
    if not date_text:
        return ""
    return f"{date_text} {normalise_time(time_value)}"


def current_tickers(*frames: pd.DataFrame) -> set[str]:
    tickers: set[str] = set()
    for frame in frames:
        if frame.empty or "ticker" not in frame.columns:
            continue
        tickers.update(
            frame["ticker"].fillna("").astype(str).str.strip().str.upper().dropna()
        )
    return {ticker for ticker in tickers if ticker}


def current_open_buy_candidates(journal: pd.DataFrame, portfolio: pd.DataFrame):
    if journal.empty or portfolio.empty:
        return {}

    journal_rows = journal.copy()
    journal_rows["legacy_row_number"] = journal_rows.index + 2
    for column in ["price", "shares", "value"]:
        if column not in journal_rows.columns:
            journal_rows[column] = 0.0
        journal_rows[column] = pd.to_numeric(journal_rows[column], errors="coerce")
    for column in ["date", "time", "action", "ticker", "reason"]:
        if column not in journal_rows.columns:
            journal_rows[column] = ""
    journal_rows["_ticker_norm"] = (
        journal_rows["ticker"].fillna("").astype(str).str.strip().str.upper()
    )
    journal_rows["_action_norm"] = (
        journal_rows["action"].fillna("").astype(str).str.strip().str.upper()
    )
    journal_rows["_timestamp"] = journal_rows.apply(
        lambda row: timestamp_from_parts(row.get("date"), row.get("time")),
        axis=1,
    )
    journal_rows = journal_rows[journal_rows["_action_norm"].eq("BUY")].copy()

    candidates = {}
    for _, portfolio_row in portfolio.iterrows():
        ticker = clean_text(portfolio_row.get("ticker")).upper()
        if not ticker:
            continue
        entry_price = safe_float(portfolio_row.get("entry_price"))
        shares = safe_float(portfolio_row.get("shares"))
        value = safe_float(portfolio_row.get("position_value"))
        matches = journal_rows[
            journal_rows["_ticker_norm"].eq(ticker)
            & (journal_rows["price"].sub(entry_price).abs() <= VALUE_TOLERANCE)
            & (journal_rows["shares"].sub(shares).abs() <= SHARE_TOLERANCE)
            & (journal_rows["value"].sub(value).abs() <= VALUE_TOLERANCE)
        ].copy()
        if matches.empty:
            continue
        matches["_sort_time"] = pd.to_datetime(
            matches["_timestamp"],
            errors="coerce",
        )
        row = matches.sort_values(["_sort_time", "legacy_row_number"]).iloc[-1]
        candidates[ticker] = {
            "ticker": ticker,
            "timestamp": row["_timestamp"],
            "trade_date": normalise_date(row.get("date")),
            "trade_time": normalise_time(row.get("time")),
            "shares": safe_float(row.get("shares")),
            "price": safe_float(row.get("price")),
            "value": safe_float(row.get("value")),
            "reason": clean_text(row.get("reason")) or "SIGNAL ENTRY",
            "legacy_row_number": int(row.get("legacy_row_number")),
        }
    return candidates


def ledger_lot_state(ledger: pd.DataFrame):
    events = clean_ledger_events(ledger)
    open_lots = defaultdict(deque)
    matches = []
    orphans = []

    for _, row in events.iterrows():
        ticker = str(row["ticker"]).upper()
        action = str(row["action"]).upper()

        if action == "BUY":
            lot = row.copy()
            lot["remaining_shares"] = float(row["shares"])
            open_lots[ticker].append(lot)
            continue

        remaining_sell_shares = float(row["shares"])
        while remaining_sell_shares > 1e-12 and open_lots[ticker]:
            open_trade = open_lots[ticker][0]
            matched_shares = min(
                float(open_trade["remaining_shares"]),
                remaining_sell_shares,
            )
            matches.append(
                {
                    "ticker": ticker,
                    "entry_event_id": open_trade.get("event_id", ""),
                    "exit_event_id": row.get("event_id", ""),
                    "entry_legacy_row_number": open_trade.get(
                        "legacy_row_number",
                        "",
                    ),
                    "exit_legacy_row_number": row.get("legacy_row_number", ""),
                    "matched_shares": matched_shares,
                }
            )
            open_trade["remaining_shares"] = (
                float(open_trade["remaining_shares"]) - matched_shares
            )
            remaining_sell_shares -= matched_shares
            if float(open_trade["remaining_shares"]) <= 1e-12:
                open_lots[ticker].popleft()

        if remaining_sell_shares > 1e-12:
            orphans.append(
                {
                    "ticker": ticker,
                    "exit_event_id": row.get("event_id", ""),
                    "exit_legacy_row_number": row.get("legacy_row_number", ""),
                    "unmatched_shares": remaining_sell_shares,
                }
            )

    open_rows = []
    for ticker, lots in open_lots.items():
        for lot in lots:
            remaining = float(lot["remaining_shares"])
            if remaining <= 1e-12:
                continue
            open_rows.append(
                {
                    "ticker": ticker,
                    "event_id": lot.get("event_id", ""),
                    "legacy_source_file": lot.get("legacy_source_file", ""),
                    "legacy_row_number": lot.get("legacy_row_number", ""),
                    "remaining_shares": remaining,
                    "original_shares": float(lot.get("shares", 0.0) or 0.0),
                    "timestamp": lot.get("timestamp", ""),
                    "price": float(lot.get("price", 0.0) or 0.0),
                }
            )

    return (
        pd.DataFrame(open_rows),
        pd.DataFrame(matches),
        pd.DataFrame(orphans),
    )


def build_correction_event(candidate):
    ticker = candidate["ticker"]
    row_number = int(candidate["legacy_row_number"])
    return build_trade_event(
        timestamp=candidate["timestamp"],
        trade_date=candidate["trade_date"],
        trade_time=candidate["trade_time"],
        ticker=ticker,
        action="BUY",
        shares=candidate["shares"],
        price=candidate["price"],
        value=candidate["value"],
        fees=0.0,
        currency=ASSETS.get(ticker, {}).get("listing_currency") or "UNKNOWN",
        source="ledger_open_lot_reconciliation",
        mode="paper",
        status="RECORDED",
        reason=candidate["reason"],
        legacy_trade_id=f"trade_journal_v3.csv:{row_number}",
        run_id="ledger_open_lot_reconciliation_v1",
        position_id=f"{ticker}_{candidate['trade_date']}",
        pnl=0.0,
        pnl_percent=0.0,
        legacy_source_file="trade_journal_v3.csv",
        legacy_row_number=row_number,
        migration_status=CORRECTION_STATUS,
        quarantine_reason="",
    )


def build_actions(ledger, portfolio, holdings, journal):
    open_lots, matches, orphans = ledger_lot_state(ledger)
    active_tickers = current_tickers(portfolio, holdings)
    current_candidates = current_open_buy_candidates(journal, portfolio)

    if open_lots.empty:
        missing_open_lots = pd.DataFrame()
    else:
        missing_open_lots = open_lots[
            ~open_lots["ticker"].astype(str).str.upper().isin(active_tickers)
        ].copy()

    event_ids = set()
    if not missing_open_lots.empty:
        event_ids.update(missing_open_lots["event_id"].astype(str))

    correction_events = []
    correction_event_ids = set()
    if not open_lots.empty:
        for _, lot in open_lots.iterrows():
            ticker = clean_text(lot.get("ticker")).upper()
            candidate = current_candidates.get(ticker)
            if not candidate:
                continue
            lot_shares = safe_float(lot.get("remaining_shares"))
            lot_price = safe_float(lot.get("price"))
            lot_value = lot_shares * lot_price
            lot_legacy_row = safe_float(lot.get("legacy_row_number"), default=-1)
            mismatched = (
                abs(lot_shares - candidate["shares"]) > SHARE_TOLERANCE
                or abs(lot_price - candidate["price"]) > VALUE_TOLERANCE
                or abs(lot_value - candidate["value"]) > VALUE_TOLERANCE
                or int(lot_legacy_row) != int(candidate["legacy_row_number"])
            )
            if not mismatched:
                continue
            event_id = clean_text(lot.get("event_id"))
            correction_event_ids.add(event_id)
            correction_events.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "action": "BUY",
                    "legacy_source_file": lot.get("legacy_source_file", ""),
                    "legacy_row_number": lot.get("legacy_row_number", ""),
                    "previous_status": "RECORDED",
                    "previous_migration_status": lot.get("migration_status", ""),
                    "new_status": "RECORDED",
                    "new_migration_status": CORRECTION_STATUS,
                    "reason": CORRECTION_REASON,
                    "replacement_event": build_correction_event(candidate),
                }
            )

    touched_sells = pd.DataFrame()
    if event_ids and not matches.empty:
        touched_sells = matches[matches["entry_event_id"].astype(str).isin(event_ids)]
        event_ids.update(touched_sells["exit_event_id"].astype(str))

    actions = []
    for event_id in sorted(event_ids - correction_event_ids):
        source = ledger[ledger["event_id"].astype(str).eq(event_id)]
        if source.empty:
            continue
        row = source.iloc[0]
        actions.append(
            {
                "event_id": event_id,
                "ticker": row.get("ticker", ""),
                "action": row.get("action", ""),
                "legacy_source_file": row.get("legacy_source_file", ""),
                "legacy_row_number": row.get("legacy_row_number", ""),
                "previous_status": row.get("status", ""),
                "previous_migration_status": row.get("migration_status", ""),
                "new_status": "REJECTED",
                "new_migration_status": QUARANTINE_STATUS,
                "reason": QUARANTINE_REASON,
                "replacement_event": None,
            }
        )

    actions.extend(correction_events)

    if not actions:
        status = ledger.get("status", pd.Series([""] * len(ledger)))
        migration_status = ledger.get(
            "migration_status",
            pd.Series([""] * len(ledger)),
        )
        already_quarantined = ledger[
            status.fillna("").astype(str).str.upper().eq("REJECTED")
            & migration_status.fillna("").astype(str).str.upper().eq(
                QUARANTINE_STATUS
            )
        ]
        for _, row in already_quarantined.iterrows():
            actions.append(
                {
                    "event_id": row.get("event_id", ""),
                    "ticker": row.get("ticker", ""),
                    "action": row.get("action", ""),
                    "legacy_source_file": row.get("legacy_source_file", ""),
                    "legacy_row_number": row.get("legacy_row_number", ""),
                    "previous_status": row.get("status", ""),
                    "previous_migration_status": row.get("migration_status", ""),
                    "new_status": "REJECTED",
                    "new_migration_status": QUARANTINE_STATUS,
                    "reason": row.get("quarantine_reason", QUARANTINE_REASON),
                    "replacement_event": None,
                }
            )

    return (
        pd.DataFrame(actions),
        missing_open_lots,
        touched_sells,
        orphans,
    )


def apply_actions(ledger: pd.DataFrame, actions: pd.DataFrame):
    if actions.empty:
        return ledger, 0

    updated = ledger.copy()
    for column in ["status", "migration_status", "quarantine_reason"]:
        if column not in updated.columns:
            updated[column] = ""
        updated[column] = updated[column].fillna("").astype(str)

    changed = 0
    action_ids = set(actions["event_id"].astype(str))
    mask = updated["event_id"].astype(str).isin(action_ids)

    for index in updated[mask].index:
        action_row = actions[actions["event_id"].astype(str).eq(str(updated.at[index, "event_id"]))].iloc[0]
        replacement_event = action_row.get("replacement_event")
        if isinstance(replacement_event, dict):
            for column in LEDGER_COLUMNS:
                updated.at[index, column] = replacement_event.get(column, "")
            changed += 1
            continue

        already_done = (
            str(updated.at[index, "status"]).upper() == "REJECTED"
            and str(updated.at[index, "migration_status"]).upper()
            == QUARANTINE_STATUS
        )
        if already_done:
            continue
        updated.at[index, "status"] = "REJECTED"
        updated.at[index, "migration_status"] = QUARANTINE_STATUS
        updated.at[index, "quarantine_reason"] = QUARANTINE_REASON
        changed += 1

    return updated, changed


def write_outputs(
    *,
    actions: pd.DataFrame,
    missing_open_lots: pd.DataFrame,
    touched_sells: pd.DataFrame,
    orphans: pd.DataFrame,
    changed_events: int,
    apply: bool,
):
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    actions.to_csv(ACTIONS_FILE, index=False)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "applied": apply,
        "changed_events": changed_events,
        "missing_open_lots": missing_open_lots.to_dict(orient="records"),
        "touched_sell_events": touched_sells.to_dict(orient="records"),
        "orphan_sell_events_before_action": orphans.to_dict(orient="records"),
        "action_event_ids": (
            actions["event_id"].astype(str).tolist() if not actions.empty else []
        ),
        "corrected_event_ids": (
            actions.loc[
                actions["new_migration_status"].astype(str).eq(CORRECTION_STATUS),
                "event_id",
            ].astype(str).tolist()
            if not actions.empty
            else []
        ),
        "ledger_file": str(LEDGER_FILE.relative_to(ROOT)),
        "portfolio_file": str(PORTFOLIO_FILE.relative_to(ROOT)),
        "holdings_file": str(HOLDINGS_FILE.relative_to(ROOT)),
        "journal_file": str(JOURNAL_FILE.relative_to(ROOT)),
        "actions_file": str(ACTIONS_FILE.relative_to(ROOT)),
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Quarantine clean ledger open lots that are absent from current "
            "portfolio and holdings."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write ledger quarantine changes. Without this, only reports actions.",
    )
    args = parser.parse_args()

    ledger = load_trade_ledger(LEDGER_FILE)
    portfolio = read_csv(PORTFOLIO_FILE)
    holdings = read_csv(HOLDINGS_FILE)
    journal = read_csv(JOURNAL_FILE)

    actions, missing_open_lots, touched_sells, orphans = build_actions(
        ledger,
        portfolio,
        holdings,
        journal,
    )

    changed_events = 0
    if args.apply and not actions.empty:
        updated, changed_events = apply_actions(ledger, actions)
        updated = updated.reindex(columns=LEDGER_COLUMNS)
        updated.to_csv(LEDGER_FILE, index=False)

    report = write_outputs(
        actions=actions,
        missing_open_lots=missing_open_lots,
        touched_sells=touched_sells,
        orphans=orphans,
        changed_events=changed_events,
        apply=args.apply,
    )

    print("Ledger open-lot reconciliation")
    print(f"applied={report['applied']}")
    print(f"missing_open_lots={len(missing_open_lots)}")
    print(f"action_events={len(actions)}")
    print(f"correction_events={len(report['corrected_event_ids'])}")
    print(f"changed_events={changed_events}")
    print(f"wrote={REPORT_FILE.relative_to(ROOT)}")
    print(f"wrote={ACTIONS_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
