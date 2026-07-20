from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event
from scripts.repair_paper_tracker_projection import (
    TrackerRepairError,
    build_repair,
    file_hash,
    run,
)


EXPECTED_VALUE = 10029.824975615284
EXPECTED_CASH = 3860.342651148374
EXPECTED_REALISED = -139.65734885161947
EXPECTED_UNREALISED = 169.48232446691054


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def write_fixture(base, duplicate_current=False, healthy=True):
    base.mkdir(parents=True, exist_ok=True)
    ticker, shares, entry_price = "AAPL", 1.0, 6000.0
    closed_buy = build_trade_event(
        timestamp="2026-06-30 10:00:00", trade_date="2026-06-30", trade_time="10:00:00",
        ticker="CLOSED", action="BUY", shares=1, price=1000.0,
        value=1000.0, currency="GBP", reason="fixture",
        legacy_trade_id="fixture-closed-buy", run_id="tracker-repair-fixture",
        position_id="CLOSED-position",
    )
    closed_sell_value = 1000.0 + EXPECTED_REALISED
    closed_sell = build_trade_event(
        timestamp="2026-06-30 11:00:00", trade_date="2026-06-30", trade_time="11:00:00",
        ticker="CLOSED", action="SELL", shares=1, price=closed_sell_value,
        value=closed_sell_value, currency="GBP", reason="fixture",
        legacy_trade_id="fixture-closed-sell", run_id="tracker-repair-fixture",
        position_id="CLOSED-position", pnl=EXPECTED_REALISED,
    )
    open_buy = build_trade_event(
        timestamp="2026-07-01 12:00:00", trade_date="2026-07-01", trade_time="12:00:00",
        ticker=ticker, action="BUY", shares=shares, price=entry_price,
        value=entry_price, currency="GBP", reason="fixture",
        legacy_trade_id="fixture-aapl", run_id="tracker-repair-fixture",
        position_id="AAPL-open",
    )
    pd.DataFrame([closed_buy, closed_sell, open_buy], columns=LEDGER_COLUMNS).to_csv(base / "trade_ledger_v1.csv", index=False)
    portfolio_shares = shares + 1 if not healthy else shares
    pd.DataFrame([{
        "ticker": ticker, "entry_date": "2026-07-01", "entry_price": entry_price,
        "shares": portfolio_shares, "position_value": entry_price,
        "stop_loss": 9000, "take_profit": 11000,
        "signal_exit_count": 0, "last_signal_exit_check": "",
    }]).to_csv(base / "paper_portfolio_v3.csv", index=False)
    market_value = EXPECTED_VALUE - EXPECTED_CASH
    pd.DataFrame([{
        "date": "2026-07-16", "ticker": ticker, "shares": shares,
        "entry_price": entry_price, "current_price": market_value,
        "market_value": market_value, "unrealised_pnl": EXPECTED_UNREALISED,
        "unrealised_pnl_percent": EXPECTED_UNREALISED / entry_price,
    }]).to_csv(base / "holdings_report.csv", index=False)
    pd.DataFrame([{
        "cash": EXPECTED_CASH, "buying_power": EXPECTED_CASH,
        "positions_value": market_value, "portfolio_value": EXPECTED_VALUE,
        "realised_pnl": EXPECTED_REALISED, "unrealised_pnl": EXPECTED_UNREALISED,
    }]).to_csv(base / "broker_account.csv", index=False)
    rows = [
        ["2026-07-14 09:00:00", 9980.0, 4000.0, -100.0, 80.0, 0.1, 0.0],
        ["2026-07-15 09:00:00", 10010.0, 3900.0, -120.0, 130.0, 0.2, 0.0],
        ["2026-07-16 13:25:19", 8886.02, 3000.0, -139.0, -974.0, 0.3, 0.0],
    ]
    if duplicate_current:
        rows.insert(-1, ["2026-07-16 12:00:00", 9990.0, 3900.0, -120.0, 110.0, 0.3, 0.0])
    columns = ["date", "portfolio_value", "cash", "realised_pnl", "unrealised_pnl", "benchmark_return", "alpha"]
    pd.DataFrame(rows, columns=columns).to_csv(base / "paper_30_day_tracker.csv", index=False)
    for name in ["trade_journal_v3.csv", "trade_transactions_v1.csv", "trade_snapshots.csv"]:
        (base / name).write_bytes(f"protected {name}\n".encode())


