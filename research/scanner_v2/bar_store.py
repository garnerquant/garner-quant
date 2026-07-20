from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
from uuid import uuid4

import numpy as np
import pandas as pd

from execution.atomic_io import atomic_write_csv_frames


BAR_COLUMNS = [
    "ticker", "date", "open", "high", "low", "close", "volume",
    "source", "fetched_at", "adjusted",
]


class BarValidationError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MergeStats:
    rows_added: int
    rows_replaced: int
    rows_unchanged: int


def partition_name(ticker):
    safe = ticker.replace("^", "_INDEX_").replace("=", "_EQ_").replace("-", "_DASH_").replace(".", "_DOT_")
    return f"{safe}.csv"


def normalize_downloaded_bars(frame, ticker, fetched_at, source="yfinance", adjusted=True):
    if frame is None or frame.empty:
        raise BarValidationError("empty_download", f"{ticker}: download returned no bars")
    bars = frame.copy()
    if isinstance(bars.columns, pd.MultiIndex):
        matching = [level for level in range(bars.columns.nlevels) if ticker in set(bars.columns.get_level_values(level).astype(str))]
        if not matching:
            raise BarValidationError("unsupported_column_structure", f"{ticker}: ticker not present in multi-index columns")
        bars = bars.xs(ticker, axis=1, level=matching[0], drop_level=True)
    columns = {str(column).strip().lower().replace(" ", "_"): column for column in bars.columns}
    required = ["open", "high", "low", "close"]
    missing = [field for field in required if field not in columns]
    if missing:
        raise BarValidationError("missing_ohlc_fields", f"{ticker}: missing {missing}")
    output = pd.DataFrame({field: pd.to_numeric(bars[columns[field]], errors="coerce") for field in required})
    output["volume"] = pd.to_numeric(bars[columns["volume"]], errors="coerce") if "volume" in columns else 0.0
    dates = pd.to_datetime(bars.index, errors="coerce", utc=True)
    if dates.isna().any():
        raise BarValidationError("invalid_timestamp", f"{ticker}: unparseable timestamps")
    output["date"] = dates.tz_convert(None).normalize()
    output["ticker"] = ticker
    output["source"] = source
    output["fetched_at"] = pd.Timestamp(fetched_at).isoformat()
    output["adjusted"] = bool(adjusted)
    return validate_bars(output[BAR_COLUMNS], ticker)


def validate_bars(bars, ticker, minimum_history=1, stale_after_days=None, as_of=None):
    if bars.empty:
        raise BarValidationError("empty_download", f"{ticker}: no bars")
    missing = [column for column in BAR_COLUMNS if column not in bars]
    if missing:
        raise BarValidationError("invalid_bar_schema", f"{ticker}: missing {missing}")
    result = bars.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    if result["date"].isna().any():
        raise BarValidationError("invalid_timestamp", f"{ticker}: invalid dates")
    if result.duplicated(["ticker", "date"]).any():
        duplicate_groups = result[result.duplicated(["ticker", "date"], keep=False)].groupby(["ticker", "date"])
        for _, group in duplicate_groups:
            comparable = group[["open", "high", "low", "close", "volume"]].drop_duplicates()
            if len(comparable) > 1:
                raise BarValidationError("conflicting_duplicate_date", f"{ticker}: conflicting duplicate date")
        result = result.drop_duplicates(["ticker", "date"], keep="last")
    result = result.sort_values("date", kind="stable").reset_index(drop=True)
    for column in ["open", "high", "low", "close"]:
        values = pd.to_numeric(result[column], errors="coerce")
        if not np.isfinite(values).all() or (values <= 0).any():
            raise BarValidationError("invalid_price", f"{ticker}: {column} must be finite and positive")
        result[column] = values
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    if not np.isfinite(result["volume"]).all() or (result["volume"] < 0).any():
        raise BarValidationError("invalid_volume", f"{ticker}: volume must be finite and non-negative")
    if (result["high"] < result["low"]).any() or (result["open"] > result["high"]).any() or (result["open"] < result["low"]).any() or (result["close"] > result["high"]).any() or (result["close"] < result["low"]).any():
        raise BarValidationError("invalid_ohlc_bounds", f"{ticker}: OHLC bounds are inconsistent")
    if len(result) < minimum_history:
        raise BarValidationError("insufficient_history", f"{ticker}: {len(result)} bars; requires {minimum_history}")
    if stale_after_days is not None:
        reference = pd.Timestamp(as_of or pd.Timestamp.now(tz="UTC")).tz_localize(None).normalize()
        if result["date"].iloc[-1] < reference - pd.Timedelta(days=stale_after_days):
            raise BarValidationError("stale_final_bar", f"{ticker}: final bar {result['date'].iloc[-1].date()} is stale")
    return result[BAR_COLUMNS]


