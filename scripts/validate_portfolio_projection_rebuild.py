from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.portfolio_manager import PORTFOLIO_COLUMNS
from execution.accounting import ledger_accounting
from execution.trade_audit import clean_ledger_events
from execution.trade_ledger import load_trade_ledger
from execution.trade_ledger import LEDGER_COLUMNS, build_trade_event
from scripts.rebuild_portfolio_projection import (
    ProjectionRebuildError,
    build_projection,
    file_hash,
    position_map,
    run,
)


POSITIONS = [
    ("BTC-GBP", "2026-07-16 13:25:06", 0.02107703656865844, 47445.0, 1000.0, 44981.279575892855, 51140.58063616071),
    ("ETH-GBP", "2026-07-16 13:25:06", 0.35959323824245987, 1390.4599609375, 500.0, 1289.384068080357, 1542.0738002232142),
    ("IUSA.L", "2026-07-06 14:29:22", 0.3573342862247632, 5597.0, 2000.0, 5497.253766741072, 5746.619349888393),
    ("MSFT", "2026-07-16 13:25:06", 2.5276141537753305, 395.6300048828125, 1000.0, 375.3342895507813, 426.0735778808594),
    ("VWRL.L", "2026-07-14 00:04:28", 18.22688781897888, 137.16000366210938, 2500.0, 134.74999782017298, 140.77501242501395),
]


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def event_for(item, suffix=""):
    ticker, timestamp, shares, price, value, _, _ = item
    stamp = pd.Timestamp(timestamp)
    return build_trade_event(
        timestamp=timestamp, trade_date=stamp.strftime("%Y-%m-%d"), trade_time=stamp.strftime("%H:%M:%S"),
        ticker=ticker, action="BUY", shares=shares, price=price, value=value,
        currency="GBP", reason="SIGNAL ENTRY", legacy_trade_id=f"fixture-{ticker}{suffix}",
        run_id="projection-rebuild-fixture", position_id=f"{ticker}-open{suffix}",
    )


