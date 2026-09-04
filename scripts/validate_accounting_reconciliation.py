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

from config import STARTING_CASH
from execution.accounting import (
    broker_values_from_ledger_and_holdings,
    ledger_accounting as canonical_ledger_accounting,
    numeric as canonical_numeric,
)
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import load_trade_ledger


LEDGER_FILE = ROOT / "trade_ledger_v1.csv"
BROKER_FILE = ROOT / "broker_account.csv"
PORTFOLIO_FILE = ROOT / "paper_portfolio_v3.csv"
HOLDINGS_FILE = ROOT / "holdings_report.csv"
TRACKER_FILE = ROOT / "paper_30_day_tracker.csv"
REPORT_FILE = ROOT / "data" / "accounting_reconciliation_report.json"
REQUIRED_RUNTIME_FILES = (LEDGER_FILE, BROKER_FILE, PORTFOLIO_FILE, HOLDINGS_FILE, TRACKER_FILE)

CASH_TOLERANCE = 0.01
SHARE_TOLERANCE = 1e-6
VALUE_TOLERANCE = 0.01


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric(value, default=0.0):
    return canonical_numeric(value, default=default)


def check(condition, severity, message, issues, details=None):
    if condition:
        print(f"OK: {message}")
        return
    print(f"{severity}: {message}")
    issues.append(
        {
            "severity": severity,
            "message": message,
            "details": details or {},
        }
    )


def ledger_accounting(events):
    return canonical_ledger_accounting(events)


def aggregate_open_lots(open_lots):
    if open_lots.empty:
        return pd.DataFrame(
            columns=["ticker", "shares", "entry_price", "position_value"]
        )
    grouped_rows = []
    for ticker, group in open_lots.groupby("ticker"):
        shares = float(group["shares"].sum())
        cost = float(group["cost_basis"].sum())
        grouped_rows.append(
            {
                "ticker": ticker,
                "shares": shares,
                "entry_price": cost / shares if shares else 0.0,
                "position_value": cost,
            }
        )
    return pd.DataFrame(grouped_rows)


def by_ticker(frame, columns):
    if frame.empty or "ticker" not in frame.columns:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    return {
        ticker: row
        for ticker, row in data.set_index("ticker")[columns].iterrows()
        if ticker
    }


