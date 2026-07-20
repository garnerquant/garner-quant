"""Read-only access to the active canonical Scanner v2 feature generation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


ARTIFACT_COLUMNS = {
    "scanner_features.csv": {
        "ticker", "as_of_date", "terminal_state", "scanner_score",
        "data_quality_pass", "rejection_reason",
    },
    "latest_rankings.csv": {
        "ticker", "display_name", "global_rank", "scanner_score",
        "selected_for_research", "movement_state", "rank_delta",
    },
    "selected_candidates.csv": {
        "ticker", "display_name", "global_rank", "scanner_score",
        "selected_for_research", "movement_state", "rank_delta",
    },
    "rejected_assets.csv": {
        "ticker", "terminal_state", "rejection_reason",
    },
    "ranking_movement.csv": {
        "ticker", "previous_rank", "current_rank", "rank_delta",
        "previous_score", "current_score", "score_delta", "movement_state",
    },
}
PORTFOLIO_FIT_COLUMNS = {
    "ticker", "portfolio_fit_status", "already_held", "sector_overlap_pct",
    "country_overlap_pct", "currency_overlap_pct", "asset_type_overlap_pct",
    "concentration_impact", "diversification_score", "explanation_text",
}
REQUIRED_MANIFEST_FIELDS = {
    "generation_id", "acquisition_generation", "status", "started_at",
    "ended_at", "eligible_assets", "scored_assets", "rejected_assets",
    "failed_assets", "candidates", "feature_schema_version",
    "scoring_version", "hashes",
}


class ScannerReaderError(RuntimeError):
    """A safe, classified Scanner v2 consumer-contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScannerGenerationMetadata:
    generation_id: str
    acquisition_generation: str
    status: str
    started_at: str
    ended_at: str
    eligible_assets: int
    scored_assets: int
    rejected_assets: int
    failed_assets: int
    candidate_count: int
    feature_schema_version: str
    scoring_version: str
    universe_counts: Mapping[str, int]


@dataclass(frozen=True)
class ScannerGenerationBundle:
    metadata: ScannerGenerationMetadata
    features: pd.DataFrame
    rankings: pd.DataFrame
    candidates: pd.DataFrame
    rejections: pd.DataFrame
    movement: pd.DataFrame
    portfolio_fit: pd.DataFrame

    def copy(self) -> "ScannerGenerationBundle":
        return ScannerGenerationBundle(
            metadata=self.metadata,
            features=self.features.copy(deep=True),
            rankings=self.rankings.copy(deep=True),
            candidates=self.candidates.copy(deep=True),
            rejections=self.rejections.copy(deep=True),
            movement=self.movement.copy(deep=True),
            portfolio_fit=self.portfolio_fit.copy(deep=True),
        )


