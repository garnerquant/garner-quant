"""Forward-return outcomes from explicitly pinned canonical Scanner bar data."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


FORWARD_HORIZONS = (5, 20, 60, 120, 252)


def _partition_name(ticker: str) -> str:
    safe = ticker.replace("^", "_INDEX_").replace("=", "_EQ_").replace("-", "_DASH_").replace(".", "_DOT_")
    return f"{safe}.csv"


def _current_bar_generation(root: Path) -> str:
    pointer = root / "current_generation.json"
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("No valid current Scanner bar generation is available") from exc
    identity = str(payload.get("generation_id", "")).strip()
    if not identity or Path(identity).name != identity:
        raise ValueError("Current Scanner bar generation identity is invalid")
    return identity


def _load_prices(root: Path, generation_id: str, ticker: str) -> pd.DataFrame:
    generation = (root / "generations" / generation_id).resolve()
    if generation.parent != (root / "generations").resolve() or not generation.is_dir():
        raise ValueError(f"Outcome bar generation does not exist: {generation_id}")
    path = generation / "bars" / _partition_name(ticker)
    if not path.is_file():
        return pd.DataFrame(columns=["date", "close"])
    frame = pd.read_csv(path, usecols=["date", "close"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame[frame["close"].gt(0)].drop_duplicates("date", keep="last")
    return frame.sort_values("date", kind="stable").reset_index(drop=True)


def add_forward_returns(
    history: pd.DataFrame,
    bar_store_root: str | Path,
    outcome_generation: str = "current",
    horizons=FORWARD_HORIZONS,
) -> pd.DataFrame:
    """Add outcomes only; never reconstruct or replace point-in-time feature fields."""
    output = history.copy(deep=True)
    requested = tuple(sorted({int(value) for value in horizons}))
    if any(value <= 0 for value in requested):
        raise ValueError("Forward-return horizons must be positive")
    for horizon in requested:
        output[f"forward_return_{horizon}d_pct"] = np.nan
    output["forward_return_base_date"] = pd.NaT
    output["forward_return_base_close"] = np.nan
    output["outcome_bar_generation"] = ""
    if output.empty:
        return output
    required = {"ticker", "as_of_date", "generation_id"}
    if not required.issubset(output.columns):
        raise ValueError(f"Historical dataset is missing: {sorted(required - set(output.columns))}")

    root = Path(bar_store_root).resolve()
    identity = _current_bar_generation(root) if outcome_generation == "current" else str(outcome_generation)
    if not identity or Path(identity).name != identity:
        raise ValueError("Outcome bar generation identity is invalid")
    cache = {}
    for index, row in output.iterrows():
        ticker = str(row["ticker"])
        if ticker not in cache:
            cache[ticker] = _load_prices(root, identity, ticker)
        prices = cache[ticker]
        as_of = pd.to_datetime(row["as_of_date"], errors="coerce")
        if prices.empty or pd.isna(as_of):
            continue
        positions = prices.index[prices["date"].ge(pd.Timestamp(as_of).normalize())]
        if positions.empty:
            continue
        base_index = int(positions[0])
        base_close = float(prices.at[base_index, "close"])
        output.at[index, "forward_return_base_date"] = prices.at[base_index, "date"]
        output.at[index, "forward_return_base_close"] = base_close
        output.at[index, "outcome_bar_generation"] = identity
        for horizon in requested:
            target_index = base_index + horizon
            if target_index < len(prices):
                target = float(prices.at[target_index, "close"])
                output.at[index, f"forward_return_{horizon}d_pct"] = (target / base_close - 1) * 100
    return output
