"""Portfolio-context intelligence for canonical Scanner v2 candidates."""

from __future__ import annotations

import numpy as np
import pandas as pd


PORTFOLIO_FIT_COLUMNS = [
    "ticker", "portfolio_fit_status", "already_held", "sector_overlap_pct",
    "country_overlap_pct", "currency_overlap_pct", "asset_type_overlap_pct",
    "concentration_impact", "diversification_score", "explanation_text",
]


def _unavailable(candidates: pd.DataFrame, explanation: str) -> pd.DataFrame:
    rows = []
    for ticker in candidates.get("ticker", pd.Series(dtype=str)).astype(str):
        rows.append({
            "ticker": ticker,
            "portfolio_fit_status": "unavailable",
            "already_held": False,
            "sector_overlap_pct": np.nan,
            "country_overlap_pct": np.nan,
            "currency_overlap_pct": np.nan,
            "asset_type_overlap_pct": np.nan,
            "concentration_impact": "Unknown",
            "diversification_score": np.nan,
            "explanation_text": explanation,
        })
    return pd.DataFrame(rows, columns=PORTFOLIO_FIT_COLUMNS)


def build_portfolio_fit(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build candidate fit from canonical metadata and an optional valued holding set."""
    if candidates.empty:
        return pd.DataFrame(columns=PORTFOLIO_FIT_COLUMNS)
    if holdings is None or holdings.empty:
        return _unavailable(candidates, "Holdings snapshot unavailable; portfolio fit was not calculated.")
    if "ticker" not in holdings or "market_value" not in holdings:
        return _unavailable(candidates, "Holdings snapshot lacks ticker or market_value.")

    metadata_columns = [
        column for column in ["ticker", "sector", "country", "currency", "asset_type"]
        if column in features.columns
    ]
    portfolio = holdings.copy()
    portfolio["ticker"] = portfolio["ticker"].fillna("").astype(str)
    portfolio["_market_value"] = pd.to_numeric(portfolio["market_value"], errors="coerce").fillna(0.0)
    portfolio = portfolio[portfolio["ticker"].ne("") & portfolio["_market_value"].gt(0)].copy()
    if portfolio.empty or portfolio["_market_value"].sum() <= 0:
        return _unavailable(candidates, "Holdings snapshot has no positive market value.")
    metadata = features[metadata_columns].drop_duplicates("ticker", keep="first")
    for column in ["sector", "country", "currency", "asset_type"]:
        if column in portfolio.columns:
            portfolio = portfolio.drop(columns=[column])
    portfolio = portfolio.merge(metadata, on="ticker", how="left")
    portfolio["_weight"] = portfolio["_market_value"] / portfolio["_market_value"].sum()
    held = set(portfolio["ticker"])
    dimensions = ["sector", "country", "currency", "asset_type"]
    exposure = {}
    for dimension in dimensions:
        values = portfolio[dimension].fillna("Unknown").astype(str)
        exposure[dimension] = portfolio.groupby(values, sort=True)["_weight"].sum().to_dict()

    rows = []
    ordered = candidates.sort_values(["global_rank", "ticker"], kind="stable")
    for candidate in ordered.to_dict("records"):
        ticker = str(candidate["ticker"])
        overlaps = {}
        score = 3.0
        positives, cautions = [], []
        already_held = ticker in held
        if already_held:
            score -= 1.2
            cautions.append("Candidate is already held.")
        dominant = 0
        shared = 0
        for dimension in dimensions:
            value = str(candidate.get(dimension) or "Unknown")
            weight = float(exposure[dimension].get(value, 0.0))
            overlaps[dimension] = weight * 100
            if weight <= 0:
                score += 0.35
                positives.append(f"Adds {value} {dimension.replace('_', ' ')} diversification.")
            else:
                shared += 1
                if weight >= 0.35:
                    score -= 0.35
                    dominant += 1
                    cautions.append(f"Adds to concentrated {value} {dimension.replace('_', ' ')} exposure.")
                elif weight <= 0.15:
                    score += 0.10
        if already_held or dominant >= 3:
            impact = "High"
        elif shared >= 3 or dominant:
            impact = "Moderate"
        else:
            impact = "Low"
        explanation = " ".join((positives[:2] + cautions[:2]))
        if not explanation:
            explanation = "Candidate has broadly neutral overlap with current holdings."
        rows.append({
            "ticker": ticker,
            "portfolio_fit_status": "calculated",
            "already_held": already_held,
            "sector_overlap_pct": overlaps["sector"],
            "country_overlap_pct": overlaps["country"],
            "currency_overlap_pct": overlaps["currency"],
            "asset_type_overlap_pct": overlaps["asset_type"],
            "concentration_impact": impact,
            "diversification_score": float(max(1.0, min(5.0, score))),
            "explanation_text": explanation,
        })
    return pd.DataFrame(rows, columns=PORTFOLIO_FIT_COLUMNS)
