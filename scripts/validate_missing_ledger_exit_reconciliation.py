from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.accounting import authoritative_ledger_accounting
from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event
from scripts.reconcile_missing_ledger_exit import plan_reconciliation, run


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def write_fixture(base, include_sell=True):
    buy = build_trade_event(
        timestamp="2026-07-06 16:57:38", trade_date="2026-07-06", trade_time="16:57:38",
        ticker="BTC-GBP", action="BUY", shares=0.0210814625594048,
        price=47435.0390625, value=999.9999999999998, currency="GBP",
        reason="SIGNAL ENTRY", legacy_trade_id="BTC-GBP_2026-07-06_BUY",
        run_id="20260706_165738", position_id="BTC-GBP_2026-07-06",
    )
    pd.DataFrame([buy], columns=LEDGER_COLUMNS).to_csv(base / "trade_ledger_v1.csv", index=False)
    pd.DataFrame(columns=["ticker", "shares"]).to_csv(base / "paper_portfolio_v3.csv", index=False)
    sell = {"date": "2026-07-13", "time": "17:56:38", "action": "SELL", "ticker": "BTC-GBP", "price": 47951.6484375, "shares": 0.0210814625594048, "value": 1010.890881196898, "pnl": 10.890881196900011, "pnl_percent": 0.0108908811968999, "reason": "CONFIRMED SIGNAL EXIT"}
    buy_audit = {"date": "2026-07-06", "time": "16:57:38", "action": "BUY", "ticker": "BTC-GBP", "price": 47435.0390625, "shares": 0.0210814625594048, "value": 999.9999999999998, "pnl": 0, "pnl_percent": 0, "reason": "SIGNAL ENTRY"}
    pd.DataFrame([buy_audit, sell] if include_sell else [buy_audit]).to_csv(base / "trade_journal_v3.csv", index=False)
    tx_fields = ["date", "action", "ticker", "price", "shares", "value", "reason"]
    pd.DataFrame([{key: row[key] for key in tx_fields} for row in ([buy_audit, sell] if include_sell else [buy_audit])]).to_csv(base / "trade_transactions_v1.csv", index=False)
    buy_snapshot = {"trade_id": "BTC-GBP_2026-07-06_BUY", "event": "BUY", "ticker": "BTC-GBP", "timestamp": "2026-07-06 16:57:38", "price": buy_audit["price"], "shares": buy_audit["shares"], "position_value": buy_audit["value"], "stop_loss": 44083.55524553572, "take_profit": 52462.26478794643}
    sell_snapshot = {"trade_id": "BTC-GBP_2026-07-06_SELL", "event": "SELL", "ticker": "BTC-GBP", "timestamp": "2026-07-13 17:56:38", "price": sell["price"], "shares": sell["shares"], "position_value": sell["value"]}
    pd.DataFrame([buy_snapshot, sell_snapshot] if include_sell else [buy_snapshot]).to_csv(base / "trade_snapshots.csv", index=False)
    return sell


def main():
    issues = []
    base = ROOT / ".reconciliation_test_workspace"
    base.mkdir(exist_ok=True)
    try:
        sell = write_fixture(base)
        before = {path.name: path.read_bytes() for path in base.glob("*.csv")}
        check(run(base, apply=False) == 1, "manual reconciliation defaults to dry-run when repair is needed", issues)
        after = {path.name: path.read_bytes() for path in base.glob("*.csv")}
        check(before == after and not (base / "data").exists(), "dry-run validation cannot change accounting files or create a report", issues)
        _, repairs, report = plan_reconciliation(base)
        check(report["status"] == "repairable" and len(repairs) == 1, "BTC mismatch identifies exactly one missing SELL", issues)
        check(report["repairs"][0]["journal_row"] == 3 and report["repairs"][0]["transaction_row"] == 3 and report["repairs"][0]["snapshot_row"] == 3, "report records every causal audit row", issues)
        check(run(base, apply=True) == 0, "deterministic repair applies", issues)
        accounting = authoritative_ledger_accounting(base_dir=base)
        check(accounting is not None and accounting["open_lots"].empty, "repaired ledger closes the economic BTC position", issues)
        check(run(base, apply=True) == 0, "second repair run is idempotent", issues)
        report_data = json.loads((base / "data" / "missing_ledger_exit_reconciliation.json").read_text())
        check(report_data["status"] == "consistent", "repeat run reports consistent state", issues)

        write_fixture(base)
        journal = pd.read_csv(base / "trade_journal_v3.csv")
        journal = pd.concat([journal, journal], ignore_index=True)
        journal.to_csv(base / "trade_journal_v3.csv", index=False)
        _, repairs, report = plan_reconciliation(base)
        check(not repairs and report["status"] == "refused", "ambiguous duplicate SELL evidence is refused", issues)

        write_fixture(base, include_sell=False)
        _, repairs, report = plan_reconciliation(base)
        check(report["status"] == "repairable" and repairs[0]["kind"] == "restore_portfolio_open_lot", "open BUY without exit restores the portfolio snapshot", issues)
        check(run(base, apply=True) == 0, "open-position repair applies", issues)
        portfolio = pd.read_csv(base / "paper_portfolio_v3.csv")
        check(abs(float(portfolio.iloc[0]["shares"]) - 0.0210814625594048) <= 1e-12, "restored portfolio shares equal ledger open lots", issues)
    finally:
        for path in list(base.glob("*")):
            if path.is_file():
                path.unlink(missing_ok=True)
        data_dir = base / "data"
        if data_dir.exists():
            for path in list(data_dir.glob("*")):
                path.unlink(missing_ok=True)
            data_dir.rmdir()
        base.rmdir()

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
