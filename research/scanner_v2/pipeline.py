from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import time

import pandas as pd

from execution.atomic_io import atomic_write_csv_frames, atomic_write_json


FEATURE_KEY = ["ticker", "as_of_date"]


@dataclass(frozen=True)
class RankingPolicy:
    minimum_score: float = 0.0
    top_n: int = 15


def validate_feature_store(features):
    missing = [column for column in FEATURE_KEY if column not in features]
    if missing:
        raise ValueError(f"Scanner feature store missing columns: {missing}")
    if features.duplicated(FEATURE_KEY).any():
        raise ValueError("Scanner feature store has duplicate ticker/as-of keys")
    return features.sort_values(FEATURE_KEY, kind="stable").reset_index(drop=True)


def rank_feature_store(features, memberships=None, policy=RankingPolicy()):
    ranked = validate_feature_store(features).copy()
    if "scanner_score" not in ranked:
        raise ValueError("Scanner feature store has no scanner_score")
    ranked["scanner_score"] = pd.to_numeric(ranked["scanner_score"], errors="coerce")
    ranked["data_quality_confidence"] = pd.to_numeric(
        ranked.get("data_quality_confidence", 0.0), errors="coerce"
    ).fillna(0.0)
    ranked["excluded"] = ranked["scanner_score"].isna() | ranked["scanner_score"].lt(policy.minimum_score)
    ranked["exclusion_reasons"] = ranked.get("exclusion_reasons", "")
    below = ranked["scanner_score"].notna() & ranked["scanner_score"].lt(policy.minimum_score)
    ranked.loc[below & ranked["exclusion_reasons"].eq(""), "exclusion_reasons"] = "below_minimum_score"
    ranked = ranked.sort_values(
        ["excluded", "scanner_score", "data_quality_confidence", "ticker"],
        ascending=[True, False, False, True], kind="stable",
    ).reset_index(drop=True)
    scored = ~ranked["excluded"]
    ranked["global_rank"] = pd.NA
    ranked.loc[scored, "global_rank"] = range(1, int(scored.sum()) + 1)

    global_candidates = ranked.loc[~ranked["excluded"]].sort_values(
        ["global_rank", "ticker"], kind="stable"
    ).head(policy.top_n).copy()
    if memberships is not None and not memberships.empty:
        expanded = ranked.merge(memberships[["ticker", "universe_name"]], on="ticker", how="left")
        expanded["universe_rank"] = expanded.groupby("universe_name", dropna=False)["scanner_score"].rank(method="first", ascending=False)
        ranked = expanded
    else:
        ranked["universe_name"] = "global"
        ranked["universe_rank"] = ranked["global_rank"]
    return ranked, global_candidates


def build_manifest(*, run_id, started_at, ended_at, requested, eligible, scored, rejected, failed_downloads=0, stale_cache_assets=0, batch_count=0, universe_versions=None, partial=False):
    counts = {
        "requested_assets": int(requested), "eligible_assets": int(eligible),
        "successfully_scored_assets": int(scored), "rejected_assets": int(rejected),
        "failed_downloads": int(failed_downloads), "stale_cache_assets": int(stale_cache_assets),
    }
    if counts["requested_assets"] != counts["eligible_assets"] + counts["rejected_assets"]:
        raise ValueError("Manifest counts do not reconcile: requested != eligible + rejected")
    if counts["successfully_scored_assets"] > counts["eligible_assets"]:
        raise ValueError("Manifest scored assets exceed eligible assets")
    start, end = pd.Timestamp(started_at), pd.Timestamp(ended_at)
    return {
        "run_id": str(run_id), "status": "partial" if partial else "complete",
        **counts, "duration_seconds": max(0.0, (end - start).total_seconds()),
        "batch_count": int(batch_count), "universe_versions": universe_versions or {},
        "started_at": start.isoformat(), "ended_at": end.isoformat(),
    }


def write_scan_outputs(output_dir, *, features, rankings, candidates, rejected, manifest, failure_hook=None):
    """Publish complete CSV outputs together; manifest is the completion marker."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        output / "scanner_features.csv": validate_feature_store(features),
        output / "latest_rankings.csv": rankings,
        output / "selected_candidates.csv": candidates,
        output / "rejected_assets.csv": rejected,
    }
    atomic_write_csv_frames(frames, failure_hook=failure_hook, lock_path=output / ".scanner-write.lock")
    atomic_write_json(manifest, output / "scan_run_manifest.json", lock_path=output / ".scanner-write.lock")
    return [str(path) for path in frames] + [str(output / "scan_run_manifest.json")]


def run_fixture_pipeline(universe, memberships, features, output_dir=None, policy=RankingPolicy()):
    started = pd.Timestamp.now(tz="UTC")
    rankings, candidates = rank_feature_store(features, memberships, policy)
    rejected = rankings.loc[rankings["excluded"]].copy()
    eligible = len(universe)
    manifest = build_manifest(
        run_id=f"fixture-{len(universe)}", started_at=started,
        ended_at=pd.Timestamp.now(tz="UTC"), requested=len(universe),
        eligible=eligible,
        scored=int(rankings.loc[~rankings["excluded"], "ticker"].nunique()),
        rejected=0, batch_count=(len(universe) + 99) // 100,
        universe_versions={"fixture": str(len(universe))}, partial=False,
    )
    if output_dir is not None:
        write_scan_outputs(output_dir, features=features, rankings=rankings, candidates=candidates, rejected=rejected, manifest=manifest)
    return rankings, candidates, manifest
