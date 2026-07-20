from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.scheduler_reader import load_scheduler_state
from execution.portfolio_manager import signal_exit_status
from runtime.bar_scheduler import (
    BarIdentity, ExchangeCalendarAdapter, ProcessedBarStore, SchedulerError,
    evaluate_completed_bar, market_policies,
)
from runtime.live_runtime import paper_execution_blocked_reason
from runtime.strategy_orchestrator import completed_bar_timestamps, schedule_completed_bars


UTC = timezone.utc
STRATEGY = "strategy-v1"
CONFIG = "config-v1"


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def decision(symbol, close, now):
    return evaluate_completed_bar(
        symbol, close, now=now, strategy_version=STRATEGY,
        configuration_version=CONFIG, data_source="fixture",
    )


def main():
    issues = []
    policies = market_policies()
    check(len(policies) == 9 and all(policies), "every supported instrument has an independent market policy", issues)
    sunday = datetime(2026, 7, 19, 1, tzinfo=UTC)
    crypto = decision("BTC-GBP", datetime(2026, 7, 19, 0, tzinfo=UTC), sunday)
    lse_friday = decision("IUSA.L", datetime(2026, 7, 17, 15, 30, tzinfo=UTC), sunday)
    us_friday = decision("AAPL", datetime(2026, 7, 17, 20, 0, tzinfo=UTC), sunday)
    check(crypto.eligible, "Sunday crypto completed daily bar is eligible", issues)
    check(not lse_friday.eligible, "Sunday crypto availability does not evaluate LSE instruments", issues)
    check(not us_friday.eligible, "Sunday crypto availability does not evaluate US equities", issues)

    before_lse = decision("IUSA.L", datetime(2026, 7, 20, 15, 30, tzinfo=UTC),
                          datetime(2026, 7, 20, 15, 29, tzinfo=UTC))
    after_lse = decision("IUSA.L", datetime(2026, 7, 20, 15, 30, tzinfo=UTC),
                         datetime(2026, 7, 20, 15, 31, tzinfo=UTC))
    before_us = decision("AAPL", datetime(2026, 7, 20, 20, 0, tzinfo=UTC),
                         datetime(2026, 7, 20, 19, 59, tzinfo=UTC))
    after_us = decision("AAPL", datetime(2026, 7, 20, 20, 0, tzinfo=UTC),
                        datetime(2026, 7, 20, 20, 1, tzinfo=UTC))
    check(not before_lse.eligible and after_lse.eligible, "LSE daily bar evaluates only after official close", issues)
    check(not before_us.eligible and after_us.eligible, "Nasdaq daily bar evaluates only after official close", issues)

    holiday = decision("AAPL", datetime(2026, 12, 25, 18, tzinfo=UTC),
                       datetime(2026, 12, 25, 19, tzinfo=UTC))
    weekend = decision("IUSA.L", datetime(2026, 7, 18, 15, 30, tzinfo=UTC),
                       datetime(2026, 7, 18, 16, tzinfo=UTC))
    early = decision("IUSA.L", datetime(2026, 12, 24, 12, 30, tzinfo=UTC),
                     datetime(2026, 12, 24, 12, 31, tzinfo=UTC))
    check(not holiday.eligible, "exchange holiday creates no equity evaluation", issues)
    check(not weekend.eligible, "weekend creates no equity evaluation", issues)
    check(early.eligible, "official LSE early close is recognized", issues)

    summer = decision("IUSA.L", datetime(2026, 7, 20, 15, 30, tzinfo=UTC),
                      datetime(2026, 7, 20, 15, 31, tzinfo=UTC))
    winter = decision("IUSA.L", datetime(2026, 12, 21, 16, 30, tzinfo=UTC),
                      datetime(2026, 12, 21, 16, 31, tzinfo=UTC))
    check(summer.eligible and winter.eligible, "LSE DST transition uses official UTC closes", issues)
    naive = decision("AAPL", datetime(2026, 7, 20, 20), datetime(2026, 7, 20, 21, tzinfo=UTC))
    future = decision("AAPL", datetime(2026, 7, 20, 20, tzinfo=UTC),
                      datetime(2026, 7, 20, 19, tzinfo=UTC))
    check(not naive.eligible and "timezone-aware" in naive.reason, "timezone-naive bar fails closed", issues)
    check(not future.eligible, "future or incomplete bar fails closed", issues)

    scratch = ROOT / ".tmp" / "per-market-bar-scheduler-validation"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    try:
        state = scratch / "processed.json"
        lock = scratch / "scheduler.lock"
        store = ProcessedBarStore(state, lock)
        acquired, _ = store.claim(after_lse, decision_timestamp=datetime(2026, 7, 20, 15, 31, tzinfo=UTC))
        duplicate, _ = store.claim(after_lse, decision_timestamp=datetime(2026, 7, 20, 15, 36, tzinfo=UTC))
        check(acquired and not duplicate, "repeated five-minute polls claim one daily bar once", issues)
        restarted = ProcessedBarStore(state, lock)
        check(restarted.is_processed(after_lse.identity), "runtime restart does not replay committed bar identity", issues)

        concurrent_state = scratch / "concurrent.json"
        concurrent_lock = scratch / "concurrent.lock"
        def claim_once(_):
            try:
                return ProcessedBarStore(concurrent_state, concurrent_lock).claim(
                    after_us, decision_timestamp=datetime(2026, 7, 20, 20, 1, tzinfo=UTC)
                )[0]
            except Exception:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim_once, range(2)))
        check(claims.count(True) == 1, "two runtime instances cannot claim the same bar", issues)

        retry_state = scratch / "retry.json"
        retry_store = ProcessedBarStore(retry_state, scratch / "retry.lock")
        retry_store.claim(crypto, decision_timestamp=sunday)
        retry_store.transition(crypto.identity, "FAILED_RETRYABLE", timestamp=sunday,
                               failure_reason="crash before execution", retry_eligible=True)
        retried, _ = retry_store.claim(crypto, decision_timestamp=sunday + timedelta(minutes=5))
        check(retried, "crash before execution can retry only after explicit retryable state", issues)
        retry_store.transition(crypto.identity, "SIGNAL_COMPUTED", timestamp=sunday + timedelta(minutes=5),
                               signal_result="BUY", related_event_ids=[crypto.identity.key])
        check(not retry_store.claim(crypto, decision_timestamp=sunday + timedelta(minutes=10))[0],
              "crash after deterministic event preparation cannot duplicate execution", issues)

        corrupt = scratch / "corrupt.json"
        corrupt.write_text("{bad", encoding="utf-8")
        try:
            ProcessedBarStore(corrupt, scratch / "corrupt.lock").load()
            corrupt_blocked = False
        except SchedulerError:
            corrupt_blocked = True
        check(corrupt_blocked, "corrupt processed-bar state fails closed", issues)

        identity_strategy = BarIdentity(**{**after_lse.identity.__dict__, "strategy_version": "strategy-v2"})
        identity_config = BarIdentity(**{**after_lse.identity.__dict__, "configuration_version": "config-v2"})
        check(identity_strategy.key != after_lse.identity.key, "strategy version changes processing identity", issues)
        check(identity_config.key != after_lse.identity.key, "configuration version changes processing identity", issues)

        position = {"entry_date": "2026-07-01", "signal_exit_count": 0, "last_signal_exit_check": ""}
        first = signal_exit_status(position, 0, "2026-07-20", after_lse.identity.key)
        position.update(signal_exit_count=first["count"], last_signal_exit_check=first["last_check"])
        repeated = signal_exit_status(position, 0, "2026-07-20", after_lse.identity.key)
        next_bar = signal_exit_status(position, 0, "2026-07-21", identity_config.key)
        check(first["count"] == repeated["count"] == 1, "duplicate bar does not advance exit confirmation", issues)
        check(next_bar["count"] == 2, "exit confirmation advances once on a distinct bar identity", issues)

        close_frame = pd.DataFrame(
            {"BTC-GBP": [1.0], "IUSA.L": [1.0]},
            index=[pd.Timestamp("2026-07-18")],
        )
        subset_policies = {key: policies[key] for key in close_frame.columns}
        orchestration = schedule_completed_bars(
            close_frame, now=sunday, strategy_version=STRATEGY,
            configuration_version=CONFIG, data_source="fixture",
            execution_block_reason="monitor_only", policies=subset_policies,
            store=ProcessedBarStore(scratch / "monitor.json", scratch / "monitor.lock"),
        )
        statuses = {row["symbol"]: row["status"] for row in orchestration["decisions"]}
        check(statuses["BTC-GBP"] == "EXECUTION_BLOCKED" and statuses["IUSA.L"] == "FAILED_FINAL",
              "monitor-only records crypto decision without authorizing Sunday LSE", issues)
        check(not orchestration["eligible_symbols"], "monitor-only never invokes execution", issues)
        dashboard = load_scheduler_state(scratch / "monitor.json")
        before = state.read_bytes()
        load_scheduler_state(state)
        check(before == state.read_bytes(), "dashboard scheduler reader is read-only", issues)
        check("BTC-GBP" in dashboard.instruments, "scheduler health exposes last status per instrument", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    missing = evaluate_completed_bar("UNKNOWN", datetime(2026, 7, 20, tzinfo=UTC), now=datetime(2026, 7, 20, 1, tzinfo=UTC),
                                     strategy_version=STRATEGY, configuration_version=CONFIG, data_source="fixture")
    check(not missing.eligible and "missing calendar" in missing.reason, "missing calendar metadata blocks instrument", issues)
    config = {"_config_exists": True, "mode": "monitor_only", "allowed_modes": ["monitor_only", "paper_execution"], "paper_execution_enabled": False}
    check(paper_execution_blocked_reason(config, ["CRYPTO"], now=sunday) == "mode is monitor_only",
          "execution-disabled monitor configuration remains respected", issues)

    runtime_source = (ROOT / "runtime/live_runtime.py").read_text(encoding="utf-8")
    main_source = (ROOT / "main_v2.py").read_text(encoding="utf-8")
    check("eligible_symbols=scheduler_summary[\"eligible_symbols\"]" in runtime_source,
          "runtime passes only independently scheduled symbols to execution", issues)
    check("Per-instrument completed-bar eligibility is required" in main_source,
          "legacy all-asset main path fails closed", issues)
    reader_source = (ROOT / "dashboard/scheduler_reader.py").read_text(encoding="utf-8")
    check("write_text" not in reader_source and "atomic_write" not in reader_source,
          "dashboard scheduler reader has no write path", issues)

    if issues:
        print(f"Per-market bar scheduler validation failed: {len(issues)} issue(s)")
        return 1
    print("Per-market once-per-completed-bar scheduler validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
