from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.global_scanner import calculate_quality as legacy_quality
from research.scanner_v2.bar_store import ScannerBarStore
from research.scanner_v2.features import (COMPARISON_FIELDS, FeatureGenerationStore,
    FeaturePolicy, calculate_ticker_features, produce_feature_generation,
    ranking_movement)
from research.scanner_v2.generation import GENERATION_ARTIFACTS


def check(value, message, issues):
    print(("PASS" if value else "FAIL") + f": {message}")
    if not value: issues.append(message)


def bars(ticker, periods=260, offset=0):
    dates = pd.bdate_range("2025-01-01", periods=periods)
    close = 80 + offset + np.arange(periods) * .08 + np.sin(np.arange(periods) / 9)
    return pd.DataFrame({"ticker": ticker, "date": dates, "open": close - .2,
        "high": close + .6, "low": close - .7, "close": close,
        "volume": 1_000_000 + (np.arange(periods) % 23) * 10_000,
        "source": "fixture", "fetched_at": "2026-01-01T00:00:00Z", "adjusted": True})


def metadata(ticker):
    return {"ticker": ticker, "display_name": ticker, "asset_type": "Equity",
        "exchange": "NASDAQ", "country": "United States", "currency": "USD",
        "sector": "Technology", "industry": "Software", "universe_source": "fixture",
        "enabled": True, "priority": 1, "max_position_weight": np.nan,
        "first_seen_at": "2025-01-01", "last_verified_at": "2026-01-01"}


def write_universe(path, count):
    path.mkdir(parents=True, exist_ok=True)
    rows = [{**metadata(f"T{i:04d}"), "universe_name": "fixture"} for i in range(count)]
    pd.DataFrame(rows).to_csv(path / "fixture.csv", index=False)


def main():
    issues, base = [], ROOT / ".scanner_v2_phase3_fixture"
    if base.exists(): shutil.rmtree(base)
    try:
        one = bars("AAPL")
        row = calculate_ticker_features("AAPL", one, metadata("AAPL"), ["fixture"], one["date"].iloc[-1])
        prices = one.set_index("date")[["close"]].rename(columns={"close": "AAPL"})
        volumes = one.set_index("date")[["volume"]].rename(columns={"volume": "AAPL"})
        highs = one.set_index("date")[["high"]].rename(columns={"high": "AAPL"})
        lows = one.set_index("date")[["low"]].rename(columns={"low": "AAPL"})
        legacy_meta = pd.DataFrame([{"yahoo_ticker": "AAPL"}])
        legacy = legacy_quality(legacy_meta, prices, volumes, highs, lows).iloc[0]
        parity = ["technical_score", "volatility_20d", "volatility_60d", "atr_percent",
                  "trend_stability_score", "scanner_score"]
        check(all(np.isclose(row[key], legacy[key], equal_nan=True) for key in parity), "golden legacy indicators and score retain parity", issues)
        check(row["technical_score"] == sum(row[key] for key in ["price_above_ema20", "ema20_above_ema50", "rsi_in_range", "macd_above_signal", "volume_above_20d_average"]), "technical score is the deterministic five-indicator count", issues)
        check(0 <= row["data_quality_confidence"] <= 1 and row["risk_level"] in {"Very Low", "Low", "Medium", "High", "Very High"}, "confidence and legacy risk labels are bounded", issues)

        old = pd.DataFrame({"ticker": ["A", "B", "D"], "global_rank": [2, 1, 3], "scanner_score": [9., 10., 8.]})
        new = pd.DataFrame({"ticker": ["A", "B", "C"], "global_rank": [1, 2, 3], "scanner_score": [11., 9., 8.]})
        movement = ranking_movement(new, old)
        check(set(movement["movement_state"]) == {"improved", "declined", "new", "removed"} and movement["ticker"].is_unique, "ranking movement covers terminal movement states with deltas", issues)

        for count in (500, 1500):
            universe_dir, bar_root, feature_root = base / str(count) / "universes", base / str(count) / "bars", base / str(count) / "features"
            write_universe(universe_dir, count)
            store = ScannerBarStore(bar_root)
            store.commit({f"T{i:04d}": bars(f"T{i:04d}", offset=i % 31) for i in range(count)}, generation_id="acquisition")
            first = produce_feature_generation(bar_root, feature_root, universe_dir, dry_run=True, policy=FeaturePolicy(top_n=25))
            check(len(first["features"]) == count and first["writes"] == 0 and first["manifest"]["eligible_assets"] == count, f"{count}-asset per-ticker dry-run reconciles and writes nothing", issues)
            ordered = first["rankings"][["ticker", "global_rank"]].copy()
            reranked = first["features"].sample(frac=1, random_state=9).sort_values(["scanner_score", "avg_traded_value_60d", "ticker"], ascending=[False, False, True], kind="stable")
            reranked["global_rank"] = range(1, len(reranked) + 1)
            check(ordered.equals(reranked[["ticker", "global_rank"]].reset_index(drop=True)), f"{count}-asset ranking is completion-order independent", issues)
            if count == 500:
                published = produce_feature_generation(bar_root, feature_root, universe_dir, generation_id="good")
                pointer_before = (feature_root / "current_generation.json").read_bytes()
                def fail(stage, _path):
                    if stage == "before_pointer_swap": raise RuntimeError("fixture failure")
                try:
                    produce_feature_generation(bar_root, feature_root, universe_dir, generation_id="bad", failure_hook=fail)
                    rollback = False
                except RuntimeError: rollback = True
                check(rollback and pointer_before == (feature_root / "current_generation.json").read_bytes() and FeatureGenerationStore(feature_root).current_generation() == "good", "failed generation preserves the previous active generation", issues)
                manifest = json.loads((Path(published["path"]) / "scanner_generation_manifest.json").read_text())
                check(manifest["eligible_assets"] == manifest["scored_assets"] + manifest["rejected_assets"] + manifest["failed_assets"] and set(manifest["hashes"]) == set(GENERATION_ARTIFACTS), "manifest terminal states and artifact hashes reconcile", issues)
                rankings = pd.read_csv(Path(published["path"]) / "latest_rankings.csv")
                candidates = pd.read_csv(Path(published["path"]) / "selected_candidates.csv")
                check(list(rankings.columns) == list(candidates.columns) and COMPARISON_FIELDS.issubset(rankings.columns), "candidate schema matches rankings and canonical features drive comparison", issues)

        scanner_source = (ROOT / "research/scanner_v2/features.py").read_text(encoding="utf-8")
        check("web_dashboard" not in scanner_source and "research.global_scanner" not in scanner_source, "producer has no dashboard or legacy calculation dependency", issues)
    finally:
        if base.exists(): shutil.rmtree(base)
    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
