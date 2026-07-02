from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.backtest_analytics import load_backtest_analytics
from research.experiment_registry import (
    build_leaderboard,
    create_experiment,
    load_experiments,
    save_experiment,
)


def main():
    registry_path = ROOT / "research" / "experiments" / "experiments.jsonl"
    analytics = load_backtest_analytics(ROOT)
    metrics = analytics.get("summary", {})

    experiment = create_experiment(
        name="Research Lab V1 validation dry run",
        parameter_config={
            "mode": "dry_run",
            "source": "saved_backtest_analytics",
            "production_mutation": False,
        },
        metrics={
            "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
            "total_return": metrics.get("total_return", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "trade_count": metrics.get("trade_count", 0),
        },
        status="dry_run",
        notes="Validation record created by scripts/validate_research_lab.py.",
    )
    saved = save_experiment(experiment, registry_path)
    experiments = load_experiments(registry_path)
    leaderboard = build_leaderboard(
        sort_by="sharpe_ratio",
        path=registry_path,
    )

    print("Research Lab validation passed")
    print(f"Registry: {registry_path.relative_to(ROOT)}")
    print(f"Saved experiment: {saved['experiment_id']}")
    print(f"Loaded experiments: {len(experiments)}")
    print(f"Leaderboard rows: {len(leaderboard)}")
    if not leaderboard.empty:
        top = leaderboard.iloc[0]
        print(
            "Top experiment: "
            f"{top.get('name')} | sharpe_ratio={top.get('sharpe_ratio')}"
        )


if __name__ == "__main__":
    main()
