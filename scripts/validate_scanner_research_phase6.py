from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.scanner_forward_returns import add_forward_returns  # noqa: E402
from research.scanner_generation_reader import ScannerResearchReader  # noqa: E402
from research.scanner_history import build_historical_dataset  # noqa: E402
from research.scanner_research_analytics import build_research_reports, evaluate_factors  # noqa: E402
from research.scanner_research_reports import publish_research_reports  # noqa: E402
from research.scanner_v2.features import (  # noqa: E402
    FeatureGenerationStore, calculate_ticker_features, rank_features, ranking_movement,
)
from research.scanner_v2.generation import ScannerGeneration  # noqa: E402
from research.scanner_v2.intelligence import enrich_feature_intelligence  # noqa: E402
from research.scanner_v2.portfolio_intelligence import build_portfolio_fit  # noqa: E402


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def _bars(ticker, multiplier=1.0):
    dates = pd.bdate_range("2025-01-02", periods=420)
    close = (80 + np.arange(len(dates)) * 0.15) * multiplier
    return pd.DataFrame({
        "ticker": ticker, "date": dates, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1_000_000 * multiplier,
        "source": "fixture", "fetched_at": "2026-07-20T08:00:00+00:00", "adjusted": True,
    })


def _feature(ticker, sector, country, multiplier):
    data = _bars(ticker, multiplier)
    metadata = {
        "ticker": ticker, "display_name": ticker, "asset_type": "equity",
        "exchange": "TEST", "country": country, "currency": "USD", "sector": sector,
        "industry": "Fixture", "universe_source": "fixture", "enabled": True,
        "priority": 1, "max_position_weight": 0.1, "first_seen_at": "2025-01-02",
        "last_verified_at": "2026-07-20",
    }
    return calculate_ticker_features(ticker, data, metadata, ["fixture"], data["date"].iloc[-1])


def _generation(identity, ended_at, as_of_date, score_shift=0.0):
    features = pd.DataFrame([
        _feature("AAA", "Technology", "US", 1.0),
        _feature("BBB", "Utilities", "GB", 0.8),
        _feature("CCC", "Technology", "US", 1.2),
    ]).sort_values("ticker", kind="stable").reset_index(drop=True)
    features["scanner_score"] = features["scanner_score"] + score_shift
    features["as_of_date"] = as_of_date
    features = enrich_feature_intelligence(features)
    memberships = pd.DataFrame({"ticker": features["ticker"], "universe_name": "fixture"})
    rankings, _ = rank_features(features, memberships, top_n=2)
    movement = ranking_movement(rankings, pd.DataFrame())
    movement_map = movement.set_index("ticker")
    for column in ("rank_delta", "movement_state"):
        rankings[column] = rankings["ticker"].map(movement_map[column])
    rankings["days_in_top_list"] = rankings["global_rank"].map({1: 12, 2: 6, 3: 1})
    rankings["consecutive_days_seen"] = rankings["days_in_top_list"]
    rankings["highest_rank_seen"] = rankings["global_rank"]
    rankings["average_rank"] = rankings["global_rank"].astype(float)
    rankings["rank_volatility"] = 0.0
    rankings["persistence_score"] = rankings["global_rank"].map({1: 90.0, 2: 60.0, 3: 20.0})
    rankings["persistence_level"] = rankings["global_rank"].map({1: "High", 2: "Medium", 3: "Low"})
    candidates = rankings[rankings["selected_for_research"]].copy()
    portfolio_fit = build_portfolio_fit(candidates, features, None)
    manifest = {
        "generation_id": identity, "acquisition_generation": "outcome-bars",
        "status": "complete", "started_at": ended_at, "ended_at": ended_at,
        "duration_seconds": 0.0, "eligible_assets": 3, "scored_assets": 3,
        "rejected_assets": 0, "failed_assets": 0, "candidates": len(candidates),
        "universe_counts": {"fixture": 3}, "feature_schema_version": "scanner-features-v2",
        "scoring_version": "legacy-scanner-score-v1",
        "intelligence_schema_version": "scanner-intelligence-v1",
        "portfolio_fit_assets": len(portfolio_fit),
    }
    return ScannerGeneration(
        identity, manifest, features, rankings, candidates, features.iloc[0:0].copy(),
        movement, portfolio_fit,
    )


def _tree_hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def _write_bars(root):
    directory = root / "generations" / "outcome-bars" / "bars"
    directory.mkdir(parents=True)
    for ticker, multiplier in (("AAA", 1.0), ("BBB", 0.8), ("CCC", 1.2)):
        _bars(ticker, multiplier).to_csv(directory / f"{ticker}.csv", index=False)
    (root / "current_generation.json").write_text(
        json.dumps({"generation_id": "outcome-bars"}), encoding="utf-8"
    )


