"""Deterministic canonical intelligence derived from Scanner v2 features."""

from __future__ import annotations

import numpy as np
import pandas as pd


INTELLIGENCE_SCHEMA_VERSION = "scanner-intelligence-v1"
BAR_INTELLIGENCE_COLUMNS = (
    "return_20d_pct", "return_60d_pct", "return_252d_pct", "average_volume_60d",
    "high_52w", "low_52w", "percentile_52w", "distance_from_52w_high_pct",
    "distance_from_52w_low_pct", "distance_from_ema20_pct", "distance_from_ema50_pct",
    "moving_average_alignment", "trend_regime", "momentum_regime", "breakout_state",
    "mean_reversion_state", "bullish_trend", "bearish_trend",
)
FEATURE_INTELLIGENCE_COLUMNS = frozenset(BAR_INTELLIGENCE_COLUMNS) | {
    "relative_strength_percentile", "atr_percentile",
    "rolling_volatility_percentile", "volume_percentile", "liquidity_percentile",
    "average_daily_traded_value_60d", "traded_value_currency",
    "average_dollar_volume_60d", "spread_estimate", "volatility_regime",
    "quality_bucket", "liquidity_bucket", "tradability_classification",
    "trend_strength_pct",
}
PEER_INTELLIGENCE_COLUMNS = {
    "sector_rank", "sector_percentile", "sector_candidate_rank",
    "sector_candidate_count", "sector_average_score", "country_rank",
    "country_percentile",
}


def _period_return(close: pd.Series, periods: int) -> float:
    if len(close) <= periods or close.iloc[-periods - 1] == 0:
        return np.nan
    return float((close.iloc[-1] / close.iloc[-periods - 1] - 1) * 100)


def calculate_bar_intelligence(frame: pd.DataFrame) -> dict:
    """Calculate deterministic single-asset intelligence from canonical bars."""
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    latest = float(close.iloc[-1])
    window = close.tail(252)
    high_52w = float(window.max())
    low_52w = float(window.min())
    range_width = high_52w - low_52w
    percentile_52w = 100.0 if range_width == 0 else (latest - low_52w) / range_width * 100
    prior = close.iloc[:-1].tail(252)
    prior_high = float(prior.max()) if not prior.empty else np.nan
    prior_low = float(prior.min()) if not prior.empty else np.nan
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    distance_ema20 = (latest / ema20 - 1) * 100 if ema20 else np.nan
    distance_ema50 = (latest / ema50 - 1) * 100 if ema50 else np.nan

    if latest > ema20 > ema50:
        alignment, trend_regime = "Bullish", "Strong Trend"
    elif latest < ema20 < ema50:
        alignment, trend_regime = "Bearish", "Downtrend"
    else:
        alignment, trend_regime = "Mixed", "Weak Trend"

    return_20d = _period_return(close, 20)
    return_60d = _period_return(close, 60)
    return_252d = _period_return(close, 252)
    if pd.isna(return_20d):
        momentum_regime = "Unknown"
    elif return_20d >= 10:
        momentum_regime = "High Momentum"
    elif return_20d > 0:
        momentum_regime = "Positive Momentum"
    elif return_20d <= -10:
        momentum_regime = "Low Momentum"
    else:
        momentum_regime = "Negative Momentum"

    if pd.notna(prior_high) and latest > prior_high:
        breakout_state = "52-Week Breakout"
    elif pd.notna(prior_low) and latest < prior_low:
        breakout_state = "52-Week Breakdown"
    else:
        breakout_state = "Within 52-Week Range"

    if distance_ema20 >= 5:
        mean_reversion_state = "Extended Above EMA20"
    elif distance_ema20 <= -5:
        mean_reversion_state = "Extended Below EMA20"
    else:
        mean_reversion_state = "Near EMA20"

    return {
        "return_20d_pct": return_20d,
        "return_60d_pct": return_60d,
        "return_252d_pct": return_252d,
        "average_volume_60d": float(volume.tail(60).mean()),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "percentile_52w": float(percentile_52w),
        "distance_from_52w_high_pct": float((latest / high_52w - 1) * 100),
        "distance_from_52w_low_pct": float((latest / low_52w - 1) * 100),
        "distance_from_ema20_pct": float(distance_ema20),
        "distance_from_ema50_pct": float(distance_ema50),
        "moving_average_alignment": alignment,
        "trend_regime": trend_regime,
        "momentum_regime": momentum_regime,
        "breakout_state": breakout_state,
        "mean_reversion_state": mean_reversion_state,
        "bullish_trend": alignment == "Bullish",
        "bearish_trend": alignment == "Bearish",
    }


