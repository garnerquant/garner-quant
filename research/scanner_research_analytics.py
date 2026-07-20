"""Deterministic analytics over immutable Scanner research observations."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


NUMERIC_FACTORS = (
    "trend_stability_score", "trend_strength_pct", "return_20d_pct",
    "return_60d_pct", "relative_strength_percentile", "atr_percent",
    "liquidity_percentile", "avg_traded_value_60d", "persistence_score",
    "data_quality_confidence", "risk_score", "scanner_score",
)
CATEGORICAL_FACTORS = (
    "trend_regime", "momentum_regime", "volatility_regime", "liquidity_bucket",
    "quality_bucket", "risk_level", "sector", "country",
)


def forward_return_columns(frame: pd.DataFrame) -> list[tuple[int, str]]:
    values = []
    for column in frame.columns:
        if column.startswith("forward_return_") and column.endswith("d_pct"):
            text = column.removeprefix("forward_return_").removesuffix("d_pct")
            if text.isdigit():
                values.append((int(text), column))
    return sorted(values)


def outcome_metrics(values, horizon: int) -> dict:
    returns = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    gains = returns[returns > 0]
    losses = returns[returns < 0]
    if returns.empty:
        return {
            "observations": len(pd.Series(values)), "available_outcomes": 0,
            "average_return_pct": np.nan, "median_return_pct": np.nan,
            "hit_rate_pct": np.nan, "average_gain_pct": np.nan,
            "average_loss_pct": np.nan, "max_drawdown_pct": np.nan,
            "sharpe": np.nan, "win_pct": np.nan, "loss_pct": np.nan,
        }
    decimal = returns / 100
    wealth = (1 + decimal).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    standard_deviation = float(decimal.std(ddof=1)) if len(decimal) > 1 else np.nan
    sharpe = (
        float(decimal.mean() / standard_deviation * math.sqrt(252 / horizon))
        if pd.notna(standard_deviation) and standard_deviation > 0 else np.nan
    )
    wins = float((returns > 0).mean() * 100)
    return {
        "observations": len(pd.Series(values)),
        "available_outcomes": len(returns),
        "average_return_pct": float(returns.mean()),
        "median_return_pct": float(returns.median()),
        "hit_rate_pct": wins,
        "average_gain_pct": float(gains.mean()) if not gains.empty else np.nan,
        "average_loss_pct": float(losses.mean()) if not losses.empty else np.nan,
        "max_drawdown_pct": float(drawdown.min() * 100),
        "sharpe": sharpe,
        "win_pct": wins,
        "loss_pct": float((returns < 0).mean() * 100),
    }


def _group_report(frame: pd.DataFrame, group_type: str, column: str) -> pd.DataFrame:
    columns = ["group_type", "group_value", "horizon_days"] + list(outcome_metrics([], 1))
    if frame.empty or column not in frame:
        return pd.DataFrame(columns=columns)
    rows = []
    values = frame[column].fillna("Unknown").astype(str)
    for value, group in frame.groupby(values, sort=True):
        for horizon, outcome in forward_return_columns(frame):
            rows.append({
                "group_type": group_type,
                "group_value": value,
                "horizon_days": horizon,
                **outcome_metrics(group[outcome], horizon),
            })
    return pd.DataFrame(rows, columns=columns)


def prepare_research_groups(history: pd.DataFrame) -> pd.DataFrame:
    result = history.copy(deep=True)
    rank = pd.to_numeric(result.get("global_rank"), errors="coerce")
    scored = pd.to_numeric(result.get("scored_assets"), errors="coerce") if "scored_assets" in result else pd.Series(np.nan, index=result.index)
    if scored.isna().all() and "global_rank" in result:
        scored = result.groupby("generation_id")["global_rank"].transform("count")
    result["rank_decile"] = np.ceil(rank / scored.replace(0, np.nan) * 10).clip(1, 10).astype("Int64")
    persistence = (
        pd.to_numeric(result["persistence_score"], errors="coerce")
        if "persistence_score" in result
        else pd.Series(np.nan, index=result.index, dtype=float)
    )
    result["persistence_score_bucket"] = pd.cut(
        persistence,
        bins=[-np.inf, 20, 40, 65, 85, np.inf],
        labels=["New", "Emerging", "Established", "Persistent", "Core Candidate"],
        right=False,
    )
    return result


def build_research_reports(history: pd.DataFrame) -> dict[str, pd.DataFrame]:
    data = prepare_research_groups(history)
    ranking = _group_report(data, "rank_decile", "rank_decile")
    sector = _group_report(data, "sector", "sector")
    country = _group_report(data, "country", "country")
    buckets = pd.concat([
        _group_report(data, "liquidity_bucket", "liquidity_bucket"),
        _group_report(data, "quality_bucket", "quality_bucket"),
        _group_report(data, "persistence_score", "persistence_score_bucket"),
    ], ignore_index=True)
    regimes = pd.concat([
        _group_report(data, "volatility_regime", "volatility_regime"),
        _group_report(data, "trend_regime", "trend_regime"),
        _group_report(data, "momentum_regime", "momentum_regime"),
    ], ignore_index=True)
    candidates = _group_report(data, "candidate_status", "candidate_status")
    return {
        "ranking_report.csv": ranking,
        "sector_report.csv": sector,
        "country_report.csv": country,
        "bucket_report.csv": buckets,
        "regime_report.csv": regimes,
        "candidate_report.csv": candidates,
    }


def _numeric_predictive_statistic(feature, outcome) -> tuple[int, float]:
    pair = pd.DataFrame({
        "feature": pd.to_numeric(feature, errors="coerce"),
        "outcome": pd.to_numeric(outcome, errors="coerce"),
    }).dropna()
    if len(pair) < 3 or pair["feature"].nunique() < 2 or pair["outcome"].nunique() < 2:
        return len(pair), np.nan
    statistic = pair["feature"].rank(method="average").corr(
        pair["outcome"].rank(method="average"), method="pearson"
    )
    return len(pair), float(statistic)


def _categorical_predictive_statistic(feature, outcome) -> tuple[int, float]:
    pair = pd.DataFrame({"feature": feature, "outcome": pd.to_numeric(outcome, errors="coerce")}).dropna()
    if len(pair) < 3 or pair["feature"].nunique() < 2:
        return len(pair), np.nan
    mean = pair["outcome"].mean()
    total = float(((pair["outcome"] - mean) ** 2).sum())
    if total <= 0:
        return len(pair), np.nan
    between = 0.0
    for _, group in pair.groupby(pair["feature"].astype(str), sort=True):
        between += len(group) * float((group["outcome"].mean() - mean) ** 2)
    return len(pair), float(between / total)


def evaluate_factors(history: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon, outcome in forward_return_columns(history):
        for factor in NUMERIC_FACTORS:
            if factor not in history:
                continue
            observations, statistic = _numeric_predictive_statistic(history[factor], history[outcome])
            rows.append({
                "factor": factor, "factor_type": "numeric_spearman",
                "horizon_days": horizon, "observations": observations,
                "predictive_statistic": statistic,
                "absolute_predictive_statistic": abs(statistic) if pd.notna(statistic) else np.nan,
                "direction": "positive" if pd.notna(statistic) and statistic > 0 else "negative" if pd.notna(statistic) and statistic < 0 else "none",
            })
        for factor in CATEGORICAL_FACTORS:
            if factor not in history:
                continue
            observations, statistic = _categorical_predictive_statistic(history[factor], history[outcome])
            rows.append({
                "factor": factor, "factor_type": "categorical_eta_squared",
                "horizon_days": horizon, "observations": observations,
                "predictive_statistic": statistic,
                "absolute_predictive_statistic": statistic,
                "direction": "group_effect" if pd.notna(statistic) else "none",
            })
    return pd.DataFrame(rows).sort_values(
        ["horizon_days", "absolute_predictive_statistic", "factor"],
        ascending=[True, False, True], kind="stable", na_position="last",
    ).reset_index(drop=True)