def _import_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def main():
    issues = []
    scratch = Path(mkdtemp(prefix="scanner-phase6-validation-"))
    try:
        feature_root, bar_root, report_root = scratch / "features", scratch / "bars", scratch / "reports"
        store = FeatureGenerationStore(feature_root)
        first = _generation("research-001", "2026-01-15T18:00:00+00:00", "2026-01-15")
        second = _generation("research-002", "2026-02-16T18:00:00+00:00", "2026-02-16", 0.5)
        store.publish(first.frames(), first.manifest, generation_id=first.generation_id)
        store.publish(second.frames(), second.manifest, generation_id=second.generation_id)
        _write_bars(bar_root)
        before = _tree_hashes(feature_root)

        reader = ScannerResearchReader(feature_root)
        check(reader.load_generation().generation_id == "research-002", "current generation loads", issues)
        history_generations = reader.load_history()
        check([item.generation_id for item in history_generations] == ["research-001", "research-002"],
              "history is ordered by manifest time", issues)
        check(len(reader.load_history(["research-001"])) == 1, "generation IDs filter history", issues)
        between = reader.load_between("2026-02-01", "2026-03-01")
        check([item.generation_id for item in between] == ["research-002"], "date ranges filter history", issues)

        history = build_historical_dataset(history_generations)
        check(len(history) == 6 and not history.duplicated(["generation_id", "ticker", "as_of_date"]).any(),
              "historical dataset has one immutable observation key", issues)
        expected = {"global_rank", "candidate_status", "movement_state", "persistence_score",
                    "portfolio_fit_status", "sector", "liquidity_bucket"}
        check(expected.issubset(history.columns), "history stacks every canonical intelligence family", issues)
        original = history.copy(deep=True)
        outcomes = add_forward_returns(history, bar_root, "outcome-bars")
        check(history.equals(original), "forward-return engine does not mutate history", issues)
        check(outcomes["forward_return_5d_pct"].notna().all(), "five-day outcomes use pinned canonical bars", issues)
        check(outcomes["forward_return_252d_pct"].isna().any(), "unavailable long outcomes remain null", issues)

        reports = build_research_reports(outcomes)
        check({"ranking_report.csv", "sector_report.csv", "country_report.csv", "bucket_report.csv",
               "regime_report.csv", "candidate_report.csv"} == set(reports),
              "all requested grouped reports are generated", issues)
        check(all(not frame.empty for frame in reports.values()), "grouped research reports contain metrics", issues)
        factors_one = evaluate_factors(outcomes)
        factors_two = evaluate_factors(outcomes)
        check(factors_one.equals(factors_two) and not factors_one.empty,
              "factor predictive statistics are deterministic", issues)

        destination = publish_research_reports(
            outcomes, report_root, [item.generation_id for item in history_generations],
            "outcome-bars", "fixture-report",
        )
        required = {"factor_report.csv", "sector_report.csv", "country_report.csv",
                    "bucket_report.csv", "regime_report.csv", "candidate_report.csv",
                    "ranking_report.csv", "historical_dataset.csv", "research_summary.json",
                    "research_manifest.json"}
        check(required.issubset({path.name for path in destination.iterdir()}),
              "immutable report bundle publishes all declared artifacts", issues)
        manifest = json.loads((destination / "research_manifest.json").read_text(encoding="utf-8"))
        check(all(hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
                  for name, digest in manifest["hashes"].items()), "report manifest hashes reconcile", issues)
        duplicate_refused = False
        try:
            publish_research_reports(outcomes, report_root, [], "outcome-bars", "fixture-report")
        except FileExistsError:
            duplicate_refused = True
        check(duplicate_refused, "published research generations cannot be overwritten", issues)
        check(_tree_hashes(feature_root) == before, "research never mutates Scanner generations or pointer", issues)

        modules = [
            ROOT / "research/scanner_generation_reader.py", ROOT / "research/scanner_history.py",
            ROOT / "research/scanner_forward_returns.py", ROOT / "research/scanner_research_analytics.py",
            ROOT / "research/scanner_research_reports.py",
        ]
        prohibited = {"dashboard", "execution", "runtime", "accounting", "yfinance", "streamlit"}
        check(all(not (_import_roots(path) & prohibited) for path in modules),
              "Research modules have no dashboard, operational, or network dependency", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if issues:
        raise AssertionError("; ".join(issues))
    print("\nScanner research Phase 6 validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
