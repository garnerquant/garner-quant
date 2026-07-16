from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from config import CRYPTO_MA_THRESHOLD, DEFAULT_MA_THRESHOLD, ETF_MA_THRESHOLD, STOCK_MA_THRESHOLD
from research.scanner_v2.bar_store import ScannerBarStore
from research.scanner_v2.universe import load_canonical_universe


FEATURE_SCHEMA_VERSION = "scanner-features-v1"
SCORING_VERSION = "legacy-scanner-score-v1"
TERMINAL_STATES = {"scored", "rejected", "failed"}
OUTPUT_NAMES = (
    "scanner_features.csv", "latest_rankings.csv", "selected_candidates.csv",
    "rejected_assets.csv", "ranking_movement.csv", "scanner_generation_manifest.json",
)
COMPARISON_FIELDS = {
    "ticker", "display_name", "sector", "industry", "country", "currency",
    "exchange", "asset_type", "latest_close", "technical_score", "scanner_score",
    "avg_traded_value_60d", "volatility_20d", "volatility_60d", "atr_percent",
    "max_drawdown_1y", "trend_stability_score", "risk_level",
    "data_quality_confidence", "global_rank", "rank_delta", "score_delta",
    "days_in_top_list", "consecutive_days_seen", "highest_rank_seen",
    "average_rank", "rank_volatility", "persistence_score", "persistence_level",
}


@dataclass(frozen=True)
class FeaturePolicy:
    top_n: int = 15
    minimum_history: int = 126
    stale_after_days: int = 7
    maximum_missing_fraction: float = 0.10


def _ma_threshold(ticker):
    if ticker.endswith(".L"):
        return ETF_MA_THRESHOLD
    if ticker in {"AAPL", "MSFT", "NVDA"}:
        return STOCK_MA_THRESHOLD
    if "BTC" in ticker or "ETH" in ticker:
        return CRYPTO_MA_THRESHOLD
    return DEFAULT_MA_THRESHOLD


def _technical_features(ticker, close, volume):
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rsi14 = 100 - (100 / (1 + gain / loss))
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    threshold = _ma_threshold(ticker)
    flags = {
        "price_above_ema20": bool(close.iloc[-1] > ema20.iloc[-1] * (1 + threshold)),
        "ema20_above_ema50": bool(ema20.iloc[-1] > ema50.iloc[-1] * (1 + threshold)),
        "rsi_in_range": bool(rsi14.iloc[-1] > 45 and rsi14.iloc[-1] < 70),
        "macd_above_signal": bool(macd.iloc[-1] > signal.iloc[-1]),
        "volume_above_20d_average": bool(volume.iloc[-1] > volume.rolling(20).mean().iloc[-1]),
    }
    return {**flags, "ema20": float(ema20.iloc[-1]), "ema50": float(ema50.iloc[-1]),
            "rsi14": float(rsi14.iloc[-1]), "macd": float(macd.iloc[-1]),
            "macd_signal": float(signal.iloc[-1]), "technical_score": float(sum(flags.values()))}


def _volatility(close, window):
    values = close.pct_change().dropna().tail(window)
    return np.nan if len(values) < 2 else float(values.std() * np.sqrt(252) * 100)


def _atr_percent(bars, window=14):
    previous = bars["close"].shift()
    true_range = pd.concat([(bars["high"] - bars["low"]),
                            (bars["high"] - previous).abs(),
                            (bars["low"] - previous).abs()], axis=1).max(axis=1)
    value = true_range.dropna().tail(window).mean()
    return np.nan if pd.isna(value) or bars["close"].iloc[-1] == 0 else float(value / bars["close"].iloc[-1] * 100)


def _max_drawdown(close):
    values = close.tail(252)
    return float(abs((values / values.cummax() - 1).min()) * 100)


def _trend_stability(close, volatility_60d, max_drawdown_1y):
    if len(close) < 60:
        return np.nan
    ema50 = close.ewm(span=50, adjust=False).mean()
    trend = float((close.tail(60) > ema50.tail(60)).mean()) * 40
    returns = close.pct_change().dropna().tail(60)
    threshold = max(0.03, float(returns.std() * 2))
    swing = (1 - min(float((returns.abs() > threshold).mean()) / .20, 1)) * 20
    vol = (1 - min(float(volatility_60d) / 80, 1)) * 20
    drawdown = (1 - min(float(max_drawdown_1y) / 50, 1)) * 20
    return float(max(0, min(trend + swing + vol + drawdown, 100)))


