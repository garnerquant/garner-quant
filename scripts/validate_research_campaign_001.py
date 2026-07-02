from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.research_campaigns import (
    build_campaign_leaderboard,
    build_campaign_summary,
    run_campaign_001,
)


def _best_name(summary, key):
    row = summary.get(key) or {}
    return row.get("variation_name", "Unavailable")


def main():
    registry_path = ROOT / "research" / "experiments" / "experiments.jsonl"
    result = run_campaign_001(
        path=registry_path,
        dry_run=True,
        base_path=ROOT,
        save_report=True,
    )
    summary = build_campaign_summary(result["campaign_id"], path=registry_path)
    leaderboard = build_campaign_leaderboard(
        result["campaign_id"],
        path=registry_path,
    )

    print("Research Campaign 001 validation passed")
    print(f"Registry: {registry_path.relative_to(ROOT)}")
    print(f"Campaign ID: {result['campaign_id']}")
    print(f"Runs: {summary['runs']}")
    print(f"Completed: {summary['completed_runs']}")
    print(f"Failed: {summary['failed_runs']}")
    print(f"Best Sharpe: {_best_name(summary, 'best_sharpe')}")
    print(f"Best CAGR: {_best_name(summary, 'best_cagr')}")
    print(f"Best Drawdown: {_best_name(summary, 'best_drawdown')}")
    print(f"Best Profit Factor: {_best_name(summary, 'best_profit_factor')}")
    print(f"Leaderboard rows: {len(leaderboard)}")
    if result.get("report_path"):
        report_path = Path(result["report_path"])
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        print(f"Report: {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
