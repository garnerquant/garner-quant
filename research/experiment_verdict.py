from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    direction: str
    weight: float
    tolerance: float = 1e-6


METRICS = [
    MetricDefinition("total_return", "Total Return", "higher", 3.0, 0.0025),
    MetricDefinition("sharpe_ratio", "Sharpe Ratio", "higher", 2.5, 0.025),
    MetricDefinition("sortino_ratio", "Sortino Ratio", "higher", 2.0, 0.025),
    MetricDefinition("profit_factor", "Profit Factor", "higher", 2.0, 0.025),
    MetricDefinition("max_drawdown", "Max Drawdown", "higher", 1.5, 0.0025),
    MetricDefinition("win_rate", "Win Rate", "higher", 1.0, 0.0025),
    MetricDefinition("average_trade_pct", "Average Trade %", "higher", 1.5, 0.0005),
    MetricDefinition("average_holding_period", "Average Holding Days", "lower", 0.25, 0.25),
    MetricDefinition("completed_trades", "Completed Trades", "higher", 0.5, 1.0),
    MetricDefinition("ending_equity", "Ending Equity", "higher", 2.0, 1.0),
]

RULE_KEYS = [
    "technical_score_threshold",
    "max_positions",
    "position_size",
    "stop_loss_pct",
    "take_profit_pct",
    "min_volume",
    "exit_mode",
]

PARAMETER_ALIASES = {
    "Technical score threshold": "technical_score_threshold",
    "Technical Score Threshold": "technical_score_threshold",
    "Maximum positions": "max_positions",
    "Max Positions": "max_positions",
    "Position size": "position_size",
    "Position Size": "position_size",
    "Stop loss %": "stop_loss_pct",
    "Stop Loss %": "stop_loss_pct",
    "Take profit %": "take_profit_pct",
    "Take Profit %": "take_profit_pct",
    "Minimum volume": "min_volume",
    "Minimum Volume": "min_volume",
    "Exit mode": "exit_mode",
    "Exit Mode": "exit_mode",
}


