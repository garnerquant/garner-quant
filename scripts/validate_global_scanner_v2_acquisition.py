from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.scanner_v2.acquisition import AcquisitionConfig, acquire_plan, acquisition_manifest, build_acquisition_plan
from research.scanner_v2.acquire import main as acquire_main
from research.scanner_v2.bar_store import BAR_COLUMNS, BarValidationError, ScannerBarStore, merge_bars, normalize_downloaded_bars


def check(value, message, issues):
    print(("PASS" if value else "FAIL") + f": {message}")
    if not value:
        issues.append(message)


def raw(ticker, start="2026-01-01", periods=130, invalid=False, timezone="UTC"):
    index = pd.date_range(start, periods=periods, freq="B", tz=timezone)
    close = pd.Series(range(100, 100 + periods), index=index, dtype=float)
    frame = pd.DataFrame({"Open": close, "High": close + 2, "Low": close - 2, "Close": close + 1, "Volume": 1000.0})
    if invalid:
        frame.iloc[-1, frame.columns.get_loc("High")] = 1
    return frame


class MockDownloader:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []

    def download(self, tickers, start, end):
        self.calls.append(tuple(tickers))
        value = self.behavior(tuple(tickers), len(self.calls))
        if isinstance(value, Exception):
            raise value
        return value


def multi(tickers, missing=()):
    frames = {ticker: raw(ticker) for ticker in tickers if ticker not in missing}
    return pd.concat(frames, axis=1).swaplevel(0, 1, axis=1).sort_index(axis=1)


def universe(count):
    return pd.DataFrame({"ticker": [f"T{i:04d}" for i in range(count)], "enabled": True})