def _percentile(frame: pd.DataFrame, column: str, mask: pd.Series, group=None) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    values = pd.to_numeric(frame.loc[mask, column], errors="coerce")
    valid = values.notna()
    if group is None:
        result.loc[values.index[valid]] = values.loc[valid].rank(method="average", pct=True) * 100
    else:
        grouped = frame.loc[values.index[valid], group].fillna("Unknown").astype(str)
        result.loc[values.index[valid]] = values.loc[valid].groupby(grouped).rank(method="average", pct=True) * 100
    return result


def enrich_feature_intelligence(features: pd.DataFrame) -> pd.DataFrame:
    """Add cross-sectional labels and percentiles without changing scanner score."""
    result = features.copy()
    for column in BAR_INTELLIGENCE_COLUMNS:
        if column not in result:
            result[column] = np.nan
    scored = result["terminal_state"].eq("scored")
    result["relative_strength_percentile"] = _percentile(result, "return_60d_pct", scored)
    result["atr_percentile"] = _percentile(result, "atr_percent", scored)
    result["rolling_volatility_percentile"] = _percentile(result, "volatility_60d", scored)
    result["volume_percentile"] = _percentile(result, "average_volume_60d", scored)
    result["liquidity_percentile"] = _percentile(
        result, "avg_traded_value_60d", scored, group="currency"
    )
    result["average_daily_traded_value_60d"] = result["avg_traded_value_60d"]
    result["traded_value_currency"] = result.get("currency", "Unknown")
    result["average_dollar_volume_60d"] = np.nan
    result["spread_estimate"] = np.nan

    volatility = pd.to_numeric(result["volatility_60d"], errors="coerce")
    result["volatility_regime"] = np.select(
        [volatility.lt(20), volatility.lt(45), volatility.notna()],
        ["Stable", "Moderate Volatility", "Volatile"], default="Unknown",
    )
    confidence = pd.to_numeric(result["data_quality_confidence"], errors="coerce")
    result["quality_bucket"] = np.select(
        [confidence.ge(0.85), confidence.ge(0.65), confidence.notna()],
        ["High Quality", "Medium Quality", "Low Quality"], default="Unknown",
    )
    liquidity_pct = pd.to_numeric(result["liquidity_percentile"], errors="coerce")
    result["liquidity_bucket"] = np.select(
        [liquidity_pct.ge(75), liquidity_pct.ge(25), liquidity_pct.notna()],
        ["High Liquidity", "Medium Liquidity", "Low Liquidity"], default="Unknown",
    )
    result["tradability_classification"] = result["liquidity_bucket"].map({
        "High Liquidity": "Highly Tradable",
        "Medium Liquidity": "Tradable",
        "Low Liquidity": "Limited Tradability",
    }).fillna("Unknown")
    result["trend_strength_pct"] = pd.to_numeric(
        result["distance_from_ema50_pct"], errors="coerce"
    )
    if not FEATURE_INTELLIGENCE_COLUMNS.issubset(result.columns):
        raise ValueError("Canonical feature intelligence schema is incomplete")
    return result


def add_peer_intelligence(rankings: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic sector/country ranks to already globally ranked rows."""
    result = rankings.copy()
    for dimension in ("sector", "country"):
        groups = result[dimension].fillna("Unknown").astype(str)
        result[f"{dimension}_rank"] = result.groupby(groups, sort=False).cumcount() + 1
        counts = result.groupby(groups, sort=False)["ticker"].transform("count")
        result[f"{dimension}_percentile"] = (
            (counts - result[f"{dimension}_rank"] + 1) / counts * 100
        )
    sector_groups = result["sector"].fillna("Unknown").astype(str)
    result["sector_average_score"] = result.groupby(sector_groups, sort=False)["scanner_score"].transform("mean")
    selected = result["selected_for_research"].astype(bool)
    selected_rows = result.loc[selected].copy()
    selected_groups = selected_rows["sector"].fillna("Unknown").astype(str)
    selected_rows["sector_candidate_rank"] = selected_rows.groupby(selected_groups, sort=False).cumcount() + 1
    candidate_rank = selected_rows.set_index("ticker")["sector_candidate_rank"]
    candidate_counts = selected_rows.groupby(selected_groups, sort=False)["ticker"].count().to_dict()
    result["sector_candidate_rank"] = result["ticker"].map(candidate_rank)
    result["sector_candidate_count"] = sector_groups.map(candidate_counts).fillna(0).astype(int)
    if not PEER_INTELLIGENCE_COLUMNS.issubset(result.columns):
        raise ValueError("Canonical peer intelligence schema is incomplete")
    return result