def _summary(experiment: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(experiment, dict):
        return {}

    if "summary" in experiment and isinstance(experiment["summary"], dict):
        return experiment["summary"]

    return experiment.get("results", {}).get("summary", {}) or {}


def _config(experiment: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(experiment, dict):
        return {}

    result_config = experiment.get("results", {}).get("experiment_config", {})
    if isinstance(result_config, dict) and result_config:
        return result_config

    parameters = experiment.get("parameters", {})
    if not isinstance(parameters, dict):
        return {}

    config = {}
    for key, value in parameters.items():
        canonical_key = PARAMETER_ALIASES.get(key, key)
        config[canonical_key] = value

    return config


def _name(experiment: dict[str, Any] | None, fallback: str) -> str:
    if not isinstance(experiment, dict):
        return fallback

    return str(experiment.get("name") or fallback)


def _to_float(value: Any) -> float | None:
    if value in (None, "", "Not available"):
        return None

    try:
        return float(value)
    except Exception:
        return None


def _compare_metric(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
    definition: MetricDefinition,
) -> dict[str, Any]:
    baseline_value = _to_float(baseline_summary.get(definition.key))
    candidate_value = _to_float(candidate_summary.get(definition.key))

    result = {
        "metric": definition.label,
        "key": definition.key,
        "baseline": baseline_value,
        "candidate": candidate_value,
        "delta": None,
        "outcome": "Unavailable",
        "direction": definition.direction,
        "weight": definition.weight,
    }

    if baseline_value is None or candidate_value is None:
        return result

    delta = candidate_value - baseline_value
    result["delta"] = delta

    if abs(delta) <= definition.tolerance:
        result["outcome"] = "Unchanged"
        return result

    if definition.direction == "higher":
        result["outcome"] = "Improved" if delta > 0 else "Worsened"
    else:
        result["outcome"] = "Improved" if delta < 0 else "Worsened"

    return result


def _parameter_changes(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    baseline_config = _config(baseline)
    candidate_config = _config(candidate)
    changes = []

    for key in RULE_KEYS:
        baseline_value = baseline_config.get(key)
        candidate_value = candidate_config.get(key)

        if str(baseline_value) == str(candidate_value):
            continue

        changes.append(
            {
                "parameter": key,
                "baseline": baseline_value,
                "candidate": candidate_value,
            }
        )

    return changes


def _score(comparisons: list[dict[str, Any]]) -> float:
    score = 0.0

    for comparison in comparisons:
        if comparison["outcome"] == "Improved":
            score += comparison["weight"]
        elif comparison["outcome"] == "Worsened":
            score -= comparison["weight"]

    return score


def _confidence(score: float, completed_trades: float | None, comparisons: list[dict[str, Any]]) -> str:
    available = [row for row in comparisons if row["outcome"] != "Unavailable"]
    improved = sum(1 for row in available if row["outcome"] == "Improved")
    worsened = sum(1 for row in available if row["outcome"] == "Worsened")
    aligned = max(improved, worsened) / len(available) if available else 0

    if completed_trades is not None and completed_trades >= 100 and abs(score) >= 5 and aligned >= 0.6:
        return "High"

    if completed_trades is not None and completed_trades >= 30 and abs(score) >= 2:
        return "Medium"

    return "Low"


def _verdict(score: float, confidence: str, completed_trades: float | None) -> str:
    if completed_trades is not None and completed_trades < 30:
        return "Needs More Testing"

    if score >= 7 and confidence in {"Medium", "High"}:
        return "Highly Promising"

    if score >= 2:
        return "Promising"

    if score <= -3 and confidence in {"Medium", "High"}:
        return "Not Recommended"

    if score <= -1:
        return "Needs More Testing"

    return "Neutral"


def _sentence_for_metric(row: dict[str, Any]) -> str:
    baseline = row["baseline"]
    candidate = row["candidate"]

    if baseline is None or candidate is None:
        return f"{row['metric']} was unavailable for one or both experiments."

    if row["outcome"] == "Improved":
        direction = "improved"
    elif row["outcome"] == "Worsened":
        direction = "worsened"
    elif row["outcome"] == "Unchanged":
        direction = "was unchanged"
    else:
        direction = "changed"

    if direction == "was unchanged":
        return f"{row['metric']} was unchanged at {candidate:.4g}."

    return (
        f"{row['metric']} {direction} from {baseline:.4g} "
        f"to {candidate:.4g}."
    )


def _suggestion(
    verdict: str,
    parameter_changes: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> str:
    worsened = [row for row in comparisons if row["outcome"] == "Worsened"]
    improved = [row for row in comparisons if row["outcome"] == "Improved"]

    if not parameter_changes:
        return "Re-run with a labelled parameter change before drawing a strategy conclusion."

    if len(parameter_changes) == 1:
        change = parameter_changes[0]
        parameter = change["parameter"]
        baseline = change["baseline"]
        candidate = change["candidate"]

        try:
            baseline_number = float(baseline)
            candidate_number = float(candidate)
            low = min(baseline_number, candidate_number)
            high = max(baseline_number, candidate_number)
            step = max(abs(candidate_number - baseline_number) / 4, 0.01)
            range_text = f"{low:g} to {high:g}, step {step:g}"
        except Exception:
            range_text = f"{baseline} and {candidate}"

        if verdict in {"Not Recommended", "Needs More Testing"} and worsened:
            return (
                f"Run a parameter sweep for {parameter} across {range_text} "
                "to test whether an intermediate value avoids the deterioration."
            )

        if improved:
            return (
                f"Validate nearby {parameter} values across {range_text}, then run "
                "walk-forward testing before considering promotion."
            )

    changed = ", ".join(change["parameter"] for change in parameter_changes)
    return (
        f"Run a focused sweep around the changed parameters ({changed}) and separate "
        "single-parameter tests to isolate which rule caused the result."
    )


def generate_experiment_verdict(
    baseline_experiment: dict[str, Any],
    candidate_experiment: dict[str, Any],
) -> dict[str, Any]:
    """Compare two research experiments and return a research-only verdict."""
    baseline_summary = _summary(baseline_experiment)
    candidate_summary = _summary(candidate_experiment)
    comparisons = [
        _compare_metric(baseline_summary, candidate_summary, definition)
        for definition in METRICS
    ]
    parameter_changes = _parameter_changes(baseline_experiment, candidate_experiment)
    score = _score(comparisons)
    completed_trades = _to_float(candidate_summary.get("completed_trades"))
    confidence = _confidence(score, completed_trades, comparisons)
    verdict = _verdict(score, confidence, completed_trades)

    strengths = [
        _sentence_for_metric(row)
        for row in comparisons
        if row["outcome"] == "Improved"
    ]
    weaknesses = [
        _sentence_for_metric(row)
        for row in comparisons
        if row["outcome"] == "Worsened"
    ]

    if not strengths:
        strengths = ["No material metric improvements were detected."]

    if not weaknesses:
        weaknesses = ["No material metric deterioration was detected."]

    key_evidence = []
    for key in ["total_return", "sharpe_ratio", "max_drawdown", "profit_factor", "completed_trades"]:
        row = next((item for item in comparisons if item["key"] == key), None)
        if row is not None:
            key_evidence.append(_sentence_for_metric(row))

    summary = _build_summary(verdict, comparisons, parameter_changes)

    return {
        "baseline_name": _name(baseline_experiment, "Baseline"),
        "candidate_name": _name(candidate_experiment, "Candidate"),
        "verdict": verdict,
        "confidence": confidence,
        "score": score,
        "summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "evidence": key_evidence,
        "suggested_next_experiment": _suggestion(
            verdict,
            parameter_changes,
            comparisons,
        ),
        "parameter_changes": parameter_changes,
        "metric_comparisons": comparisons,
    }


def _build_summary(
    verdict: str,
    comparisons: list[dict[str, Any]],
    parameter_changes: list[dict[str, Any]],
) -> str:
    return_row = next((row for row in comparisons if row["key"] == "total_return"), None)
    sharpe_row = next((row for row in comparisons if row["key"] == "sharpe_ratio"), None)
    drawdown_row = next((row for row in comparisons if row["key"] == "max_drawdown"), None)

    change_text = "the tested parameter changes"
    if len(parameter_changes) == 1:
        change = parameter_changes[0]
        change_text = (
            f"{change['parameter']} changed from "
            f"{change['baseline']} to {change['candidate']}"
        )
    elif parameter_changes:
        change_text = f"{len(parameter_changes)} parameter changes"

    if verdict in {"Highly Promising", "Promising"}:
        return (
            f"{change_text} improved the overall research profile. "
            f"{_sentence_for_metric(return_row)} {_sentence_for_metric(sharpe_row)}"
        )

    if verdict == "Not Recommended":
        return (
            f"{change_text} weakened the overall research profile. "
            f"{_sentence_for_metric(return_row)} {_sentence_for_metric(sharpe_row)} "
            f"{_sentence_for_metric(drawdown_row)}"
        )

    if verdict == "Needs More Testing":
        return (
            f"{change_text} produced mixed or low-sample evidence. "
            "Treat this as a research lead, not a promotion candidate."
        )

    return (
        f"{change_text} did not materially change the measured research profile."
    )
