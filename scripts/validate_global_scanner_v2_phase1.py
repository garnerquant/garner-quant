from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.scanner_v2.pipeline import RankingPolicy, build_manifest, run_fixture_pipeline, write_scan_outputs
from research.scanner_v2.universe import EligibilityRules, deterministic_batches, incremental_refresh_start, load_canonical_universe, market_data_eligibility, normalize_ticker, structural_eligibility


def check(value, message, issues):
    print(("PASS" if value else "FAIL") + f": {message}")
    if not value:
        issues.append(message)


def fixture_universe(path, count):
    path.mkdir(parents=True, exist_ok=True)
    midpoint = count // 2
    columns = ["ticker", "display_name", "asset_type", "exchange", "country", "currency", "sector", "industry", "universe_source", "enabled", "priority", "max_position_weight", "first_seen_at", "last_verified_at", "universe_name"]
    rows = []
    for index in range(count):
        rows.append([f"T{index:04d}", f"Asset {index}", "Equity", "NASDAQ", "United States", "USD", "Test", "Test", "fixture", True, index % 5, np.nan, "2026-01-01", "2026-07-16", "alpha" if index < midpoint else "beta"])
    pd.DataFrame(rows[:midpoint], columns=columns).to_csv(path / "alpha.csv", index=False)
    pd.DataFrame(rows[midpoint:], columns=columns).to_csv(path / "beta.csv", index=False)
    return rows


def features_for(universe):
    return pd.DataFrame({
        "ticker": universe["ticker"], "as_of_date": "2026-07-16",
        "scanner_score": [float(index % 101) for index in range(len(universe))],
        "data_quality_confidence": 0.95, "exclusion_reasons": "",
    })


def main():
    issues = []
    base = ROOT / ".scanner_v2_phase1_fixture"
    if base.exists():
        shutil.rmtree(base)
    try:
        small = base / "small"
        fixture_universe(small, 12)
        duplicate = pd.read_csv(small / "beta.csv").iloc[[0]].copy()
        duplicate["universe_name"] = "gamma"
        duplicate.to_csv(small / "gamma.csv", index=False)
        universe, memberships = load_canonical_universe(small, observed_at="2026-07-16T12:00:00Z")
        check(len(universe) == 12 and len(memberships) == 13, "universe merge deduplicates assets without losing named memberships", issues)
        check(normalize_ticker(" brk.b ") == "BRK.B", "ticker normalization is canonical and deterministic", issues)

        bad = universe.iloc[[0]].copy()
        bad["ticker"] = "BAD/TICKER"
        bad["enabled"] = False
        structural = pd.concat([universe.iloc[[1]], bad], ignore_index=True)
        eligible, rejected = structural_eligibility(structural, EligibilityRules(supported_exchanges=frozenset({"NASDAQ"}), supported_currencies=frozenset({"USD"})))
        check(len(eligible) == 1 and set(rejected.iloc[0]["rejection_reasons"].split("|")) == {"disabled", "unsupported_ticker_format"}, "structural eligibility reports every rejection reason", issues)

        quality = pd.DataFrame([{"ticker": "A", "valid_bar_count": 20, "latest_close": 0.0, "avg_traded_value_60d": 0, "missing_close_pct": 0.5, "download_failed": True, "quarantined": False}])
        _, quality_rejected = market_data_eligibility(quality, EligibilityRules(minimum_average_traded_value=1000))
        check(set(quality_rejected.iloc[0]["exclusion_reasons"].split("|")) == {"download_failed", "insufficient_history", "liquidity_below_minimum", "missing_data_exceeds_tolerance", "price_below_minimum"}, "market eligibility reports complete reasons", issues)
        check([len(batch) for batch in deterministic_batches(["C", "A", "B", "A", "D", "E"], 2)] == [2, 2, 1], "batch partitioning is sorted, deduplicated, and bounded", issues)
        now = pd.Timestamp("2026-07-16T12:00:00Z")
        check(incremental_refresh_start(pd.Timestamp("2026-07-15T12:00:00Z"), now) == pd.Timestamp("2026-07-10T12:00:00Z"), "incremental refresh uses bounded overlap instead of full history", issues)

        for count in (500, 1500):
            folder = base / str(count)
            fixture_universe(folder, count)
            large_universe, large_memberships = load_canonical_universe(folder, observed_at=now)
            rankings, candidates, manifest = run_fixture_pipeline(large_universe, large_memberships, features_for(large_universe), policy=RankingPolicy(minimum_score=10, top_n=25))
            check(len(large_universe) == count and len(rankings) == count and len(candidates) == 25, f"{count}-asset fixture completes deterministically", issues)
            reranked, _, _ = run_fixture_pipeline(large_universe.sample(frac=1, random_state=7), large_memberships.sample(frac=1, random_state=8), features_for(large_universe).sample(frac=1, random_state=9), policy=RankingPolicy(minimum_score=10, top_n=25))
            first = rankings.sort_values(["ticker", "universe_name"])[["ticker", "universe_name", "global_rank"]].reset_index(drop=True)
            second = reranked.sort_values(["ticker", "universe_name"])[["ticker", "universe_name", "global_rank"]].reset_index(drop=True)
            check(first.equals(second), f"{count}-asset rankings are independent of input/completion order", issues)
            check(manifest["requested_assets"] == manifest["eligible_assets"] + manifest["rejected_assets"] and manifest["successfully_scored_assets"] <= manifest["eligible_assets"], f"{count}-asset manifest counts reconcile", issues)

        output = base / "outputs"
        output.mkdir(parents=True)
        prior = b"ticker,as_of_date\nOLD,2026-01-01\n"
        for name in ["scanner_features.csv", "latest_rankings.csv", "selected_candidates.csv", "rejected_assets.csv"]:
            (output / name).write_bytes(prior)
        features = features_for(universe)
        rankings, candidates, manifest = run_fixture_pipeline(universe, memberships, features, policy=RankingPolicy(top_n=3))
        before = {path.name: path.read_bytes() for path in output.glob("*.csv")}
        def fail(stage, _targets):
            if stage == "after_temp_writes":
                raise RuntimeError("fixture failure")
        try:
            write_scan_outputs(output, features=features, rankings=rankings, candidates=candidates, rejected=rankings.iloc[0:0], manifest=manifest, failure_hook=fail)
            refused = False
        except Exception:
            refused = True
        after = {path.name: path.read_bytes() for path in output.glob("*.csv")}
        check(refused and before == after and not (output / "scan_run_manifest.json").exists(), "failed atomic publication preserves every last-good output", issues)
    finally:
        if base.exists():
            shutil.rmtree(base)
    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