def merge_bars(existing, incoming, ticker):
    current = validate_bars(existing, ticker) if existing is not None and not existing.empty else pd.DataFrame(columns=BAR_COLUMNS)
    update = validate_bars(incoming, ticker)
    current_by_date = current.set_index("date") if not current.empty else current
    incoming_by_date = update.set_index("date")
    overlap = set(current_by_date.index) & set(incoming_by_date.index) if not current.empty else set()
    replaced = sum(not current_by_date.loc[date, ["open", "high", "low", "close", "volume"]].equals(incoming_by_date.loc[date, ["open", "high", "low", "close", "volume"]]) for date in overlap)
    unchanged = len(overlap) - replaced
    added = len(set(incoming_by_date.index) - set(current_by_date.index)) if not current.empty else len(update)
    merged = pd.concat([current, update], ignore_index=True).drop_duplicates(["ticker", "date"], keep="last")
    return validate_bars(merged, ticker), MergeStats(added, replaced, unchanged)


class ScannerBarStore:
    def __init__(self, root):
        self.root = Path(root)
        self.generations = self.root / "generations"
        self.pointer = self.root / "current_generation.json"

    def current_generation(self):
        if not self.pointer.exists():
            return None
        return json.loads(self.pointer.read_text(encoding="utf-8"))["generation_id"]

    @property
    def partitions(self):
        generation = self.current_generation()
        return self.root / "bars" if generation is None else self.generations / generation / "bars"

    def path_for(self, ticker):
        return self.partitions / partition_name(ticker)

    def read(self, ticker):
        path = self.path_for(ticker)
        if not path.exists():
            return pd.DataFrame(columns=BAR_COLUMNS)
        return validate_bars(pd.read_csv(path), ticker)

    def last_date(self, ticker):
        bars = self.read(ticker)
        return pd.NaT if bars.empty else pd.Timestamp(bars["date"].iloc[-1])

    def commit(self, updates, failure_hook=None, generation_id=None, csv_artifacts=None, json_artifacts=None):
        generation_id = generation_id or uuid4().hex
        staging = self.root / f".staging-{generation_id}"
        final_generation = self.generations / generation_id
        if staging.exists() or final_generation.exists():
            raise ValueError(f"Generation already exists: {generation_id}")
        staging_bars = staging / "bars"
        staging_bars.mkdir(parents=True, exist_ok=True)
        if self.partitions.exists():
            for source in sorted(self.partitions.glob("*.csv")):
                target = staging_bars / source.name
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
        frames, stats = {}, {}
        try:
            for ticker in sorted(updates):
                merged, ticker_stats = merge_bars(self.read(ticker), updates[ticker], ticker)
                frames[staging_bars / partition_name(ticker)] = merged
                stats[ticker] = ticker_stats
            for relative, frame in (csv_artifacts or {}).items():
                frames[staging / relative] = frame
            atomic_write_csv_frames(
                frames,
                failure_hook=failure_hook,
                lock_path=self.root / ".bar-store.lock",
            )
            for relative, payload in (json_artifacts or {}).items():
                path = staging / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(payload, indent=2, default=str),
                    encoding="utf-8",
                )
            self.generations.mkdir(parents=True, exist_ok=True)
            staging.replace(final_generation)
            from execution.atomic_io import atomic_write_json
            atomic_write_json(
                {"generation_id": generation_id},
                self.pointer,
                lock_path=self.root / ".bar-store.lock",
            )
            return stats
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
