from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.research_lab_v2 import (  # noqa: E402
    build_metric_delta_table,
    build_research_lab_v2_model,
)


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    model = build_research_lab_v2_model(ROOT)
    experiments = model["experiments"]
    summary = model["summary"]
    leaderboard = model["leaderboard"]

    assert_true(isinstance(experiments, list), "experiments must be a list")
    assert_true(summary["total"] == len(experiments), "summary total mismatch")
    assert_true("briefing" in model and model["briefing"], "briefing is missing")

    if experiments:
        assert_true(not leaderboard.empty, "leaderboard missing despite experiments")
        titles = {item.get("title") for item in experiments}
        sources = {item.get("source") for item in experiments}
        atr_rows = [
            item for item in experiments if "atr_leaderboard" in str(item.get("source"))
        ]
        campaign_rows = [
            item for item in experiments if item.get("source") == "campaign_001_report"
        ]

        assert_true(
            len(experiments) > 1,
            "Research Lab v2 only loaded one experiment; expected real candidates",
        )
        assert_true(
            "Baseline self-check" not in titles or len(experiments) == 1,
            "baseline self-check was not de-prioritised",
        )
        assert_true(
            atr_rows,
            "ATR leaderboard candidates were not loaded from research/report_exports/atr_exit_leaderboard.csv",
        )
        assert_true(
            campaign_rows,
            "Campaign 001 variants were not loaded from campaign report exports",
        )
        assert_true(
            "campaign_001_report" in sources,
            "Campaign 001 source marker missing",
        )
        assert_true(
            any("ATR trailing stop" in str(title) for title in titles),
            "human-readable ATR titles missing",
        )
        assert_true(
            {"Current binary exit", "Time exit 10 days", "Fixed stop loss 3%"}.issubset(titles),
            "human-readable Campaign 001 variant titles missing",
        )
        assert_true(
            any("trade count" in str(item.get("reason", "")).lower() for item in campaign_rows),
            "missing Campaign 001 trade count explanation was not surfaced",
        )

        required = {
            "Score",
            "Experiment",
            "Candidate Strategy",
            "Baseline Strategy",
            "CAGR Delta",
            "Sharpe Delta",
            "Max Drawdown Delta",
            "Trade Count",
            "Decision",
            "Promotion Recommendation",
            "Reason",
        }
        assert_true(required.issubset(set(leaderboard.columns)), "leaderboard columns missing")

        best = summary["best"]
        assert_true(best is not None, "best experiment missing")
        assert_true("raw return" not in str(best.get("reason", "")).lower(), "raw return used as reason")

        detail = build_metric_delta_table(best)
        assert_true(not detail.empty, "detail table is empty")
        assert_true(
            {"Metric", "Baseline", "Candidate", "Delta"}.issubset(detail.columns),
            "detail table columns missing",
        )

    print("Research Lab v2 validation passed.")


if __name__ == "__main__":
    main()