def _risk(volatility_60d, max_drawdown_1y, atr_percent):
    score = min(volatility_60d / 80, 1) * 40 + min(max_drawdown_1y / 60, 1) * 40 + min(atr_percent / 8, 1) * 20
    label = "Very Low" if score <= 20 else "Low" if score <= 40 else "Medium" if score <= 60 else "High" if score <= 80 else "Very High"
    return float(score), label


def calculate_ticker_features(ticker, bars, metadata, memberships, reference_date, policy=FeaturePolicy()):
    """Calculate one asset without cross-asset filling, coercion, or defaults."""
    required = {"date", "open", "high", "low", "close", "volume"}
    if bars.empty or not required.issubset(bars.columns):
        raise ValueError("missing_bar_partition_or_columns")
    frame = bars.copy().sort_values("date", kind="stable")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"non_finite_{column}")
    close, volume = frame["close"], frame["volume"]
    as_of = frame["date"].iloc[-1]
    expected = len(pd.bdate_range(frame["date"].iloc[0], as_of))
    missing_fraction = max(0.0, 1 - len(frame) / max(expected, 1))
    stale = bool(as_of < pd.Timestamp(reference_date).normalize() - pd.Timedelta(days=policy.stale_after_days))
    volume_present = bool(volume.tail(20).sum() > 0)
    traded_value = float((close * volume).tail(60).mean())
    tech = _technical_features(ticker, close, volume) if len(close) >= 60 else None
    vol20, vol60 = _volatility(close, 20), _volatility(close, 60)
    atr_pct, drawdown = _atr_percent(frame), _max_drawdown(close)
    stability = _trend_stability(close, vol60, drawdown) if np.isfinite(vol60) else np.nan
    risk_score, risk_level = _risk(vol60, drawdown, atr_pct) if all(np.isfinite(x) for x in [vol60, drawdown, atr_pct]) else (np.nan, "Unknown")
    reasons = []
    if len(close) < policy.minimum_history: reasons.append("insufficient_history")
    if missing_fraction > policy.maximum_missing_fraction: reasons.append("missing_data_exceeds_tolerance")
    if stale: reasons.append("stale_latest_price")
    if not volume_present: reasons.append("missing_recent_volume")
    if tech is None: reasons.append("technical_history_insufficient")
    freshness = 20 + (0 if stale else 20)
    history = min(len(close) / 252, 1) * 20
    missing = max(0, 1 - missing_fraction) * 20
    volume_score = 10 if volume_present else 0
    technical = 0 if tech is None else tech["technical_score"] * 10
    liquidity = min(np.log10(max(traded_value, 1)) * 2, 20)
    score = float(freshness + history + missing + volume_score + technical + liquidity)
    confidence = float((freshness + history + missing + volume_score) / 90)
    row = {**metadata, "ticker": ticker, "yahoo_ticker": ticker,
           "name": metadata.get("display_name"), "as_of_date": as_of.date().isoformat(),
           "universe_memberships": "|".join(sorted(memberships)), "latest_close": float(close.iloc[-1]),
           "latest_price_date": as_of.date().isoformat(), "latest_close_present": True,
           "valid_bar_count": int(len(close)), "missing_close_pct": float(missing_fraction),
           "stale_latest_price": stale, "volume_present": volume_present,
           "avg_traded_value_60d": traded_value, "volatility_20d": vol20,
           "volatility_60d": vol60, "atr_percent": atr_pct, "max_drawdown_1y": drawdown,
           "trend_stability_score": stability, "risk_score": risk_score, "risk_level": risk_level,
           "data_quality_pass": not reasons, "data_quality_confidence": confidence,
           "freshness_component": freshness, "history_component": history,
           "missing_data_component": missing, "volume_component": volume_score,
           "technical_component": technical, "liquidity_component": liquidity,
           "scanner_score": score, "global_score": score, "exclusion_state": bool(reasons),
           "rejection_reason": "|".join(sorted(reasons)), "terminal_state": "rejected" if reasons else "scored"}
    row.update(tech or {key: np.nan for key in ["ema20", "ema50", "rsi14", "macd", "macd_signal", "technical_score"]})
    if tech is None:
        row.update({key: False for key in ["price_above_ema20", "ema20_above_ema50", "rsi_in_range", "macd_above_signal", "volume_above_20d_average"]})
    return row


