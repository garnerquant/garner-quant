from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd


CANONICAL_UNIVERSE_COLUMNS = [
    "ticker", "display_name", "asset_type", "exchange", "country",
    "currency", "sector", "industry", "universe_source", "enabled",
    "priority", "max_position_weight", "first_seen_at", "last_verified_at",
]
MEMBERSHIP_COLUMNS = ["ticker", "universe_name", "universe_source"]
SUPPORTED_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,31}$")


@dataclass(frozen=True)
class EligibilityRules:
    supported_exchanges: frozenset[str] = frozenset()
    supported_currencies: frozenset[str] = frozenset()
    minimum_history_bars: int = 126
    minimum_price: float = 0.01
    minimum_average_traded_value: float = 0.0
    maximum_missing_fraction: float = 0.10


def normalize_ticker(value):
    ticker = str(value or "").strip().upper().replace(" ", "")
    return ticker


def _truthy(series):
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _canonical_rows(frame, source_path, observed_at):
    source_name = source_path.stem
    ticker_source = "ticker" if "ticker" in frame else "yahoo_ticker"
    if ticker_source not in frame:
        raise ValueError(f"{source_path} has no ticker or yahoo_ticker column")
    result = pd.DataFrame()
    result["ticker"] = frame[ticker_source].map(normalize_ticker)
    result["display_name"] = frame.get("display_name", frame.get("name", result["ticker"])).fillna(result["ticker"])
    result["asset_type"] = frame.get("asset_type", frame.get("asset_class", "Unknown")).fillna("Unknown")
    for column, fallback in (("exchange", "Unknown"), ("country", "Unknown"), ("currency", "Unknown"), ("sector", "Unknown"), ("industry", "Unknown")):
        result[column] = frame.get(column, pd.Series(fallback, index=frame.index)).fillna(fallback)
    result["universe_source"] = frame.get("universe_source", frame.get("index_source", source_name)).fillna(source_name)
    enabled = frame.get("enabled", frame.get("active", pd.Series(True, index=frame.index)))
    result["enabled"] = enabled if enabled.dtype == bool else _truthy(enabled)
    result["priority"] = pd.to_numeric(frame.get("priority", 100), errors="coerce").fillna(100).astype(int) if isinstance(frame.get("priority", 100), pd.Series) else 100
    result["max_position_weight"] = pd.to_numeric(frame.get("max_position_weight", np.nan), errors="coerce")
    result["first_seen_at"] = frame.get("first_seen_at", observed_at)
    result["last_verified_at"] = frame.get("last_verified_at", observed_at)
    result["universe_name"] = frame.get("universe_name", source_name)
    return result


def load_canonical_universe(universe_dir, observed_at=None):
    """Merge named universe files deterministically without losing membership."""
    directory = Path(universe_dir)
    paths = sorted(directory.glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No universe CSV files found in {directory}")
    timestamp = pd.Timestamp(observed_at or pd.Timestamp.now(tz="UTC")).isoformat()
    rows = []
    for path in paths:
        rows.append(_canonical_rows(pd.read_csv(path), path, timestamp))
    combined = pd.concat(rows, ignore_index=True)
    combined = combined[combined["ticker"].ne("")].copy()
    combined = combined.sort_values(["ticker", "priority", "universe_name"], kind="stable")
    memberships = combined[["ticker", "universe_name", "universe_source"]].drop_duplicates().sort_values(["ticker", "universe_name"]).reset_index(drop=True)

    conflicts = []
    for ticker, group in combined.groupby("ticker", sort=True):
        for column in ["asset_type", "exchange", "country", "currency"]:
            values = sorted(set(group[column].dropna().astype(str)) - {"", "Unknown"})
            if len(values) > 1:
                conflicts.append(f"{ticker}:{column}={values}")
    if conflicts:
        raise ValueError("Ambiguous canonical universe metadata: " + "; ".join(conflicts))

    universe = combined.drop_duplicates("ticker", keep="first")[CANONICAL_UNIVERSE_COLUMNS]
    universe = universe.sort_values(["priority", "ticker"], kind="stable").reset_index(drop=True)
    return universe, memberships


def structural_eligibility(universe, rules=EligibilityRules()):
    """Apply cheap deterministic rules before any market-data request."""
    eligible_rows, rejected_rows = [], []
    for row in universe.to_dict(orient="records"):
        reasons = []
        ticker = normalize_ticker(row.get("ticker"))
        if not row.get("enabled", False):
            reasons.append("disabled")
        if not SUPPORTED_TICKER.fullmatch(ticker):
            reasons.append("unsupported_ticker_format")
        if rules.supported_exchanges and str(row.get("exchange")) not in rules.supported_exchanges:
            reasons.append("unsupported_exchange")
        if rules.supported_currencies and str(row.get("currency")) not in rules.supported_currencies:
            reasons.append("unsupported_currency")
        row["ticker"] = ticker
        if reasons:
            row["rejection_reasons"] = "|".join(sorted(reasons))
            rejected_rows.append(row)
        else:
            eligible_rows.append(row)
    return pd.DataFrame(eligible_rows, columns=universe.columns), pd.DataFrame(rejected_rows)


def market_data_eligibility(features, rules=EligibilityRules()):
    """Return one explicit rejection reason set for each ineligible feature row."""
    accepted, rejected = [], []
    for row in features.to_dict(orient="records"):
        reasons = []
        checks = (
            (float(row.get("valid_bar_count", 0)) < rules.minimum_history_bars, "insufficient_history"),
            (not np.isfinite(row.get("latest_close", np.nan)) or float(row.get("latest_close", 0)) < rules.minimum_price, "price_below_minimum"),
            (float(row.get("avg_traded_value_60d", 0)) < rules.minimum_average_traded_value, "liquidity_below_minimum"),
            (float(row.get("missing_close_pct", 1)) > rules.maximum_missing_fraction, "missing_data_exceeds_tolerance"),
            (bool(row.get("download_failed", False)), "download_failed"),
            (bool(row.get("quarantined", False)), "quarantined"),
        )
        reasons.extend(reason for failed, reason in checks if failed)
        row["exclusion_reasons"] = "|".join(sorted(set(reasons)))
        (rejected if reasons else accepted).append(row)
    return pd.DataFrame(accepted), pd.DataFrame(rejected)


def deterministic_batches(tickers, batch_size):
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    ordered = sorted(set(normalize_ticker(ticker) for ticker in tickers if normalize_ticker(ticker)))
    return [ordered[index:index + batch_size] for index in range(0, len(ordered), batch_size)]


def incremental_refresh_start(last_success, now, overlap_days=5, full_history_days=1095):
    now = pd.Timestamp(now)
    if pd.isna(last_success):
        return now - pd.Timedelta(days=full_history_days)
    last = pd.Timestamp(last_success)
    if last.tzinfo is None and now.tzinfo is not None:
        last = last.tz_localize(now.tzinfo)
    return min(last - pd.Timedelta(days=overlap_days), now)