def serialise_frame(frame):
    if frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate ledger, projection, holdings, and broker reconciliation."
    )
    parser.add_argument(
        "--report-file",
        help=(
            "Explicit destination for the generated JSON report. By default the "
            "validator is read-only."
        ),
    )
    args = parser.parse_args(argv)
    missing_runtime_files = [path.name for path in REQUIRED_RUNTIME_FILES if not path.is_file()]
    if missing_runtime_files:
        print(
            "Accounting reconciliation unavailable: missing server-owned runtime "
            f"files: {', '.join(missing_runtime_files)}"
        )
        print("reconciliation=skipped (runtime state is absent)")
        if args.report_file:
            report_file = Path(args.report_file).resolve()
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now().isoformat(timespec="seconds"),
                        "starting_cash": float(STARTING_CASH),
                        "expected_ledger_cash": None,
                        "actual_broker_cash": None,
                        "cash_difference": None,
                        "expected_ledger_realised_pnl": None,
                        "actual_broker_realised_pnl": None,
                        "realised_pnl_difference": None,
                        "expected_open_cost_basis": None,
                        "holdings_market_value": None,
                        "actual_broker_positions_value": None,
                        "expected_unrealised_pnl": None,
                        "actual_broker_unrealised_pnl": None,
                        "expected_portfolio_value": None,
                        "actual_broker_portfolio_value": None,
                        "portfolio_value_difference": None,
                        "currency_summary": [],
                        "expected_open_positions": [],
                        "holding_mismatches": [],
                        "issues": [{
                            "severity": "INFO",
                            "message": "reconciliation skipped: server-owned runtime state is unavailable",
                            "details": {"missing_runtime_files": missing_runtime_files},
                        }],
                        "likely_root_cause": "server-owned runtime artifacts are absent from this checkout",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"wrote={report_file}")
        return 0
    issues = []
    ledger = load_trade_ledger(LEDGER_FILE)
    events = clean_ledger_events(ledger)
    broker = read_csv(BROKER_FILE)
    portfolio = read_csv(PORTFOLIO_FILE)
    holdings = read_csv(HOLDINGS_FILE)
    accounting = ledger_accounting(events)
    expected_open = aggregate_open_lots(accounting["open_lots"])

    broker_row = broker.iloc[0] if not broker.empty else {}
    actual_cash = numeric(broker_row.get("cash"))
    actual_positions_value = numeric(broker_row.get("positions_value"))
    actual_realised_pnl = numeric(broker_row.get("realised_pnl"))
    actual_portfolio_value = numeric(broker_row.get("portfolio_value"))
    actual_unrealised_pnl = numeric(broker_row.get("unrealised_pnl"))
    holdings_market_value = (
        float(pd.to_numeric(holdings.get("market_value", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        if not holdings.empty
        else 0.0
    )
    expected_portfolio_value = accounting["expected_cash"] + holdings_market_value
    expected_unrealised_pnl = holdings_market_value - accounting["open_cost_basis"]

    print("Accounting reconciliation validation")
    print(f"starting_cash={float(STARTING_CASH):.6f}")
    print(f"clean_ledger_events={len(events)}")
    print(f"expected_ledger_cash={accounting['expected_cash']:.6f}")
    print(f"actual_broker_cash={actual_cash:.6f}")
    print(f"cash_difference={actual_cash - accounting['expected_cash']:.6f}")
    print(f"expected_ledger_realised_pnl={accounting['realised_pnl']:.6f}")
    print(f"actual_broker_realised_pnl={actual_realised_pnl:.6f}")

    check(not ledger.empty, "CRITICAL", "trade ledger exists", issues)
    check(not broker.empty, "CRITICAL", "broker account exists", issues)
    check(not portfolio.empty, "CRITICAL", "paper portfolio exists", issues)
    check(not holdings.empty, "CRITICAL", "holdings report exists", issues)
    check(
        accounting["orphan_sells"].empty,
        "CRITICAL",
        "clean ledger has no orphan SELL events",
        issues,
        {"orphan_sells": serialise_frame(accounting["orphan_sells"])},
    )
    check(
        abs(actual_cash - accounting["expected_cash"]) <= CASH_TOLERANCE,
        "CRITICAL",
        "broker cash matches clean ledger cashflow",
        issues,
        {
            "expected_cash": accounting["expected_cash"],
            "actual_cash": actual_cash,
            "difference": actual_cash - accounting["expected_cash"],
        },
    )
    check(
        abs(actual_realised_pnl - accounting["realised_pnl"]) <= VALUE_TOLERANCE,
        "CRITICAL",
        "broker realised PnL matches clean ledger closed trades",
        issues,
        {
            "expected_realised_pnl": accounting["realised_pnl"],
            "actual_realised_pnl": actual_realised_pnl,
            "difference": actual_realised_pnl - accounting["realised_pnl"],
        },
    )
    check(
        abs(actual_portfolio_value - (actual_cash + holdings_market_value))
        <= VALUE_TOLERANCE,
        "HIGH",
        "broker portfolio value equals broker cash plus holdings market value",
        issues,
        {
            "actual_portfolio_value": actual_portfolio_value,
            "actual_cash": actual_cash,
            "holdings_market_value": holdings_market_value,
        },
    )
    check(
        abs(actual_positions_value - holdings_market_value) <= VALUE_TOLERANCE,
        "HIGH",
        "broker positions value matches holdings market value",
        issues,
        {
            "actual_positions_value": actual_positions_value,
            "holdings_market_value": holdings_market_value,
            "difference": actual_positions_value - holdings_market_value,
        },
    )
    check(
        abs(actual_portfolio_value - expected_portfolio_value) <= VALUE_TOLERANCE,
        "CRITICAL",
        "broker portfolio value matches ledger cash plus holdings market value",
        issues,
        {
            "expected_portfolio_value": expected_portfolio_value,
            "actual_portfolio_value": actual_portfolio_value,
            "difference": actual_portfolio_value - expected_portfolio_value,
        },
    )
    check(
        abs(actual_unrealised_pnl - expected_unrealised_pnl) <= VALUE_TOLERANCE,
        "HIGH",
        "broker unrealised PnL matches holdings market value minus ledger open cost",
        issues,
        {
            "expected_unrealised_pnl": expected_unrealised_pnl,
            "actual_unrealised_pnl": actual_unrealised_pnl,
            "difference": actual_unrealised_pnl - expected_unrealised_pnl,
        },
    )

    expected_positions = by_ticker(
        expected_open,
        ["shares", "entry_price", "position_value"],
    )
    portfolio_positions = by_ticker(
        portfolio,
        ["shares", "entry_price", "position_value"],
    )
    holdings_positions = by_ticker(
        holdings,
        ["shares", "entry_price", "market_value", "current_price", "unrealised_pnl"],
    )
    all_tickers = set(expected_positions) | set(portfolio_positions) | set(holdings_positions)
    check(
        set(expected_positions) == set(portfolio_positions),
        "CRITICAL",
        "ledger open tickers match paper portfolio tickers",
        issues,
    )
    check(
        set(expected_positions) == set(holdings_positions),
        "CRITICAL",
        "ledger open tickers match holdings report tickers",
        issues,
    )

    holding_mismatches = []
    for ticker in sorted(all_tickers):
        expected = expected_positions.get(ticker, {})
        portfolio_row = portfolio_positions.get(ticker, {})
        holdings_row = holdings_positions.get(ticker, {})
        expected_shares = numeric(expected.get("shares"))
        expected_entry = numeric(expected.get("entry_price"))
        expected_cost = numeric(expected.get("position_value"))
        portfolio_shares = numeric(portfolio_row.get("shares"))
        portfolio_entry = numeric(portfolio_row.get("entry_price"))
        portfolio_cost = numeric(portfolio_row.get("position_value"))
        holdings_shares = numeric(holdings_row.get("shares"))
        holdings_entry = numeric(holdings_row.get("entry_price"))
        holdings_market = numeric(holdings_row.get("market_value"))
        holdings_price = numeric(holdings_row.get("current_price"))
        holdings_unrealised = numeric(holdings_row.get("unrealised_pnl"))
        expected_market = holdings_shares * holdings_price
        expected_holding_unrealised = holdings_market - expected_cost

        ticker_issues = []
        if abs(expected_shares - portfolio_shares) > SHARE_TOLERANCE:
            ticker_issues.append("portfolio shares")
        if abs(expected_shares - holdings_shares) > SHARE_TOLERANCE:
            ticker_issues.append("holdings shares")
        if abs(expected_entry - portfolio_entry) > VALUE_TOLERANCE:
            ticker_issues.append("portfolio entry price")
        if abs(expected_entry - holdings_entry) > VALUE_TOLERANCE:
            ticker_issues.append("holdings entry price")
        if abs(expected_cost - portfolio_cost) > VALUE_TOLERANCE:
            ticker_issues.append("portfolio cost basis")
        if abs(holdings_market - expected_market) > VALUE_TOLERANCE:
            ticker_issues.append("holdings market value")
        if abs(holdings_unrealised - expected_holding_unrealised) > VALUE_TOLERANCE:
            ticker_issues.append("holdings unrealised PnL")

        if ticker_issues:
            holding_mismatches.append(
                {
                    "ticker": ticker,
                    "mismatches": ticker_issues,
                    "expected": {
                        "shares": expected_shares,
                        "entry_price": expected_entry,
                        "position_value": expected_cost,
                        "market_value": expected_market,
                        "unrealised_pnl": expected_holding_unrealised,
                    },
                    "portfolio": {
                        "shares": portfolio_shares,
                        "entry_price": portfolio_entry,
                        "position_value": portfolio_cost,
                    },
                    "holdings": {
                        "shares": holdings_shares,
                        "entry_price": holdings_entry,
                        "market_value": holdings_market,
                        "unrealised_pnl": holdings_unrealised,
                    },
                }
            )

    check(
        not holding_mismatches,
        "CRITICAL",
        "ledger open holdings reconcile to paper portfolio and holdings report",
        issues,
        {"holding_mismatches": holding_mismatches},
    )

    currency_summary = (
        events.groupby(["currency", "action"])[["value", "fees"]].sum().reset_index()
        if not events.empty
        else pd.DataFrame()
    )
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "starting_cash": float(STARTING_CASH),
        "expected_ledger_cash": accounting["expected_cash"],
        "actual_broker_cash": actual_cash,
        "cash_difference": actual_cash - accounting["expected_cash"],
        "expected_ledger_realised_pnl": accounting["realised_pnl"],
        "actual_broker_realised_pnl": actual_realised_pnl,
        "realised_pnl_difference": actual_realised_pnl - accounting["realised_pnl"],
        "expected_open_cost_basis": accounting["open_cost_basis"],
        "holdings_market_value": holdings_market_value,
        "actual_broker_positions_value": actual_positions_value,
        "expected_unrealised_pnl": expected_unrealised_pnl,
        "actual_broker_unrealised_pnl": actual_unrealised_pnl,
        "expected_portfolio_value": expected_portfolio_value,
        "actual_broker_portfolio_value": actual_portfolio_value,
        "portfolio_value_difference": actual_portfolio_value - expected_portfolio_value,
        "currency_summary": serialise_frame(currency_summary),
        "expected_open_positions": serialise_frame(expected_open),
        "holding_mismatches": holding_mismatches,
        "issues": issues,
        "likely_root_cause": (
            "broker_account.csv cash and realised_pnl are derived from legacy "
            "trade_journal_v3.csv realised PnL, while authoritative cash "
            "must be derived from clean trade_ledger_v1.csv cashflows."
        ),
    }
    if args.report_file:
        report_file = Path(args.report_file).resolve()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote={report_file}")
    else:
        print("report_write=disabled (use --report-file to generate a report)")

    critical_or_high = [
        issue for issue in issues if issue["severity"] in {"CRITICAL", "HIGH"}
    ]
    print(
        "summary="
        + f"{len(issues)} issue(s), {len(critical_or_high)} critical/high issue(s)"
    )
    return 1 if critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