def write_fixture(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    events = [event_for(item) for item in POSITIONS]
    pd.DataFrame(events, columns=LEDGER_COLUMNS).to_csv(base / "trade_ledger_v1.csv", index=False)
    snapshots = []
    for ticker, timestamp, shares, price, value, stop, target in POSITIONS:
        snapshots.append({
            "trade_id": f"fixture-{ticker}", "event": "BUY", "ticker": ticker,
            "timestamp": timestamp, "price": price, "shares": shares,
            "position_value": value, "cash": 0, "portfolio_value": 0,
            "portfolio_weight": 0, "signal": 1, "reason": "SIGNAL ENTRY",
            "stop_loss": stop, "take_profit": target,
        })
    pd.DataFrame(snapshots).to_csv(base / "trade_snapshots.csv", index=False)
    corrupted = pd.DataFrame([
        ["IUSA.L", "wrong", 1.0, 99.0, 99.0, 1.0, 2.0, 7, "stale"],
        ["MSFT", "wrong", 2.0, 88.0, 176.0, 1.0, 2.0, 8, "stale"],
        ["ETH-GBP", "wrong", 3.0, 77.0, 231.0, 1.0, 2.0, 9, "stale"],
    ], columns=PORTFOLIO_COLUMNS)
    corrupted.to_csv(base / "paper_portfolio_v3.csv", index=False)
    (base / "trade_journal_v3.csv").write_bytes(b"source journal unchanged\n")
    (base / "trade_transactions_v1.csv").write_bytes(b"source transactions unchanged\n")


def expect_refusal(base, mutate, phrase):
    write_fixture(base)
    mutate(base)
    try:
        build_projection(base)
    except ProjectionRebuildError as exc:
        return phrase.lower() in str(exc).lower()
    return False


def main():
    issues = []
    base = ROOT / ".portfolio_projection_rebuild_fixture"
    if base.exists():
        shutil.rmtree(base)
    try:
        write_fixture(base)
        projection, details = build_projection(base)
        expected_tickers = ["BTC-GBP", "ETH-GBP", "IUSA.L", "MSFT", "VWRL.L"]
        check(list(projection["ticker"]) == expected_tickers, "exact five-position reconstruction uses deterministic ticker order", issues)
        check(abs(details["open_cost_basis"] - 7000.0) <= 1e-9, "open cost basis is exactly 7000", issues)
        check(list(projection.columns) == PORTFOLIO_COLUMNS, "canonical portfolio columns are preserved", issues)
        check(projection["signal_exit_count"].eq(0).all() and projection["last_signal_exit_check"].eq("").all(), "operational fields follow explicit reset policy", issues)
        check(float(projection.loc[projection.ticker.eq("IUSA.L"), "entry_price"].iloc[0]) == 5597.0, "incorrect existing rows are replaced rather than preserved", issues)

        source_names = ["trade_ledger_v1.csv", "trade_snapshots.csv", "trade_journal_v3.csv", "trade_transactions_v1.csv"]
        before_sources = {name: (base / name).read_bytes() for name in source_names}
        before_portfolio = (base / "paper_portfolio_v3.csv").read_bytes()
        before_portfolio_hash = file_hash(base / "paper_portfolio_v3.csv")
        check(run(base, apply=False) == 0, "dry-run succeeds", issues)
        check((base / "paper_portfolio_v3.csv").read_bytes() == before_portfolio and not (base / "data").exists(), "dry-run changes no files and creates no report", issues)

        check(run(base, apply=True) == 0, "apply writes fixture projection", issues)
        rebuilt = pd.read_csv(base / "paper_portfolio_v3.csv")
        report_path = base / "data" / "portfolio_projection_rebuild_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        check(list(rebuilt["ticker"]) == expected_tickers, "corrupted three-row portfolio is completely rebuilt", issues)
        check(
            report["before_hash"] == before_portfolio_hash
            and report["after_hash"] == file_hash(base / "paper_portfolio_v3.csv")
            and report["before_hash"] != report["after_hash"],
            "apply report contains exact before and after hashes",
            issues,
        )
        check(report["valuation_outputs_refreshed"] is False, "report states valuation was not refreshed", issues)
        check(before_sources == {name: (base / name).read_bytes() for name in source_names}, "ledger and source projections remain byte-identical", issues)
        authoritative = ledger_accounting(clean_ledger_events(load_trade_ledger(base / "trade_ledger_v1.csv")))["open_lots"]
        check(position_map(rebuilt) == position_map(authoritative), "final shares exactly equal parsed authoritative ledger shares", issues)

        first_hash = file_hash(base / "paper_portfolio_v3.csv")
        check(run(base, apply=True) == 0 and file_hash(base / "paper_portfolio_v3.csv") == first_hash, "repeat apply is idempotent", issues)

        check(expect_refusal(base, lambda b: pd.read_csv(b / "trade_snapshots.csv").iloc[1:].to_csv(b / "trade_snapshots.csv", index=False), "exactly one"), "missing snapshot match is refused", issues)

        def duplicate_snapshot(b):
            data = pd.read_csv(b / "trade_snapshots.csv")
            pd.concat([data, data.iloc[[0]]], ignore_index=True).to_csv(b / "trade_snapshots.csv", index=False)
        check(expect_refusal(base, duplicate_snapshot, "found 2"), "duplicate snapshot match is refused", issues)

        def orphan_sell(b):
            ledger = pd.read_csv(b / "trade_ledger_v1.csv")
            sell = build_trade_event(timestamp="2026-07-01 00:00:00", trade_date="2026-07-01", trade_time="00:00:00", ticker="ORPHAN", action="SELL", shares=1, price=1, value=1, currency="GBP", reason="test", legacy_trade_id="orphan", run_id="fixture")
            pd.concat([pd.DataFrame([sell]), ledger], ignore_index=True)[LEDGER_COLUMNS].to_csv(b / "trade_ledger_v1.csv", index=False)
        check(expect_refusal(base, orphan_sell, "orphan SELL"), "orphan SELL is refused", issues)

        def duplicate_lot(b):
            ledger = pd.read_csv(b / "trade_ledger_v1.csv")
            extra = event_for(POSITIONS[0], suffix="-second")
            pd.concat([ledger, pd.DataFrame([extra])], ignore_index=True)[LEDGER_COLUMNS].to_csv(b / "trade_ledger_v1.csv", index=False)
        check(expect_refusal(base, duplicate_lot, "multiple unresolved"), "duplicate ticker/open lot is refused", issues)

        def invalid_risk(b):
            data = pd.read_csv(b / "trade_snapshots.csv")
            data.loc[0, "stop_loss"] = float("nan")
            data.to_csv(b / "trade_snapshots.csv", index=False)
        check(expect_refusal(base, invalid_risk, "stop loss"), "invalid stop or target is refused", issues)

        def invalid_target(b):
            data = pd.read_csv(b / "trade_snapshots.csv")
            data.loc[0, "take_profit"] = -1
            data.to_csv(b / "trade_snapshots.csv", index=False)
        check(expect_refusal(base, invalid_target, "take profit"), "invalid target is independently refused", issues)

        write_fixture(base)
        duplicate_ids = pd.read_csv(base / "trade_ledger_v1.csv")
        duplicate_ids.loc[1, "event_id"] = duplicate_ids.loc[0, "event_id"]
        duplicate_ids.to_csv(base / "trade_ledger_v1.csv", index=False)
        try:
            build_projection(base)
            duplicate_id_refused = False
        except ProjectionRebuildError:
            duplicate_id_refused = True
        check(duplicate_id_refused, "duplicate ledger event IDs are refused", issues)
    finally:
        if base.exists():
            shutil.rmtree(base)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