def main():
    issues = []
    base = ROOT / ".paper_tracker_repair_fixture"
    if base.exists():
        shutil.rmtree(base)
    try:
        write_fixture(base)
        original = pd.read_csv(base / "paper_30_day_tracker.csv")
        repaired, details = build_repair(base)
        final = repaired.iloc[-1]
        check(abs(float(final["portfolio_value"]) - EXPECTED_VALUE) <= 1e-9, "exact false 8886.02 balance is repaired", issues)
        check(abs(float(final["realised_pnl"]) - EXPECTED_REALISED) <= 1e-9 and abs(float(final["unrealised_pnl"]) - EXPECTED_UNREALISED) <= 1e-9, "current realised and unrealised PnL are repaired", issues)
        expected_return = EXPECTED_VALUE / 10000.0 - 1
        check(abs(details["total_return"] - expected_return) <= 1e-12, "return is calculated from 10000 starting balance", issues)
        check(abs(details["equity_curve_final_return"] * 100 - 0.29824975615284) <= 1e-9, "equity curve final point is approximately positive 0.30 percent", issues)
        check(repaired.iloc[:-1].equals(original.iloc[:-1]), "all prior valid rows are preserved", issues)
        check(float(repaired.iloc[-1]["benchmark_return"]) == 0.3 and float(repaired.iloc[-1]["alpha"]) == 0.0, "benchmark and alpha fields are preserved", issues)

        tracker_before = (base / "paper_30_day_tracker.csv").read_bytes()
        check(run(base, apply=False) == 0, "dry-run succeeds", issues)
        check((base / "paper_30_day_tracker.csv").read_bytes() == tracker_before and not (base / "data").exists(), "dry-run is immutable and creates no report", issues)

        protected = ["trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv", "broker_account.csv", "trade_journal_v3.csv", "trade_transactions_v1.csv", "trade_snapshots.csv"]
        source_before = {name: (base / name).read_bytes() for name in protected}
        before_hash = file_hash(base / "paper_30_day_tracker.csv")
        check(run(base, apply=True) == 0, "fixture apply succeeds atomically", issues)
        report = json.loads((base / "data" / "paper_tracker_projection_repair_report.json").read_text())
        check(report["before_hash"] == before_hash and report["after_hash"] == file_hash(base / "paper_30_day_tracker.csv"), "audit report contains exact before and after hashes", issues)
        check(source_before == {name: (base / name).read_bytes() for name in protected}, "all protected accounting files remain byte-identical", issues)

        first_hash = file_hash(base / "paper_30_day_tracker.csv")
        check(run(base, apply=True) == 0 and file_hash(base / "paper_30_day_tracker.csv") == first_hash, "repeat apply is idempotent", issues)

        write_fixture(base, duplicate_current=True)
        intraday_before = pd.read_csv(base / "paper_30_day_tracker.csv")
        intraday_repaired, intraday_details = build_repair(base)
        target_index = intraday_details["target_row_index"]
        check(
            intraday_details["target_timestamp"] == "2026-07-16 13:25:19"
            and intraday_repaired.drop(index=target_index).equals(intraday_before.drop(index=target_index)),
            "multiple intraday rows repair only the unique latest timestamp",
            issues,
        )

        duplicate_timestamp = intraday_before.copy()
        duplicate_timestamp.loc[len(duplicate_timestamp)] = duplicate_timestamp.iloc[-1]
        duplicate_timestamp.to_csv(base / "paper_30_day_tracker.csv", index=False)
        duplicate_before = (base / "paper_30_day_tracker.csv").read_bytes()
        try:
            run(base, apply=True)
            duplicate_refused = False
        except TrackerRepairError as exc:
            duplicate_refused = "duplicate timestamps" in str(exc)
        check(duplicate_refused and (base / "paper_30_day_tracker.csv").read_bytes() == duplicate_before, "exact duplicate tracker timestamps are refused before mutation", issues)

        write_fixture(base, healthy=False)
        unhealthy_before = (base / "paper_30_day_tracker.csv").read_bytes()
        try:
            run(base, apply=True)
            unhealthy_refused = False
        except TrackerRepairError:
            unhealthy_refused = True
        check(unhealthy_refused and (base / "paper_30_day_tracker.csv").read_bytes() == unhealthy_before, "unhealthy accounting prerequisite is refused before mutation", issues)
    finally:
        if base.exists():
            shutil.rmtree(base)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