class ScannerDashboardReader:
    """Validate and load one immutable, producer-published feature generation."""

    def __init__(self, feature_store_root: str | Path):
        self.root = Path(feature_store_root).resolve()
        self.pointer = self.root / "current_generation.json"
        self.generations = self.root / "generations"

    @staticmethod
    def _read_json(path: Path, code: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScannerReaderError(code, f"Invalid Scanner v2 JSON: {path.name}") from exc
        if not isinstance(payload, dict):
            raise ScannerReaderError(code, f"Scanner v2 JSON must be an object: {path.name}")
        return payload

    def _active_generation(self) -> tuple[str, Path]:
        if not self.pointer.exists():
            raise ScannerReaderError(
                "no_active_generation",
                "No completed Scanner v2 generation is currently published.",
            )
        pointer = self._read_json(self.pointer, "malformed_pointer")
        generation_id = str(pointer.get("generation_id", "")).strip()
        if not generation_id or Path(generation_id).name != generation_id:
            raise ScannerReaderError("malformed_pointer", "The Scanner v2 active pointer is invalid.")
        generation_path = (self.generations / generation_id).resolve()
        if generation_path.parent != self.generations.resolve():
            raise ScannerReaderError("malformed_pointer", "The Scanner v2 active pointer is unsafe.")
        if not generation_path.is_dir():
            raise ScannerReaderError(
                "missing_generation",
                "The active Scanner v2 pointer references a missing generation.",
            )
        return generation_id, generation_path

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _manifest(self, generation_id: str, generation_path: Path) -> dict[str, Any]:
        path = generation_path / "scanner_generation_manifest.json"
        if not path.is_file():
            raise ScannerReaderError("missing_artifact", "Scanner generation manifest is missing.")
        manifest = self._read_json(path, "malformed_manifest")
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest)
        if missing:
            raise ScannerReaderError(
                "malformed_manifest",
                f"Scanner manifest is missing required fields: {', '.join(sorted(missing))}.",
            )
        if str(manifest["generation_id"]) != generation_id:
            raise ScannerReaderError(
                "generation_mismatch",
                "Scanner pointer and manifest generation identities do not match.",
            )
        if manifest["status"] != "complete":
            raise ScannerReaderError(
                "incomplete_generation",
                "The active Scanner v2 generation is incomplete and was not loaded.",
            )
        try:
            counts = [int(manifest[name]) for name in (
                "eligible_assets", "scored_assets", "rejected_assets",
                "failed_assets", "candidates",
            )]
        except (TypeError, ValueError) as exc:
            raise ScannerReaderError("malformed_manifest", "Scanner manifest counts are invalid.") from exc
        if any(value < 0 for value in counts):
            raise ScannerReaderError("malformed_manifest", "Scanner manifest counts cannot be negative.")
        if counts[0] != counts[1] + counts[2] + counts[3]:
            raise ScannerReaderError("malformed_manifest", "Scanner manifest counts do not reconcile.")
        hashes = manifest["hashes"]
        if not isinstance(hashes, dict):
            raise ScannerReaderError("malformed_manifest", "Scanner manifest hashes are invalid.")
        return manifest

    def _load_artifact(
        self, generation_path: Path, manifest: Mapping[str, Any], filename: str
    ) -> pd.DataFrame:
        path = generation_path / filename
        if not path.is_file():
            raise ScannerReaderError("missing_artifact", f"Scanner artifact is missing: {filename}.")
        declared_hash = manifest["hashes"].get(filename)
        if not isinstance(declared_hash, str) or not declared_hash:
            raise ScannerReaderError("malformed_manifest", f"Scanner manifest has no hash for {filename}.")
        if self._sha256(path) != declared_hash:
            raise ScannerReaderError("hash_mismatch", f"Scanner artifact checksum failed: {filename}.")
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            raise ScannerReaderError("schema_mismatch", f"Scanner artifact is not valid CSV: {filename}.") from exc
        missing = ARTIFACT_COLUMNS[filename] - set(frame.columns)
        if missing:
            raise ScannerReaderError(
                "schema_mismatch",
                f"Scanner artifact {filename} is missing columns: {', '.join(sorted(missing))}.",
            )
        return frame

    @staticmethod
    def _metadata(manifest: Mapping[str, Any]) -> ScannerGenerationMetadata:
        universe_counts = manifest.get("universe_counts", {})
        if not isinstance(universe_counts, dict):
            universe_counts = {}
        return ScannerGenerationMetadata(
            generation_id=str(manifest["generation_id"]),
            acquisition_generation=str(manifest["acquisition_generation"]),
            status=str(manifest["status"]),
            started_at=str(manifest["started_at"]),
            ended_at=str(manifest["ended_at"]),
            eligible_assets=int(manifest["eligible_assets"]),
            scored_assets=int(manifest["scored_assets"]),
            rejected_assets=int(manifest["rejected_assets"]),
            failed_assets=int(manifest["failed_assets"]),
            candidate_count=int(manifest["candidates"]),
            feature_schema_version=str(manifest["feature_schema_version"]),
            scoring_version=str(manifest["scoring_version"]),
            universe_counts=MappingProxyType(dict(universe_counts)),
        )

    def load_bundle(self) -> ScannerGenerationBundle:
        generation_id, generation_path = self._active_generation()
        manifest = self._manifest(generation_id, generation_path)
        frames = {
            filename: self._load_artifact(generation_path, manifest, filename)
            for filename in ARTIFACT_COLUMNS
        }
        if "intelligence_schema_version" in manifest:
            portfolio_fit = self._load_artifact_with_columns(
                generation_path, manifest, "portfolio_fit.csv", PORTFOLIO_FIT_COLUMNS
            )
        else:
            portfolio_fit = pd.DataFrame(columns=sorted(PORTFOLIO_FIT_COLUMNS))
        features = frames["scanner_features.csv"]
        states = features["terminal_state"].value_counts().to_dict()
        expected = {
            "scored": int(manifest["scored_assets"]),
            "rejected": int(manifest["rejected_assets"]),
            "failed": int(manifest["failed_assets"]),
        }
        if any(int(states.get(state, 0)) != count for state, count in expected.items()):
            raise ScannerReaderError("count_mismatch", "Scanner feature rows do not reconcile with the manifest.")
        if len(features) != int(manifest["eligible_assets"]):
            raise ScannerReaderError("count_mismatch", "Scanner eligible row count does not match the manifest.")
        if len(frames["selected_candidates.csv"]) != int(manifest["candidates"]):
            raise ScannerReaderError("count_mismatch", "Scanner candidate count does not match the manifest.")
        if len(frames["rejected_assets.csv"]) != expected["rejected"] + expected["failed"]:
            raise ScannerReaderError("count_mismatch", "Scanner rejection count does not match the manifest.")
        if "portfolio_fit_assets" in manifest and len(portfolio_fit) != int(manifest["portfolio_fit_assets"]):
            raise ScannerReaderError("count_mismatch", "Scanner portfolio-fit count does not match the manifest.")
        return ScannerGenerationBundle(
            metadata=self._metadata(manifest),
            features=features.copy(deep=True),
            rankings=frames["latest_rankings.csv"].copy(deep=True),
            candidates=frames["selected_candidates.csv"].copy(deep=True),
            rejections=frames["rejected_assets.csv"].copy(deep=True),
            movement=frames["ranking_movement.csv"].copy(deep=True),
            portfolio_fit=portfolio_fit.copy(deep=True),
        )

    def _load_artifact_with_columns(
        self,
        generation_path: Path,
        manifest: Mapping[str, Any],
        filename: str,
        required_columns: set[str],
    ) -> pd.DataFrame:
        path = generation_path / filename
        if not path.is_file():
            raise ScannerReaderError("missing_artifact", f"Scanner artifact is missing: {filename}.")
        declared_hash = manifest["hashes"].get(filename)
        if not isinstance(declared_hash, str) or not declared_hash:
            raise ScannerReaderError("malformed_manifest", f"Scanner manifest has no hash for {filename}.")
        if self._sha256(path) != declared_hash:
            raise ScannerReaderError("hash_mismatch", f"Scanner artifact checksum failed: {filename}.")
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            raise ScannerReaderError("schema_mismatch", f"Scanner artifact is not valid CSV: {filename}.") from exc
        missing = required_columns - set(frame.columns)
        if missing:
            raise ScannerReaderError(
                "schema_mismatch",
                f"Scanner artifact {filename} is missing columns: {', '.join(sorted(missing))}.",
            )
        return frame

    def load_generation_metadata(self) -> ScannerGenerationMetadata:
        return self.load_bundle().metadata

    def load_features(self) -> pd.DataFrame:
        return self.load_bundle().features.copy(deep=True)

    def load_rankings(self) -> pd.DataFrame:
        return self.load_bundle().rankings.copy(deep=True)

    def load_candidates(self) -> pd.DataFrame:
        return self.load_bundle().candidates.copy(deep=True)

    def load_rejections(self) -> pd.DataFrame:
        return self.load_bundle().rejections.copy(deep=True)

    def load_movement(self) -> pd.DataFrame:
        return self.load_bundle().movement.copy(deep=True)

    def load_portfolio_fit(self) -> pd.DataFrame:
        return self.load_bundle().portfolio_fit.copy(deep=True)
