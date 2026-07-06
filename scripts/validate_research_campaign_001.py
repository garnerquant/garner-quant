from pathlib import Path
import hashlib
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.research_campaigns import (
    build_campaign_leaderboard,
    build_campaign_summary,
    run_campaign_001,
)
from research.research_result_schema import load_canonical_result


PRODUCTION_INPUTS = [
    "signals_v2.csv",
    "prices_v2.csv",
    "weights_v2.csv",
    "portfolio_v2.csv",
    "trade_journal_v3.csv",
]


def _file_hash(path):
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_hashes():
    return {
        filename: _file_hash(ROOT / filename)
        for filename in PRODUCTION_INPUTS
    }


def _best_name(summary, key):
    row = summary.get(key) or {}
    return row.get("variation_name", "Unavailable")


def _is_number(value):
    try:
        value = float(value)
    except Exception:
        return False
    return math.isfinite(value)


def _sanity_check(leaderboard):
    required_metrics = [
        "total_return",
        "cagr",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "win_rate",
        "profit_factor",
        "trade_count",
        "average_holding_period",
        "average_win",
        "average_loss",
        "best_trade",
        "worst_trade",
    ]
    errors = []

    if "experiment_id" in leaderboard.columns:
        duplicate_ids = leaderboard["experiment_id"].duplicated().sum()
        if duplicate_ids:
            errors.append(f"duplicate experiment IDs: {duplicate_ids}")

    for _, row in leaderboard.iterrows():
        if row.get("status") not in {"completed", "dry_run"}:
            continue
        for metric in required_metrics:
            if metric not in leaderboard.columns:
                errors.append(f"missing metric: {metric}")
                continue
            if not _is_number(row.get(metric)):
                errors.append(f"{row.get('variation_name')} has invalid {metric}")

        win_rate = float(row.get("win_rate", 0))
        if win_rate < 0 or win_rate > 1:
            errors.append(f"{row.get('variation_name')} has impossible win rate {win_rate}")

        holding_period = float(row.get("average_holding_period", 0))
        if holding_period < 0:
            errors.append(
                f"{row.get('variation_name')} has negative holding period {holding_period}"
            )

    return errors


def _run_campaign(registry_path):
    try:
        result = run_campaign_001(
            path=registry_path,
            dry_run=False,
            base_path=ROOT,
            save_report=False,
        )
        mode = "real_simulation"
        return result, mode, None
    except Exception as exc:
        result = run_campaign_001(
            path=registry_path,
            dry_run=True,
            base_path=ROOT,
            save_report=False,
        )
        return result, "dry_run", str(exc)


def main():
    registry_path = ROOT / "research" / "experiments" / "experiments.jsonl"
    before_hashes = _snapshot_hashes()
    result, mode, fallback_reason = _run_campaign(registry_path)
    after_hashes = _snapshot_hashes()

    summary = build_campaign_summary(result["campaign_id"], path=registry_path)
    leaderboard = build_campaign_leaderboard(
        result["campaign_id"],
        path=registry_path,
    )
    sanity_errors = _sanity_check(leaderboard)
    canonical_paths = result.get("canonical_result_paths") or []
    canonical_results = []
    for path in canonical_paths:
        result_path = Path(path)
        if not result_path.is_absolute():
            result_path = ROOT / result_path
        canonical_results.append(load_canonical_result(result_path))

    changed_inputs = [
        filename
        for filename, before_hash in before_hashes.items()
        if before_hash != after_hashes.get(filename)
    ]

    if sanity_errors:
        raise AssertionError("; ".join(sanity_errors))
    if changed_inputs:
        raise AssertionError(
            "production input files changed during validation: "
            + ", ".join(changed_inputs)
        )
    if len(canonical_results) != len(leaderboard):
        raise AssertionError(
            f"expected {len(leaderboard)} canonical results, got {len(canonical_results)}"
        )
    if not any(
        item["candidate_strategy"] == "Time exit 10 days"
        for item in canonical_results
    ):
        raise AssertionError("canonical Campaign 001 variants were not exported")
    if not all(
        item["baseline_strategy"] == "Current binary exit"
        and item["metrics"]["trade_count"] >= 0
        and "sharpe_delta" in item["comparison"]
        for item in canonical_results
    ):
        raise AssertionError("canonical Campaign 001 exports are incomplete")

    print("Research Campaign 001 validation passed")
    print(f"Mode: {mode}")
    if fallback_reason:
        print(f"Fallback reason: {fallback_reason}")
    print(f"Registry: {registry_path.relative_to(ROOT)}")
    print(f"Campaign ID: {result['campaign_id']}")
    print(f"Runs: {summary['runs']}")
    print(f"Completed: {summary['completed_runs']}")
    print(f"Failed: {summary['failed_runs']}")
    print(f"Unsupported: {summary['unsupported_runs']}")
    print(f"Real simulations: {summary['real_simulation_runs']}")
    print(f"Dry-run rows: {summary['dry_run_runs']}")
    print(f"Best Sharpe: {_best_name(summary, 'best_sharpe')}")
    print(f"Best CAGR: {_best_name(summary, 'best_cagr')}")
    print(f"Best Drawdown: {_best_name(summary, 'best_drawdown')}")
    print(f"Best Profit Factor: {_best_name(summary, 'best_profit_factor')}")
    print(f"Leaderboard rows: {len(leaderboard)}")
    print(f"Canonical results: {len(canonical_results)}")
    print("Sanity checks: passed")
    print("Production input hashes: unchanged")
    if result.get("report_path"):
        report_path = Path(result["report_path"])
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        print(f"Report: {report_path.relative_to(ROOT)}")
    if result.get("report_export_path"):
        export_path = Path(result["report_export_path"])
        if not export_path.is_absolute():
            export_path = ROOT / export_path
        print(f"Report export: {export_path.relative_to(ROOT)}")
    if result.get("latest_report_export_path"):
        latest_export_path = Path(result["latest_report_export_path"])
        if not latest_export_path.is_absolute():
            latest_export_path = ROOT / latest_export_path
        print(f"Latest report export: {latest_export_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
