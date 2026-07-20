"""Explicit immutable-publication contract for a Scanner v2 generation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from research.scanner_v2.intelligence import (
    FEATURE_INTELLIGENCE_COLUMNS,
    PEER_INTELLIGENCE_COLUMNS,
)
from research.scanner_v2.portfolio_intelligence import PORTFOLIO_FIT_COLUMNS


GENERATION_ARTIFACTS = (
    "scanner_features.csv",
    "latest_rankings.csv",
    "selected_candidates.csv",
    "rejected_assets.csv",
    "ranking_movement.csv",
    "portfolio_fit.csv",
)


@dataclass(frozen=True)
class ScannerGeneration:
    """One complete in-memory bundle awaiting a single immutable publication."""

    generation_id: str
    manifest: Mapping
    features: pd.DataFrame
    rankings: pd.DataFrame
    candidates: pd.DataFrame
    rejections: pd.DataFrame
    movement: pd.DataFrame
    portfolio_fit: pd.DataFrame

    def frames(self) -> Mapping[str, pd.DataFrame]:
        return MappingProxyType({
            "scanner_features.csv": self.features.copy(deep=True),
            "latest_rankings.csv": self.rankings.copy(deep=True),
            "selected_candidates.csv": self.candidates.copy(deep=True),
            "rejected_assets.csv": self.rejections.copy(deep=True),
            "ranking_movement.csv": self.movement.copy(deep=True),
            "portfolio_fit.csv": self.portfolio_fit.copy(deep=True),
        })

    def validate(self) -> None:
        if str(self.manifest.get("generation_id")) != self.generation_id:
            raise ValueError("Generation and manifest identities do not match")
        if self.manifest.get("status") != "complete":
            raise ValueError("Only complete Scanner v2 generations may be published")
        expected = int(self.manifest["eligible_assets"])
        terminal = (
            int(self.manifest["scored_assets"])
            + int(self.manifest["rejected_assets"])
            + int(self.manifest["failed_assets"])
        )
        if expected != terminal or len(self.features) != expected:
            raise ValueError("Generation feature counts do not reconcile")
        if len(self.candidates) != int(self.manifest["candidates"]):
            raise ValueError("Generation candidate count does not reconcile")
        if len(self.portfolio_fit) != len(self.candidates):
            raise ValueError("Generation portfolio-fit rows must match candidates")
        if not FEATURE_INTELLIGENCE_COLUMNS.issubset(self.features.columns):
            raise ValueError("Generation feature intelligence schema is incomplete")
        if not PEER_INTELLIGENCE_COLUMNS.issubset(self.rankings.columns):
            raise ValueError("Generation peer intelligence schema is incomplete")
        if not set(PORTFOLIO_FIT_COLUMNS).issubset(self.portfolio_fit.columns):
            raise ValueError("Generation portfolio-fit schema is incomplete")
