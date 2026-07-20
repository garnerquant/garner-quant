"""Build immutable research observations from ScannerGeneration history."""

from __future__ import annotations

import pandas as pd

from research.scanner_v2.generation import ScannerGeneration


HISTORY_KEY = ["generation_id", "ticker", "as_of_date"]


def generation_observations(generation: ScannerGeneration) -> pd.DataFrame:
    """Flatten one published generation without deriving scanner intelligence."""
    generation.validate()
    features = generation.features.copy(deep=True)
    rankings = generation.rankings.copy(deep=True)
    movement = generation.movement.copy(deep=True)
    portfolio_fit = generation.portfolio_fit.copy(deep=True)
    if features["ticker"].duplicated().any():
        raise ValueError("Scanner features must contain one row per ticker")
    if not rankings.empty and rankings["ticker"].duplicated().any():
        raise ValueError("Scanner rankings must contain one row per ticker")

    ranking_columns = ["ticker"] + [
        column for column in rankings.columns
        if column != "ticker" and column not in features.columns
    ]
    observations = features.merge(rankings[ranking_columns], on="ticker", how="left", validate="one_to_one")

    movement_columns = ["ticker"] + [
        column for column in movement.columns
        if column != "ticker" and column not in observations.columns
    ]
    if not movement.empty:
        current_movement = movement[movement["ticker"].isin(set(features["ticker"]))]
        observations = observations.merge(
            current_movement[movement_columns], on="ticker", how="left", validate="one_to_one"
        )
    fit_columns = ["ticker"] + [
        column for column in portfolio_fit.columns
        if column != "ticker" and column not in observations.columns
    ]
    observations = observations.merge(
        portfolio_fit[fit_columns], on="ticker", how="left", validate="one_to_one"
    )

    candidate_tickers = set(generation.candidates["ticker"].astype(str))
    observations["is_candidate"] = observations["ticker"].astype(str).isin(candidate_tickers)
    observations["candidate_status"] = observations["is_candidate"].map(
        {True: "Candidate", False: "Not Candidate"}
    )
    observations["generation_id"] = generation.generation_id
    observations["generation_ended_at"] = str(generation.manifest["ended_at"])
    observations["acquisition_generation"] = str(generation.manifest["acquisition_generation"])
    observations["feature_schema_version"] = str(generation.manifest["feature_schema_version"])
    observations["intelligence_schema_version"] = str(
        generation.manifest.get("intelligence_schema_version", "")
    )
    for field in ("eligible_assets", "scored_assets", "rejected_assets", "failed_assets", "candidates"):
        observations[field] = int(generation.manifest[field])
    if observations.duplicated(HISTORY_KEY).any():
        raise ValueError("Historical Scanner observations have duplicate keys")
    return observations.sort_values(["ticker", "as_of_date"], kind="stable").reset_index(drop=True)


def build_historical_dataset(generations) -> pd.DataFrame:
    """Stack complete generations in manifest-time order into research history."""
    items = list(generations)
    if not items:
        return pd.DataFrame(columns=HISTORY_KEY)
    ordered = sorted(
        items,
        key=lambda generation: (
            pd.to_datetime(generation.manifest["ended_at"], utc=True),
            generation.generation_id,
        ),
    )
    history = pd.concat(
        [generation_observations(generation) for generation in ordered],
        ignore_index=True,
        sort=False,
    )
    if history.duplicated(HISTORY_KEY).any():
        raise ValueError("Historical Scanner dataset has duplicate generation/ticker/as-of keys")
    return history.sort_values(
        ["generation_ended_at", "generation_id", "ticker"], kind="stable"
    ).reset_index(drop=True)
