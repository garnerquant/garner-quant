from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import time

import pandas as pd
import yfinance as yf

from data.yfinance_cache import configure_yfinance_cache_for_ci
from research.scanner_v2.bar_store import BarValidationError, ScannerBarStore, normalize_downloaded_bars
from research.scanner_v2.universe import deterministic_batches, incremental_refresh_start


TERMINAL_STATUSES = {"cache_hit", "fetched", "partial", "rejected", "failed", "stale_cache"}


@dataclass(frozen=True)
class AcquisitionConfig:
    batch_size: int = 50
    max_workers: int = 1
    max_attempts: int = 3
    backoff_seconds: float = 0.25
    overlap_days: int = 5
    full_history_days: int = 1095
    freshness_days: int = 1
    minimum_history: int = 126


def configure_scanner_yfinance_cache(root):
    """Use a scanner-process cache without changing shared trading cache policy."""
    configure_yfinance_cache_for_ci()
    cache = Path(root) / ".yfinance" / f"process-{os.getpid()}"
    cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache))
    return cache


def build_acquisition_plan(universe, store, now, config=AcquisitionConfig(), quarantine=None):
    quarantine = quarantine or {}
    end = pd.Timestamp(now).normalize()
    rows = []
    tickers = sorted(universe.loc[universe["enabled"].astype(bool), "ticker"].astype(str).unique())
    fetch_tickers = []
    cached = {}
    for ticker in tickers:
        last = store.last_date(ticker)
        cached[ticker] = last
        if ticker in quarantine:
            reason, start = "quarantine_retry", incremental_refresh_start(last, end, config.overlap_days, config.full_history_days)
        elif pd.isna(last):
            reason, start = "initial_full_history", incremental_refresh_start(pd.NaT, end, config.overlap_days, config.full_history_days)
        elif last >= end - pd.Timedelta(days=config.freshness_days):
            reason, start = "no_fetch_required", pd.NaT
        else:
            gap = (end - last).days
            reason = "gap_repair" if gap > config.overlap_days * 2 else "incremental_refresh"
            start = incremental_refresh_start(last, end, config.overlap_days, config.full_history_days)
        if reason != "no_fetch_required":
            fetch_tickers.append(ticker)
        rows.append({"ticker": ticker, "requested_start": start, "requested_end": end, "reason": reason, "cached_last_date": last, "required_minimum_history": config.minimum_history, "attempt_policy": f"max_attempts={config.max_attempts}", "batch_id": pd.NA})
    batch_map = {ticker: index for index, batch in enumerate(deterministic_batches(fetch_tickers, config.batch_size), start=1) for ticker in batch}
    for row in rows:
        if row["ticker"] in batch_map:
            row["batch_id"] = batch_map[row["ticker"]]
    return pd.DataFrame(rows).sort_values("ticker", kind="stable").reset_index(drop=True)


class YFinanceDownloader:
    def download(self, tickers, start, end):
        return yf.download(tickers, start=pd.Timestamp(start).date(), end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date(), interval="1d", auto_adjust=True, progress=False, threads=False)


def _extract_symbol(raw, ticker, multi_ticker):
    if raw is None or raw.empty:
        return pd.DataFrame()
    if multi_ticker and isinstance(raw.columns, pd.MultiIndex):
        for level in range(raw.columns.nlevels):
            if ticker in set(raw.columns.get_level_values(level).astype(str)):
                return raw.xs(ticker, axis=1, level=level, drop_level=True).dropna(how="all")
        return pd.DataFrame()
    return raw.dropna(how="all")


def acquire_plan(plan, downloader, fetched_at, config=AcquisitionConfig(), sleep=time.sleep):
    """Run deterministic batches; isolate partial failures with individual fallback."""
    results, updates, retries = [], {}, 0
    fetch = plan[plan["reason"].ne("no_fetch_required")]
    for row in plan[plan["reason"].eq("no_fetch_required")].to_dict(orient="records"):
        results.append({"ticker": row["ticker"], "status": "cache_hit", "reason_code": "fresh_cache", "detail": "No fetch required", "attempts": 0, "rows_downloaded": 0, "batch_id": row["batch_id"]})
    for batch_id, group in fetch.groupby("batch_id", sort=True):
        rows = group.sort_values("ticker").to_dict(orient="records")
        tickers = [row["ticker"] for row in rows]
        start, end = min(row["requested_start"] for row in rows), max(row["requested_end"] for row in rows)
        try:
            raw = downloader.download(tickers, start, end)
        except Exception:
            raw = pd.DataFrame()
        for row in rows:
            ticker, attempts, last_error, bars = row["ticker"], 1, None, None
            candidate = _extract_symbol(raw, ticker, len(tickers) > 1)
            try:
                bars = normalize_downloaded_bars(candidate, ticker, fetched_at)
            except BarValidationError as exc:
                last_error = exc
            while bars is None and attempts < config.max_attempts:
                retries += 1
                sleep(config.backoff_seconds * (2 ** (attempts - 1)))
                attempts += 1
                try:
                    individual = downloader.download([ticker], row["requested_start"], row["requested_end"])
                    bars = normalize_downloaded_bars(_extract_symbol(individual, ticker, False), ticker, fetched_at)
                except BarValidationError as exc:
                    last_error = exc
                    bars = None
                except Exception as exc:
                    last_error = BarValidationError("download_error", f"{ticker}: {exc}")
            if bars is None:
                results.append({"ticker": ticker, "status": "failed", "reason_code": last_error.code if last_error else "download_error", "detail": last_error.detail if last_error else "Download failed", "attempts": attempts, "rows_downloaded": 0, "batch_id": batch_id})
            else:
                updates[ticker] = bars
                results.append({"ticker": ticker, "status": "fetched", "reason_code": "ok", "detail": "Validated bars acquired", "attempts": attempts, "rows_downloaded": len(bars), "batch_id": batch_id})
    return pd.DataFrame(results).sort_values("ticker", kind="stable").reset_index(drop=True), updates, retries


def acquisition_manifest(plan, results, stats, started_at, ended_at, retries, run_id):
    if results["ticker"].duplicated().any() or not set(results["status"]).issubset(TERMINAL_STATUSES):
        raise ValueError("Acquisition results do not have one valid terminal status per ticker")
    status_counts = results["status"].value_counts().to_dict()
    manifest = {"run_id": run_id, "started_at": pd.Timestamp(started_at).isoformat(), "ended_at": pd.Timestamp(ended_at).isoformat(), "duration_seconds": max(0.0, (pd.Timestamp(ended_at) - pd.Timestamp(started_at)).total_seconds()), "requested_symbols": len(plan), "batch_count": int(plan["batch_id"].dropna().nunique()), "retry_count": int(retries)}
    for status in sorted(TERMINAL_STATUSES):
        manifest[status] = int(status_counts.get(status, 0))
    manifest["rows_added"] = sum(value.rows_added for value in stats.values())
    manifest["rows_replaced"] = sum(value.rows_replaced for value in stats.values())
    manifest["rows_unchanged"] = sum(value.rows_unchanged for value in stats.values())
    if sum(manifest[status] for status in TERMINAL_STATUSES) != manifest["requested_symbols"]:
        raise ValueError("Acquisition manifest terminal counts do not reconcile")
    manifest["partial_coverage"] = manifest["failed"] + manifest["rejected"] + manifest["stale_cache"] > 0
    return manifest
