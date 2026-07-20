"""Read-only loading of immutable Scanner v2 generation history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from research.scanner_v2.generation import GENERATION_ARTIFACTS, ScannerGeneration


class ResearchGenerationError(RuntimeError):
    pass


class ScannerResearchReader:
    """Load validated ScannerGeneration objects without mutating scanner state."""

    def __init__(self, feature_store_root: str | Path):
        self.root = Path(feature_store_root).resolve()
        self.generations = self.root / "generations"
        self.pointer = self.root / "current_generation.json"

    @staticmethod
    def _json(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResearchGenerationError(f"Invalid Scanner JSON: {path.name}") from exc
        if not isinstance(value, dict):
            raise ResearchGenerationError(f"Scanner JSON is not an object: {path.name}")
        return value

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def current_generation_id(self) -> str:
        if not self.pointer.is_file():
            raise ResearchGenerationError("No current Scanner generation is published")
        value = str(self._json(self.pointer).get("generation_id", "")).strip()
        if not value or Path(value).name != value:
            raise ResearchGenerationError("Current Scanner generation pointer is invalid")
        return value

    def load_generation(self, generation_id: str = "current") -> ScannerGeneration:
        identity = self.current_generation_id() if generation_id == "current" else str(generation_id).strip()
        if not identity or Path(identity).name != identity:
            raise ResearchGenerationError("Scanner generation identity is invalid")
        directory = (self.generations / identity).resolve()
        if directory.parent != self.generations.resolve() or not directory.is_dir():
            raise ResearchGenerationError(f"Scanner generation does not exist: {identity}")
        manifest_path = directory / "scanner_generation_manifest.json"
        if not manifest_path.is_file():
            raise ResearchGenerationError(f"Scanner generation has no manifest: {identity}")
        manifest = self._json(manifest_path)
        if str(manifest.get("generation_id")) != identity:
            raise ResearchGenerationError("Scanner manifest identity does not match its directory")
        if manifest.get("status") != "complete":
            raise ResearchGenerationError(f"Scanner generation is not complete: {identity}")
        hashes = manifest.get("hashes")
        if not isinstance(hashes, dict):
            raise ResearchGenerationError("Scanner manifest hash contract is invalid")
        frames = {}
        for name in GENERATION_ARTIFACTS:
            path = directory / name
            if not path.is_file():
                raise ResearchGenerationError(f"Scanner generation artifact is missing: {name}")
            expected = hashes.get(name)
            if not isinstance(expected, str) or self._hash(path) != expected:
                raise ResearchGenerationError(f"Scanner generation artifact hash failed: {name}")
            try:
                frames[name] = pd.read_csv(path)
            except Exception as exc:
                raise ResearchGenerationError(f"Scanner artifact is not valid CSV: {name}") from exc
        generation = ScannerGeneration(
            generation_id=identity,
            manifest=manifest,
            features=frames["scanner_features.csv"],
            rankings=frames["latest_rankings.csv"],
            candidates=frames["selected_candidates.csv"],
            rejections=frames["rejected_assets.csv"],
            movement=frames["ranking_movement.csv"],
            portfolio_fit=frames["portfolio_fit.csv"],
        )
        try:
            generation.validate()
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchGenerationError(f"Scanner generation contract failed: {identity}") from exc
        return generation

    def _history_index(self) -> list[tuple[pd.Timestamp, str]]:
        if not self.generations.is_dir():
            return []
        indexed = []
        for directory in self.generations.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            manifest_path = directory / "scanner_generation_manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = self._json(manifest_path)
            ended = pd.to_datetime(manifest.get("ended_at"), utc=True, errors="coerce")
            if pd.isna(ended):
                raise ResearchGenerationError(f"Scanner generation has invalid ended_at: {directory.name}")
            indexed.append((ended, directory.name))
        return sorted(indexed, key=lambda item: (item[0], item[1]))

    def load_history(self, generation_ids=None) -> tuple[ScannerGeneration, ...]:
        selected = None if generation_ids is None else {str(value) for value in generation_ids}
        identities = [identity for _, identity in self._history_index() if selected is None or identity in selected]
        if selected is not None and selected != set(identities):
            missing = sorted(selected - set(identities))
            raise ResearchGenerationError(f"Scanner generations were not found: {', '.join(missing)}")
        return tuple(self.load_generation(identity) for identity in identities)

    def load_between(self, start, end) -> tuple[ScannerGeneration, ...]:
        lower = pd.Timestamp(start)
        upper = pd.Timestamp(end)
        lower = lower.tz_localize("UTC") if lower.tzinfo is None else lower.tz_convert("UTC")
        upper = upper.tz_localize("UTC") if upper.tzinfo is None else upper.tz_convert("UTC")
        if lower > upper:
            raise ValueError("Research generation start must not be after end")
        identities = [identity for ended, identity in self._history_index() if lower <= ended <= upper]
        return tuple(self.load_generation(identity) for identity in identities)
