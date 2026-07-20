from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.scanner_reader import ScannerDashboardReader, ScannerReaderError  # noqa: E402


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frames(empty_candidates=False):
    feature_columns = [
        "ticker", "as_of_date", "terminal_state", "scanner_score",
        "data_quality_pass", "rejection_reason", "display_name", "sector",
    ]
    features = pd.DataFrame([
        ["AAA", "2026-07-17", "scored", 120.0, True, "", "Alpha", "Tech"],
        ["BAD", "2026-07-17", "rejected", 80.0, False, "stale_latest_price", "Bad", "Finance"],
    ], columns=feature_columns)
    ranking_columns = [
        "ticker", "display_name", "global_rank", "scanner_score",
        "selected_for_research", "movement_state", "rank_delta",
    ]
    rankings = pd.DataFrame(
        [["AAA", "Alpha", 1, 120.0, not empty_candidates, "new", pd.NA]],
        columns=ranking_columns,
    )
    candidates = rankings.iloc[0:0].copy() if empty_candidates else rankings.copy()
    rejections = features.loc[features["terminal_state"].ne("scored")].copy()
    movement = pd.DataFrame([{
        "ticker": "AAA", "previous_rank": pd.NA, "current_rank": 1,
        "rank_delta": pd.NA, "previous_score": pd.NA, "current_score": 120.0,
        "score_delta": pd.NA, "movement_state": "new",
    }])
    return {
        "scanner_features.csv": features,
        "latest_rankings.csv": rankings,
        "selected_candidates.csv": candidates,
        "rejected_assets.csv": rejections,
        "ranking_movement.csv": movement,
    }


def publish(root, *, empty_candidates=False, status="complete"):
    generation_id = "fixture-generation"
    generation = root / "generations" / generation_id
    generation.mkdir(parents=True)
    artifacts = frames(empty_candidates)
    for name, frame in artifacts.items():
        frame.to_csv(generation / name, index=False)
    manifest = {
        "generation_id": generation_id,
        "acquisition_generation": "fixture-acquisition",
        "status": status,
        "started_at": "2026-07-20T08:00:00+00:00",
        "ended_at": "2026-07-20T08:01:00+00:00",
        "duration_seconds": 60.0,
        "eligible_assets": 2,
        "scored_assets": 1,
        "rejected_assets": 1,
        "failed_assets": 0,
        "candidates": 0 if empty_candidates else 1,
        "universe_counts": {"fixture": 2},
        "feature_schema_version": "scanner-features-v1",
        "scoring_version": "legacy-scanner-score-v1",
        "hashes": {name: sha256(generation / name) for name in artifacts},
    }
    (generation / "scanner_generation_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (root / "current_generation.json").write_text(
        json.dumps({"generation_id": generation_id}), encoding="utf-8"
    )
    return generation


def expect_code(root, code):
    try:
        ScannerDashboardReader(root).load_bundle()
    except ScannerReaderError as exc:
        return exc.code == code
    return False


def main():
    issues = []
    scratch = Path(mkdtemp(prefix=".scanner-reader-validation-", dir=ROOT))
    try:
        valid = scratch / "valid"
        generation = publish(valid)
        before = {p.relative_to(valid): p.read_bytes() for p in valid.rglob("*") if p.is_file()}
        bundle = ScannerDashboardReader(valid).load_bundle()
        after = {p.relative_to(valid): p.read_bytes() for p in valid.rglob("*") if p.is_file()}
        check(bundle.metadata.generation_id == "fixture-generation", "valid complete generation loads", issues)
        check(len(bundle.rejections) == 1, "valid rejected-assets file loads", issues)
        check(before == after, "dashboard reader performs no writes", issues)

        missing_pointer = scratch / "missing-pointer"
        missing_pointer.mkdir()
        check(expect_code(missing_pointer, "no_active_generation"), "missing pointer is classified", issues)

        missing_generation = scratch / "missing-generation"
        missing_generation.mkdir()
        (missing_generation / "current_generation.json").write_text(
            json.dumps({"generation_id": "absent"}), encoding="utf-8"
        )
        check(expect_code(missing_generation, "missing_generation"), "missing generation is classified", issues)

        malformed = scratch / "malformed"
        malformed_generation = publish(malformed)
        (malformed_generation / "scanner_generation_manifest.json").write_text("{", encoding="utf-8")
        check(expect_code(malformed, "malformed_manifest"), "malformed manifest is classified", issues)

        incomplete = scratch / "incomplete"
        publish(incomplete, status="partial")
        check(expect_code(incomplete, "incomplete_generation"), "incomplete generation is refused", issues)

        missing_artifact = scratch / "missing-artifact"
        missing_artifact_generation = publish(missing_artifact)
        (missing_artifact_generation / "ranking_movement.csv").unlink()
        check(expect_code(missing_artifact, "missing_artifact"), "missing artifact is classified", issues)

        bad_schema = scratch / "bad-schema"
        bad_schema_generation = publish(bad_schema)
        bad_path = bad_schema_generation / "latest_rankings.csv"
        pd.DataFrame({"ticker": ["AAA"]}).to_csv(bad_path, index=False)
        manifest_path = bad_schema_generation / "scanner_generation_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["hashes"]["latest_rankings.csv"] = sha256(bad_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        check(expect_code(bad_schema, "schema_mismatch"), "schema mismatch is classified", issues)

        empty = scratch / "empty-candidates"
        publish(empty, empty_candidates=True)
        empty_bundle = ScannerDashboardReader(empty).load_bundle()
        check(empty_bundle.candidates.empty, "valid empty candidates file loads", issues)

        reader_source = (ROOT / "dashboard" / "scanner_reader.py").read_text(encoding="utf-8")
        dashboard_source = (ROOT / "web_dashboard.py").read_text(encoding="utf-8")
        check("yfinance" not in reader_source and "global_scanner" not in reader_source,
              "reader imports neither yfinance nor legacy scanner", issues)
        prohibited = [
            "run_global_scanner", "run_research_scanner_from_dashboard",
            "universe_validated.csv", "SCANNER_UNIVERSE_DIR", "SCANNER_STALE_AFTER",
            "scanner_file_modified_timestamp", "scanner_selected_rows",
            "portfolio_fit_for_row", "apply_portfolio_fit",
        ]
        check(not any(value in dashboard_source for value in prohibited),
              "dashboard has no legacy producer, flat-file, raw-universe, or mtime freshness path", issues)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if issues:
        raise AssertionError("; ".join(issues))
    print("\nScanner dashboard reader validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
