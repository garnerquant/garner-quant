from __future__ import annotations

import json
import sys
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.trade_audit import clean_ledger_events, ledger_open_positions
from execution.trade_ledger import load_trade_ledger


LEDGER_FILE = ROOT / "trade_ledger_v1.csv"
PORTFOLIO_FILE = ROOT / "paper_portfolio_v3.csv"
HOLDINGS_FILE = ROOT / "holdings_report.csv"
REPORT_FILE = ROOT / "data" / "ledger_open_lot_reconciliation_report.json"
SHARE_TOLERANCE = 1e-6


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def check(condition, severity, message, issues):
    if condition:
        print(f"OK: {message}")
        return
    print(f"{severity}: {message}")
    issues.append((severity, message))


def position_map(frame):
    if frame.empty or "ticker" not in frame.columns or "shares" not in frame.columns:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["shares"] = pd.to_numeric(data["shares"], errors="coerce").fillna(0.0)
    grouped = data[data["ticker"].ne("")].groupby("ticker")["shares"].sum()
    return grouped.to_dict()


def open_position_map(frame):
    if frame.empty:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["open_shares"] = pd.to_numeric(
        data["open_shares"],
        errors="coerce",
    ).fillna(0.0)
    return data.groupby("ticker")["open_shares"].sum().to_dict()


def unmatched_sells(ledger):
    events = clean_ledger_events(ledger)
    lots = defaultdict(deque)
    rows = []

    for _, row in events.iterrows():
        ticker = str(row["ticker"]).upper()
        if str(row["action"]).upper() == "BUY":
            lot = row.copy()
            lot["remaining_shares"] = float(row["shares"])
            lots[ticker].append(lot)
            continue

        remaining = float(row["shares"])
        while remaining > 1e-12 and lots[ticker]:
            lot = lots[ticker][0]
            matched = min(float(lot["remaining_shares"]), remaining)
            lot["remaining_shares"] = float(lot["remaining_shares"]) - matched
            remaining -= matched
            if float(lot["remaining_shares"]) <= 1e-12:
                lots[ticker].popleft()

        if remaining > 1e-12:
            rows.append(
                {
                    "ticker": ticker,
                    "event_id": row.get("event_id", ""),
                    "legacy_row_number": row.get("legacy_row_number", ""),
                    "unmatched_shares": remaining,
                }
            )

    return pd.DataFrame(rows)


def load_report():
    if not REPORT_FILE.exists():
        return {}
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    issues = []
    ledger = load_trade_ledger(LEDGER_FILE)
    portfolio = read_csv(PORTFOLIO_FILE)
    holdings = read_csv(HOLDINGS_FILE)
    clean_events = clean_ledger_events(ledger)
    ledger_open = ledger_open_positions(ledger)
    ledger_positions = open_position_map(ledger_open)
    portfolio_positions = position_map(portfolio)
    holdings_positions = position_map(holdings)
    report = load_report()

    print("Ledger open-lot validation")
    print(f"clean_ledger_events={len(clean_events)}")
    print(f"ledger_open_positions={len(ledger_positions)}")
    print(f"portfolio_positions={len(portfolio_positions)}")
    print(f"holdings_positions={len(holdings_positions)}")

    check(not ledger.empty, "CRITICAL", "trade ledger exists", issues)
    check(not portfolio.empty, "CRITICAL", "paper portfolio exists", issues)
    check(not holdings.empty, "CRITICAL", "holdings report exists", issues)

    ledger_tickers = set(ledger_positions)
    portfolio_tickers = set(portfolio_positions)
    holdings_tickers = set(holdings_positions)

    check(
        ledger_tickers == portfolio_tickers,
        "CRITICAL",
        "ledger open tickers match paper portfolio tickers",
        issues,
    )
    check(
        ledger_tickers == holdings_tickers,
        "CRITICAL",
        "ledger open tickers match holdings report tickers",
        issues,
    )

    for ticker in sorted(ledger_tickers | portfolio_tickers | holdings_tickers):
        ledger_shares = float(ledger_positions.get(ticker, 0.0))
        portfolio_shares = float(portfolio_positions.get(ticker, 0.0))
        holdings_shares = float(holdings_positions.get(ticker, 0.0))
        check(
            abs(ledger_shares - portfolio_shares) <= SHARE_TOLERANCE,
            "CRITICAL",
            f"{ticker} ledger shares match paper portfolio shares",
            issues,
        )
        check(
            abs(ledger_shares - holdings_shares) <= SHARE_TOLERANCE,
            "CRITICAL",
            f"{ticker} ledger shares match holdings report shares",
            issues,
        )

    orphan_sells = unmatched_sells(ledger)
    check(
        orphan_sells.empty,
        "HIGH",
        "clean ledger contains no unmatched SELL events",
        issues,
    )
    if not orphan_sells.empty:
        print(orphan_sells.to_string(index=False))

    action_ids = set(report.get("action_event_ids", []))
    if action_ids:
        clean_ids = set(clean_events["event_id"].astype(str))
        check(
            not bool(action_ids & clean_ids),
            "HIGH",
            "reconciled/quarantined event ids are excluded from clean ledger",
            issues,
        )

    critical_or_high = [
        issue for issue in issues if issue[0] in {"CRITICAL", "HIGH"}
    ]
    print(
        "summary="
        + f"{len(issues)} issue(s), {len(critical_or_high)} critical/high issue(s)"
    )
    return 1 if critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
