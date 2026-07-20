from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.research_lab_v2 import (  # noqa: E402
    build_metric_delta_table,
    build_research_lab_v2_model,
)
from research.research_result_adapters import (  # noqa: E402
    load_canonical_results,
    load_research_results,
)
from research.research_result_schema import REQUIRED_FIELDS, validate_research_result  # noqa: E402


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    raw_canonical_results = load_canonical_results(ROOT)
    canonical_results = load_research_results(ROOT)
    assert_true(canonical_results, "canonical adapter layer produced no results")
    assert_true(raw_canonical_results, "canonical result files were not discovered")
    assert_true(
        len(canonical_results) <= len(raw_canonical_results),
        "Research Lab loader added non-canonical fallback rows despite canonical files",
    )
    for result in canonical_results:
        validate_research_result(result)
        assert_true(
            REQUIRED_FIELDS.issubset(result.keys()),
            f"canonical fields missing for {result.get('id')}",
        )

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
            item for item in experiments if "atr" in str(item.get("experiment_type"))
        ]
        campaign_rows = [
            item
            for item in experiments
            if item.get("experiment_type") == "campaign_001_exit_optimisation"
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
            "ATR canonical candidates were not loaded",
        )
        assert_true(
            campaign_rows,
            "Campaign 001 canonical variants were not loaded",
        )
        assert_true(
            not any(str(source).endswith("_adapter") for source in sources),
            "legacy adapters were loaded despite canonical result files",
        )
        assert_true(
            any("ATR trailing stop" in str(title) for title in titles),
            "human-readable ATR titles missing",
        )
        assert_true(
            {"Time exit 10 days", "Fixed stop loss 3%"}.issubset(titles),
            "human-readable Campaign 001 variant titles missing",
        )
        assert_true(
            any("ATR trailing stop p21 x3.5" in str(item.get("title")) for item in atr_rows),
            "best ATR canonical title missing",
        )
        assert_true(
            all(
                item.get("candidate_strategy") != item.get("baseline_strategy")
                for item in experiments
            ),
            "self-comparison rows leaked into actionable canonical results",
        )
        assert_true(
            all(item.get("metrics", {}).get("trade_count") is not None for item in experiments),
            "canonical trade counts were not preserved",
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
