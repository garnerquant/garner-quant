from __future__ import annotations

import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.scanner_reader import ScannerDashboardReader  # noqa: E402
from research.scanner_v2.features import (  # noqa: E402
    FeatureGenerationStore,
    calculate_ticker_features,
    rank_features,
    ranking_movement,
)
from research.scanner_v2.generation import GENERATION_ARTIFACTS, ScannerGeneration  # noqa: E402
from research.scanner_v2.intelligence import enrich_feature_intelligence  # noqa: E402
from research.scanner_v2.portfolio_intelligence import build_portfolio_fit  # noqa: E402


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def bars(ticker, start, stop, volume):
    dates = pd.bdate_range("2025-07-01", periods=260)
    close = np.linspace(start, stop, len(dates))
    return pd.DataFrame({
        "ticker": ticker,
        "date": dates,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": volume,
        "source": "fixture",
        "fetched_at": "2026-07-20T08:00:00+00:00",
        "adjusted": True,
    })


def feature(ticker, sector, country, currency, start, stop, volume):
    metadata = {
        "ticker": ticker, "display_name": ticker, "asset_type": "equity",
        "exchange": "TEST", "country": country, "currency": currency,
        "sector": sector, "industry": "Fixture", "universe_source": "fixture",
        "enabled": True, "priority": 1, "max_position_weight": 0.1,
        "first_seen_at": "2026-01-01", "last_verified_at": "2026-07-20",
    }
    data = bars(ticker, start, stop, volume)
    return calculate_ticker_features(
        ticker, data, metadata, ["fixture"], data["date"].iloc[-1]
    )


def main():
    issues = []
    raw = pd.DataFrame([
        feature("AAA", "Technology", "US", "USD", 80, 160, 2_000_000),
        feature("BBB", "Technology", "US", "USD", 100, 125, 800_000),
        feature("CCC", "Utilities", "GB", "GBP", 120, 90, 100_000),
    ]).sort_values("ticker", kind="stable").reset_index(drop=True)
    original_scores = raw.set_index("ticker")["scanner_score"].copy()
    enriched = enrich_feature_intelligence(raw)
    memberships = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "universe_name": ["fixture", "fixture", "fixture"],
    })
    rankings, candidates = rank_features(enriched, memberships, top_n=2)

    check(original_scores.equals(enriched.set_index("ticker")["scanner_score"]),
          "intelligence enrichment does not change scanner scores", issues)
    required = {
        "trend_regime", "momentum_regime", "volatility_regime", "liquidity_bucket",
        "quality_bucket", "atr_percentile", "relative_strength_percentile",
        "rolling_volatility_percentile", "volume_percentile", "breakout_state",
        "mean_reversion_state", "percentile_52w", "moving_average_alignment",
    }
    check(required.issubset(enriched.columns), "canonical intelligence schema is present", issues)
    check(enriched["average_dollar_volume_60d"].isna().all(),
          "unavailable USD-normalized volume is not fabricated", issues)
    check(enriched["spread_estimate"].isna().all(), "unavailable spread is not fabricated", issues)
    check(set(enriched["liquidity_bucket"]) <= {"High Liquidity", "Medium Liquidity", "Low Liquidity"},
          "liquidity labels are deterministic", issues)

    tech = rankings[rankings["sector"].eq("Technology")].sort_values("global_rank")
    check(list(tech["sector_rank"]) == [1, 2], "sector ranks follow deterministic global order", issues)
    check(tech.iloc[0]["sector_percentile"] > tech.iloc[1]["sector_percentile"],
          "sector percentiles identify the stronger peer", issues)
    check({"country_rank", "country_percentile", "sector_candidate_rank",
           "sector_candidate_count", "sector_average_score"}.issubset(rankings.columns),
          "sector and country intelligence is published", issues)

    holdings = pd.DataFrame({"ticker": ["AAA"], "market_value": [10_000.0]})
    portfolio_fit = build_portfolio_fit(candidates, enriched, holdings)
    aaa_fit = portfolio_fit.loc[portfolio_fit["ticker"].eq("AAA")].iloc[0]
    check(len(portfolio_fit) == len(candidates), "portfolio fit has one row per candidate", issues)
    check(bool(aaa_fit["already_held"]) and aaa_fit["sector_overlap_pct"] == 100.0,
          "portfolio overlap is derived from canonical holdings metadata", issues)
    check(bool(aaa_fit["explanation_text"]), "portfolio fit publishes explanation text", issues)
    unavailable = build_portfolio_fit(candidates, enriched, None)
    check(unavailable["portfolio_fit_status"].eq("unavailable").all()
          and unavailable["diversification_score"].isna().all(),
          "missing holdings produce explicit unavailable intelligence", issues)

    movement = ranking_movement(rankings, pd.DataFrame())
    movement_map = movement.set_index("ticker")
    for column in ["rank_delta", "movement_state"]:
        rankings[column] = rankings["ticker"].map(movement_map[column])
    candidates = rankings[rankings["selected_for_research"]].copy()
    portfolio_fit = build_portfolio_fit(candidates, enriched, holdings)
    rejected = enriched.iloc[0:0].copy()
    manifest = {
        "generation_id": "phase5-fixture", "acquisition_generation": "bars-fixture",
        "status": "complete", "started_at": "2026-07-20T08:00:00+00:00",
        "ended_at": "2026-07-20T08:01:00+00:00", "duration_seconds": 60.0,
        "eligible_assets": 3, "scored_assets": 3, "rejected_assets": 0,
        "failed_assets": 0, "candidates": len(candidates),
        "universe_counts": {"fixture": 3}, "feature_schema_version": "scanner-features-v2",
        "scoring_version": "legacy-scanner-score-v1",
        "intelligence_schema_version": "scanner-intelligence-v1",
        "portfolio_fit_assets": len(portfolio_fit),
    }
    generation = ScannerGeneration(
        "phase5-fixture", manifest, enriched, rankings, candidates,
        rejected, movement, portfolio_fit,
    )
    generation.validate()
    check(tuple(generation.frames()) == GENERATION_ARTIFACTS,
          "explicit generation bundle contains every canonical artifact", issues)

    scratch = Path(mkdtemp(prefix=".scanner-phase5-validation-", dir=ROOT))
    try:
        FeatureGenerationStore(scratch).publish(
            generation.frames(), manifest, generation_id="phase5-fixture"
        )
        loaded = ScannerDashboardReader(scratch).load_bundle()
        check(len(loaded.portfolio_fit) == len(candidates),
              "Dashboard Reader loads the Phase 5 bundle", issues)
        check(required.issubset(loaded.features.columns),
              "reader preserves enriched feature columns", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if issues:
        raise AssertionError("; ".join(issues))
    print("\nScanner v2 Phase 5 validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
