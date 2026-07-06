from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.automated_parameter_sweep import (
    build_sweep_leaderboard,
    build_sweep_summary,
    run_parameter_sweep,
)
from research.research_result_schema import load_canonical_result


def main():
    registry_path = ROOT / "research" / "experiments" / "experiments.jsonl"
    result = run_parameter_sweep(
        parameter_name="stop_loss_pct",
        candidate_values=[0.02, 0.03, 0.04],
        experiment_name="Research Lab V2 validation sweep",
        notes="Dry-run validation for automated parameter sweep engine.",
        path=registry_path,
        dry_run=True,
        base_path=ROOT,
    )
    summary = build_sweep_summary(result["sweep_id"], path=registry_path)
    leaderboard = build_sweep_leaderboard(result["sweep_id"], path=registry_path)
    canonical_results = [
        load_canonical_result(path)
        for path in result.get("canonical_result_paths", [])
    ]
    if len(canonical_results) != len(leaderboard):
        raise AssertionError(
            f"expected {len(leaderboard)} canonical sweep results, got {len(canonical_results)}"
        )
    if not all(
        item["baseline_strategy"] == "Current binary exit"
        and item["candidate_strategy"]
        and "sharpe_delta" in item["comparison"]
        for item in canonical_results
    ):
        raise AssertionError("canonical parameter sweep exports are incomplete")

    print("Research Lab V2 parameter sweep validation passed")
    print(f"Registry: {registry_path.relative_to(ROOT)}")
    print(f"Sweep ID: {result['sweep_id']}")
    print(f"Parameter: {summary['parameter_tested']}")
    print(f"Runs: {summary['runs']}")
    print(f"Completed: {summary['completed_runs']}")
    print(f"Failed: {summary['failed_runs']}")
    print(f"Best Sharpe value: {summary['best_sharpe_value']}")
    print(f"Best CAGR value: {summary['best_cagr_value']}")
    print(f"Lowest drawdown value: {summary['lowest_drawdown_value']}")
    print(f"Leaderboard rows: {len(leaderboard)}")
    print(f"Canonical results: {len(canonical_results)}")


if __name__ == "__main__":
    main()