def rank_features(features, memberships, top_n=15):
    scored = features[features["terminal_state"].eq("scored")].copy()
    scored = scored.sort_values(["scanner_score", "avg_traded_value_60d", "ticker"], ascending=[False, False, True], kind="stable").reset_index(drop=True)
    scored["global_rank"] = range(1, len(scored) + 1)
    scored["rank"] = scored["global_rank"]
    scored["selected_for_research"] = scored["global_rank"].le(top_n)
    expanded = scored.merge(memberships[["ticker", "universe_name"]], on="ticker", how="left")
    expanded = expanded.sort_values(["universe_name", "scanner_score", "avg_traded_value_60d", "ticker"], ascending=[True, False, False, True], kind="stable")
    expanded["universe_rank"] = expanded.groupby("universe_name", dropna=False).cumcount() + 1
    per_ticker = expanded.groupby("ticker", sort=False)["universe_rank"].apply(lambda s: "|".join(map(str, s))).to_dict()
    scored["universe_ranks"] = scored["ticker"].map(per_ticker)
    return scored, scored[scored["selected_for_research"]].copy()


def ranking_movement(current, previous):
    old = previous.set_index("ticker") if previous is not None and not previous.empty else pd.DataFrame()
    rows = []
    for row in current.to_dict("records"):
        ticker = row["ticker"]
        if old.empty or ticker not in old.index:
            previous_rank, previous_score, state = np.nan, np.nan, "new"
        else:
            prior = old.loc[ticker]
            previous_rank, previous_score = prior["global_rank"], prior["scanner_score"]
            state = "improved" if previous_rank > row["global_rank"] else "declined" if previous_rank < row["global_rank"] else "unchanged"
        rows.append({"ticker": ticker, "previous_rank": previous_rank, "current_rank": row["global_rank"],
                     "rank_delta": np.nan if pd.isna(previous_rank) else float(previous_rank - row["global_rank"]),
                     "previous_score": previous_score, "current_score": row["scanner_score"],
                     "score_delta": np.nan if pd.isna(previous_score) else float(row["scanner_score"] - previous_score),
                     "movement_state": state})
    current_tickers = set(current["ticker"])
    if not old.empty:
        for ticker, prior in old.iterrows():
            if ticker not in current_tickers:
                rows.append({"ticker": ticker, "previous_rank": prior["global_rank"], "current_rank": np.nan,
                             "rank_delta": np.nan, "previous_score": prior["scanner_score"], "current_score": np.nan,
                             "score_delta": np.nan, "movement_state": "removed"})
    return pd.DataFrame(rows).sort_values(["movement_state", "ticker"], kind="stable").reset_index(drop=True)


def add_persistence(rankings, history, top_n=15):
    def selected(value):
        return value is True or str(value).strip().lower() in {"1", "true", "yes", "y"}
    output = rankings.copy()
    rows = []
    for current in output.to_dict("records"):
        ticker = current["ticker"]
        observations = []
        for snapshot in history:
            match = snapshot[snapshot["ticker"].astype(str).eq(ticker)] if "ticker" in snapshot else pd.DataFrame()
            if not match.empty: observations.append(match.iloc[0].to_dict())
        observations.append(current)
        selected_ranks = [float(row["global_rank"]) for row in observations
                          if selected(row.get("selected_for_research", False)) and pd.notna(row.get("global_rank"))]
        days = len(selected_ranks)
        consecutive = 0
        for row in reversed(observations):
            if not selected(row.get("selected_for_research", False)): break
            consecutive += 1
        highest = min(selected_ranks) if selected_ranks else np.nan
        average = float(np.mean(selected_ranks)) if selected_ranks else np.nan
        volatility = float(np.std(selected_ranks)) if selected_ranks else np.nan
        swings = np.abs(np.diff(selected_ranks)) if len(selected_ranks) > 1 else np.array([])
        swing_frequency = float((swings > 5).mean()) if len(swings) else 0.0
        time_component = min(days / 20, 1) * 30
        consecutive_component = min(consecutive / 10, 1) * 25
        rank_component = 0 if pd.isna(average) else (1 - min(max(average - 1, 0) / max(float(top_n), 1), 1)) * 20
        consistency = (1 - min((10 if pd.isna(volatility) else volatility) / 10, 1)) * 15
        swing_component = (1 - min(swing_frequency / .5, 1)) * 10
        score = float(max(0, min(time_component + consecutive_component + rank_component + consistency + swing_component, 100)))
        level = "New" if score < 20 else "Emerging" if score < 40 else "Established" if score < 65 else "Persistent" if score < 85 else "Core Candidate"
        current.update({"days_in_top_list": days, "consecutive_days_seen": consecutive,
                        "highest_rank_seen": highest, "average_rank": average,
                        "rank_volatility": volatility, "persistence_score": score,
                        "persistence_level": level})
        rows.append(current)
    return pd.DataFrame(rows)


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