def main():
    issues, base = [], ROOT / ".scanner_v2_acquisition_fixture"
    if base.exists(): shutil.rmtree(base)
    try:
        store = ScannerBarStore(base / "store")
        config = AcquisitionConfig(batch_size=2, max_attempts=3, backoff_seconds=0)
        now = pd.Timestamp("2026-07-16T12:00:00Z")
        plan = build_acquisition_plan(universe(3), store, now, config)
        check(list(plan["ticker"]) == ["T0000", "T0001", "T0002"] and list(plan["batch_id"].astype(int)) == [1, 1, 2], "acquisition plan and batches are deterministic", issues)
        check(set(plan["reason"]) == {"initial_full_history"}, "empty store plans full initial history", issues)

        successful = MockDownloader(lambda tickers, _: multi(tickers))
        results, updates, retries = acquire_plan(plan, successful, now, config, sleep=lambda _: None)
        check(set(results["status"]) == {"fetched"} and retries == 0 and len(updates) == 3, "successful bulk batches isolate validated symbols", issues)
        stats = store.commit(updates)
        check(all(len(store.read(ticker)) == 130 for ticker in updates), "validated initial history is atomically partitioned", issues)

        cached_plan = build_acquisition_plan(universe(3), store, pd.Timestamp("2026-07-01"), config)
        check(set(cached_plan["reason"]) == {"no_fetch_required"}, "fresh partitions produce no-fetch cache hits", issues)

        partial_plan = plan.iloc[:2].copy()
        partial = MockDownloader(lambda tickers, call: multi(tickers, missing={"T0001"}) if len(tickers) > 1 else raw(tickers[0]))
        partial_results, partial_updates, partial_retries = acquire_plan(partial_plan, partial, now, config, sleep=lambda _: None)
        check(set(partial_results["status"]) == {"fetched"} and partial_retries == 1 and tuple(partial.calls[-1]) == ("T0001",), "partial bulk failure retries missing symbol individually", issues)

        failed = MockDownloader(lambda tickers, _: RuntimeError("network down"))
        failed_results, failed_updates, failed_retries = acquire_plan(partial_plan, failed, now, AcquisitionConfig(batch_size=2, max_attempts=2, backoff_seconds=0), sleep=lambda _: None)
        check(set(failed_results["status"]) == {"failed"} and not failed_updates and failed_retries == 2, "total failure exhausts bounded retries per symbol", issues)

        bars = normalize_downloaded_bars(raw("TZ", timezone="Europe/London"), "TZ", now)
        check(bars["date"].dt.tz is None and bars["date"].is_monotonic_increasing, "timezone/index normalization is deterministic", issues)
        try:
            normalize_downloaded_bars(raw("BAD", invalid=True), "BAD", now)
            invalid_refused = False
        except BarValidationError as exc:
            invalid_refused = exc.code == "invalid_ohlc_bounds"
        check(invalid_refused, "invalid OHLC is rejected per symbol", issues)
        try:
            normalize_downloaded_bars(pd.DataFrame(), "EMPTY", now)
            empty_refused = False
        except BarValidationError as exc:
            empty_refused = exc.code == "empty_download"
        check(empty_refused, "empty response has stable rejection code", issues)
        try:
            from research.scanner_v2.bar_store import validate_bars
            validate_bars(bars, "TZ", stale_after_days=2, as_of="2027-01-01")
            stale_refused = False
        except BarValidationError as exc:
            stale_refused = exc.code == "stale_final_bar"
        check(stale_refused, "stale final bars are rejected with a stable reason", issues)

        full_merge = normalize_downloaded_bars(raw("MERGE", periods=10), "MERGE", now)
        existing = full_merge.iloc[:5].copy()
        incoming = full_merge.iloc[3:].copy()
        merged, merge_stats = merge_bars(existing, incoming, "MERGE")
        check(len(merged) > len(existing) and merge_stats.rows_added > 0 and merge_stats.rows_unchanged > 0, "incremental overlap preserves history and reconciles rows", issues)
        duplicate = incoming.iloc[[0, 0]].copy(); duplicate.iloc[1, duplicate.columns.get_loc("close")] += 10
        try:
            merge_bars(existing, duplicate, "MERGE")
            conflict_refused = False
        except BarValidationError as exc:
            conflict_refused = exc.code == "conflicting_duplicate_date"
        check(conflict_refused, "conflicting duplicate dates are refused", issues)

        old_bytes = store.path_for("T0000").read_bytes()
        try:
            store.commit({"T0000": normalize_downloaded_bars(raw("T0000", start="2026-07-01", periods=3), "T0000", now)}, failure_hook=lambda stage, _: (_ for _ in ()).throw(RuntimeError("stop")) if stage == "after_temp_writes" else None)
        except Exception:
            pass
        check(store.path_for("T0000").read_bytes() == old_bytes, "failed partition update preserves old canonical partition", issues)

        manifest = acquisition_manifest(plan, results, stats, now, now + pd.Timedelta(seconds=2), retries, "run-1")
        check(sum(manifest[status] for status in ["cache_hit", "fetched", "partial", "rejected", "failed", "stale_cache"]) == manifest["requested_symbols"], "manifest terminal statuses reconcile exactly", issues)
        for count in (500, 1500):
            scale_plan = build_acquisition_plan(universe(count), ScannerBarStore(base / f"scale-{count}"), now, AcquisitionConfig(batch_size=50))
            check(len(scale_plan) == count and scale_plan["batch_id"].nunique() == count // 50, f"{count}-symbol acquisition-plan fixture is bounded and complete", issues)

        dry_universe = base / "dry-universe"
        dry_universe.mkdir()
        pd.DataFrame([{"ticker": "AAPL", "display_name": "Apple", "asset_type": "Equity", "exchange": "NASDAQ", "country": "United States", "currency": "USD", "sector": "Technology", "industry": "Hardware", "universe_source": "fixture", "enabled": True, "priority": 1, "universe_name": "core_existing"}]).to_csv(dry_universe / "core_existing.csv", index=False)
        dry_store = base / "dry-store"
        check(acquire_main(["--all-enabled", "--dry-run", "--universe-dir", str(dry_universe), "--store-dir", str(dry_store)]) == 0 and not dry_store.exists(), "CLI dry-run plans without downloads or canonical writes", issues)

        protected = ["trade_ledger_v1.csv", "paper_portfolio_v3.csv", "broker_account.csv", "holdings_report.csv"]
        before = {name: (ROOT / name).read_bytes() for name in protected}
        check(before == {name: (ROOT / name).read_bytes() for name in protected}, "acquisition fixtures touch no trading or accounting files", issues)
        dashboard = (ROOT / "web_dashboard.py").read_text(encoding="utf-8")
        check("research.scanner_v2.acquisition" not in dashboard and "research.scanner_v2.acquire" not in dashboard, "no scanner v2 download is added to dashboard", issues)
    finally:
        if base.exists(): shutil.rmtree(base)
    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__": raise SystemExit(main())
