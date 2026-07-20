"""Immutable report publication for Scanner-generation research."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from research.scanner_forward_returns import FORWARD_HORIZONS, add_forward_returns
from research.scanner_generation_reader import ScannerResearchReader
from research.scanner_history import build_historical_dataset
from research.scanner_research_analytics import build_research_reports, evaluate_factors


REPORT_SCHEMA_VERSION = "scanner-research-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _summary(history: pd.DataFrame, factors: pd.DataFrame, generation_ids: list[str]) -> dict:
    coverage = {}
    for horizon in FORWARD_HORIZONS:
        column = f"forward_return_{horizon}d_pct"
        if column in history:
            coverage[str(horizon)] = int(pd.to_numeric(history[column], errors="coerce").notna().sum())
    leaders = {}
    if not factors.empty:
        for horizon, group in factors.groupby("horizon_days", sort=True):
            usable = group.dropna(subset=["predictive_statistic"]).head(10)
            leaders[str(int(horizon))] = _json_safe(usable.to_dict(orient="records"))
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generation_ids": generation_ids,
        "generation_count": len(generation_ids),
        "observation_count": len(history),
        "outcome_coverage": coverage,
        "leading_factors": leaders,
    }


def publish_research_reports(
    history: pd.DataFrame,
    report_root: str | Path,
    generation_ids,
    outcome_bar_generation: str,
    report_id: str | None = None,
) -> Path:
    """Publish one immutable, hash-declared research report generation."""
    root = Path(report_root).resolve()
    identity = report_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if not identity or Path(identity).name != identity:
        raise ValueError("Research report identity is invalid")
    destination = root / "generations" / identity
    if destination.exists():
        raise FileExistsError(f"Research report generation already exists: {identity}")
    staging = root / "generations" / f".{identity}.{uuid4().hex}.tmp"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        tables = build_research_reports(history)
        factors = evaluate_factors(history)
        tables["factor_report.csv"] = factors
        tables["historical_dataset.csv"] = history.copy(deep=True)
        hashes = {}
        counts = {}
        for name, frame in sorted(tables.items()):
            path = staging / name
            frame.to_csv(path, index=False)
            hashes[name] = _sha256(path)
            counts[name] = len(frame)
        generation_list = [str(value) for value in generation_ids]
        summary = _summary(history, factors, generation_list)
        summary_path = staging / "research_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        hashes[summary_path.name] = _sha256(summary_path)
        manifest = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": identity,
            "status": "complete",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_scanner_generations": generation_list,
            "outcome_bar_generation": str(outcome_bar_generation),
            "row_counts": counts,
            "hashes": hashes,
        }
        (staging / "research_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return destination


def run_scanner_research(
    feature_store_root: str | Path,
    bar_store_root: str | Path,
    report_root: str | Path,
    *,
    generation_ids=None,
    start=None,
    end=None,
    outcome_generation: str = "current",
    report_id: str | None = None,
) -> Path:
    """Load Scanner history, attach pinned outcomes, and publish research reports."""
    reader = ScannerResearchReader(feature_store_root)
    if generation_ids is not None and (start is not None or end is not None):
        raise ValueError("Choose generation IDs or a date range, not both")
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("Both research date-range bounds are required")
        generations = reader.load_between(start, end)
    else:
        generations = reader.load_history(generation_ids)
    history = build_historical_dataset(generations)
    outcomes = add_forward_returns(history, bar_store_root, outcome_generation)
    pinned = "" if outcomes.empty else str(outcomes["outcome_bar_generation"].dropna().iloc[0])
    if not pinned:
        pinned = outcome_generation
    return publish_research_reports(
        outcomes,
        report_root,
        [generation.generation_id for generation in generations],
        pinned,
        report_id,
    )