class FeatureGenerationStore:
    def __init__(self, root):
        self.root, self.generations, self.pointer = Path(root), Path(root) / "generations", Path(root) / "current_generation.json"

    def current_generation(self):
        return None if not self.pointer.exists() else json.loads(self.pointer.read_text(encoding="utf-8"))["generation_id"]

    def read_rankings(self):
        generation = self.current_generation()
        path = self.generations / generation / "latest_rankings.csv" if generation else None
        return pd.read_csv(path) if path and path.exists() else pd.DataFrame()

    def ranking_history(self):
        frames = []
        if not self.generations.exists(): return frames
        for path in sorted(self.generations.glob("*/latest_rankings.csv"), key=lambda item: item.parent.stat().st_mtime):
            try: frames.append(pd.read_csv(path))
            except Exception: continue
        return frames

    def publish(self, frames, manifest, generation_id=None, failure_hook=None):
        generation_id = generation_id or uuid4().hex
        staging, final = self.root / f".staging-{generation_id}", self.generations / generation_id
        if staging.exists() or final.exists(): raise ValueError(f"Generation already exists: {generation_id}")
        staging.mkdir(parents=True)
        try:
            for name, frame in frames.items(): frame.to_csv(staging / name, index=False)
            if failure_hook: failure_hook("after_csv_writes", staging)
            manifest = dict(manifest)
            manifest["hashes"] = {name: _hash(staging / name) for name in sorted(frames)}
            (staging / "scanner_generation_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            if failure_hook: failure_hook("before_pointer_swap", staging)
            self.generations.mkdir(parents=True, exist_ok=True)
            staging.replace(final)
            pointer_tmp = self.root / f".pointer-{generation_id}.tmp"
            pointer_tmp.write_text(json.dumps({"generation_id": generation_id}), encoding="utf-8")
            os.replace(pointer_tmp, self.pointer)
            return final
        except Exception:
            if staging.exists(): shutil.rmtree(staging)
            raise


def produce_feature_generation(bar_store_dir="data/global_scanner/bar_store", feature_store_dir="data/global_scanner/feature_store", universe_dir="data/universes", generation="current", dry_run=False, policy=FeaturePolicy(), generation_id=None, failure_hook=None):
    started_clock, started = time.perf_counter(), pd.Timestamp.now(tz="UTC")
    bar_store = ScannerBarStore(bar_store_dir)
    acquisition_id = bar_store.current_generation() if generation == "current" else generation
    if not acquisition_id: raise FileNotFoundError("No active scanner v2 bar generation")
    pinned_bars = Path(bar_store_dir) / "generations" / acquisition_id / "bars"
    if not pinned_bars.exists(): raise FileNotFoundError(f"Missing acquisition generation: {acquisition_id}")
    universe, memberships = load_canonical_universe(universe_dir, observed_at=started)
    enabled = universe[universe["enabled"].astype(bool)].sort_values("ticker", kind="stable")
    membership_map = memberships.groupby("ticker")["universe_name"].apply(list).to_dict()
    reference_dates = []
    for ticker in enabled["ticker"]:
        path = pinned_bars / bar_store.path_for(ticker).name
        if path.exists():
            dates = pd.read_csv(path, usecols=["date"])["date"]
            if not dates.empty: reference_dates.append(pd.to_datetime(dates.iloc[-1]))
    reference = max(reference_dates) if reference_dates else started.tz_localize(None).normalize()
    rows = []
    for metadata in enabled.to_dict("records"):
        ticker = metadata["ticker"]
        path = pinned_bars / bar_store.path_for(ticker).name
        try:
            row = calculate_ticker_features(ticker, pd.read_csv(path), metadata, membership_map.get(ticker, []), reference, policy)
        except Exception as exc:
            row = {**metadata, "ticker": ticker, "yahoo_ticker": ticker, "name": metadata.get("display_name"),
                   "as_of_date": pd.NaT, "universe_memberships": "|".join(sorted(membership_map.get(ticker, []))),
                   "terminal_state": "failed", "exclusion_state": True, "rejection_reason": f"feature_error:{type(exc).__name__}:{exc}",
                   "data_quality_pass": False, "data_quality_confidence": 0.0, "scanner_score": np.nan, "global_score": np.nan}
        rows.append(row)
    features = pd.DataFrame(rows).sort_values("ticker", kind="stable").reset_index(drop=True)
    if features["ticker"].duplicated().any() or not set(features["terminal_state"]).issubset(TERMINAL_STATES): raise ValueError("Invalid terminal-state reconciliation")
    rankings, candidates = rank_features(features, memberships, policy.top_n)
    store = FeatureGenerationStore(feature_store_dir)
    rankings = add_persistence(rankings, store.ranking_history(), policy.top_n)
    movement = ranking_movement(rankings, store.read_rankings())
    movement_by_ticker = movement[movement["movement_state"].ne("removed")].set_index("ticker")
    for column in ["previous_rank", "current_rank", "rank_delta", "previous_score", "current_score", "score_delta", "movement_state"]:
        rankings[column] = rankings["ticker"].map(movement_by_ticker[column])
    rankings["rank_change"] = rankings["rank_delta"]
    rankings["new_entry"] = rankings["movement_state"].eq("new")
    candidates = rankings[rankings["selected_for_research"]].copy()
    rejected = features[features["terminal_state"].ne("scored")].copy()
    if not COMPARISON_FIELDS.issubset(rankings.columns): raise ValueError(f"Comparison fields missing: {sorted(COMPARISON_FIELDS - set(rankings))}")
    ended = pd.Timestamp.now(tz="UTC")
    states = features["terminal_state"].value_counts().to_dict()
    manifest = {"generation_id": generation_id or uuid4().hex, "acquisition_generation": acquisition_id,
                "status": "complete", "started_at": started.isoformat(), "ended_at": ended.isoformat(),
                "duration_seconds": time.perf_counter() - started_clock, "eligible_assets": len(enabled),
                "scored_assets": int(states.get("scored", 0)), "rejected_assets": int(states.get("rejected", 0)),
                "failed_assets": int(states.get("failed", 0)), "candidates": len(candidates),
                "universe_counts": memberships[memberships["ticker"].isin(set(enabled["ticker"]))]["universe_name"].value_counts().sort_index().to_dict(),
                "feature_schema_version": FEATURE_SCHEMA_VERSION, "scoring_version": SCORING_VERSION}
    if manifest["eligible_assets"] != manifest["scored_assets"] + manifest["rejected_assets"] + manifest["failed_assets"]: raise ValueError("Manifest terminal counts do not reconcile")
    if dry_run:
        return {"dry_run": True, "writes": 0, "manifest": manifest, "features": features, "rankings": rankings, "candidates": candidates, "rejected": rejected, "movement": movement}
    manifest_id = manifest["generation_id"]
    final = store.publish({"scanner_features.csv": features, "latest_rankings.csv": rankings,
                           "selected_candidates.csv": candidates, "rejected_assets.csv": rejected,
                           "ranking_movement.csv": movement}, manifest, manifest_id, failure_hook)
    return {"dry_run": False, "writes": 6, "path": str(final), "manifest": manifest}


def parser():
    command = argparse.ArgumentParser(description="Canonical Global Scanner v2 feature producer")
    command.add_argument("--generation", default="current")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--bar-store-dir", default="data/global_scanner/bar_store")
    command.add_argument("--feature-store-dir", default="data/global_scanner/feature_store")
    command.add_argument("--universe-dir", default="data/universes")
    command.add_argument("--top-n", type=int, default=15)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    result = produce_feature_generation(args.bar_store_dir, args.feature_store_dir, args.universe_dir,
                                        args.generation, args.dry_run, FeaturePolicy(top_n=args.top_n))
    print(json.dumps(result["manifest"], indent=2, default=str))
    print(f"dry_run={str(args.dry_run).lower()} writes={result['writes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
