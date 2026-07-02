from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.automated_parameter_sweep import (
    build_grid_leaderboard,
    build_grid_summary,
    run_parameter_grid,
)


def main():
    registry_path = ROOT / "research" / "experiments" / "experiments.jsonl"
    result = run_parameter_grid(
        parameter_grid={
            "stop_loss_pct": [0.02, 0.03],
            "technical_score_threshold": [3, 4],
            "max_positions": [5, 8],
        },
        experiment_name="Research Lab V3 validation grid",
        notes="Dry-run validation for multi-parameter grid search.",
        path=registry_path,
        dry_run=True,
        base_path=ROOT,
    )
    summary = build_grid_summary(result["grid_id"], path=registry_path)
    leaderboard = build_grid_leaderboard(result["grid_id"], path=registry_path)

    print("Research Lab V3 parameter grid validation passed")
    print(f"Registry: {registry_path.relative_to(ROOT)}")
    print(f"Grid ID: {result['grid_id']}")
    print(f"Runs: {summary['runs']}")
    print(f"Completed: {summary['completed_runs']}")
    print(f"Failed: {summary['failed_runs']}")
    print(f"Best Sharpe config: {summary['best_sharpe_config']}")
    print(f"Best CAGR config: {summary['best_cagr_config']}")
    print(f"Lowest drawdown config: {summary['lowest_drawdown_config']}")
    print(f"Leaderboard rows: {len(leaderboard)}")


if __name__ == "__main__":
    main()
