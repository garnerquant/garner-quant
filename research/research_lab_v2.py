from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from research.experiment_registry import load_experiments as load_legacy_experiments
from research.experiment_registry import load_registry


REPORT_EXPORTS_DIR = Path("research") / "report_exports"
ATR_LEADERBOARD = REPORT_EXPORTS_DIR / "atr_exit_leaderboard.csv"


def safe_float(value, default=0.0):
    try:
        numeric = float(value)
    except Exception:
        return default
    return numeric if math.isfinite(numeric) else default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def format_percent(value):
    return f"{safe_float(value) * 100:.2f}%"


def format_number(value):
    return f"{safe_float(value):,.2f}"


def report_path_from_entry(entry, kind):
    reports = entry.get("reports") or entry.get("report_location") or {}
    value = reports.get(kind)
    return Path(value) if value else None


def experiment_title(experiment):
    candidate_name = str(
        experiment.get("candidate_name")
        or experiment.get("candidate_strategy")
        or ""
    )
    description = str(experiment.get("description") or "")
    params = experiment.get("parameters") or {}

    if candidate_name.startswith("atr_exit"):
        period = params.get("atr_period")
        multiplier = params.get("atr_multiplier")
        method = params.get("atr_method", "ATR")
        return f"ATR trailing stop p{period} x{multiplier} ({method})"

    if "baseline compared against itself" in description.lower():
        return "Baseline self-check"

    if experiment.get("name"):
        return str(experiment["name"])

    return description or str(experiment.get("experiment_id") or "Untitled experiment")


def parameter_summary(parameters):
    if not parameters:
        return "Default parameters"
    visible = []
    for key, value in parameters.items():
        if isinstance(value, (dict, list)):
            continue
        visible.append(f"{key}={value}")
    return ", ".join(visible[:6]) if visible else "Structured parameter set"


def plain_english_conclusion(experiment):
    recommendation = experiment.get("promotion_recommendation", "Needs more testing")
    reason = experiment.get("reason", "")
    candidate = experiment.get("candidate_strategy", "Candidate")
    baseline = experiment.get("baseline_strategy", "baseline")

    if recommendation == "Promote to candidate paper strategy":
        return f"{candidate} beat {baseline} on risk-aware evidence. {reason}"
    if recommendation == "Reject":
        return f"{candidate} is not ready to replace {baseline}. {reason}"
    return f"{candidate} produced mixed evidence versus {baseline}. {reason}"


def metric_delta(baseline, candidate, key):
    return safe_float(candidate.get(key)) - safe_float(baseline.get(key))


def score_experiment(baseline, candidate, comparison=None):
    comparison = comparison or {}
    sharpe_delta = metric_delta(baseline, candidate, "sharpe")
    cagr_delta = metric_delta(baseline, candidate, "cagr")
    drawdown_delta = metric_delta(baseline, candidate, "max_drawdown")
    profit_factor_delta = metric_delta(baseline, candidate, "profit_factor")
    baseline_trades = safe_int(baseline.get("number_of_trades"))
    candidate_trades = safe_int(candidate.get("number_of_trades"))

    score = 0.0
    score += sharpe_delta * 40.0
    score += cagr_delta * 100.0
    score += drawdown_delta * 80.0
    score += profit_factor_delta * 10.0

    penalties = []
    if drawdown_delta < 0:
        penalty = abs(drawdown_delta) * 120.0
        score -= penalty
        penalties.append("worse drawdown")

    if candidate_trades < 30:
        score -= 15.0
        penalties.append("low sample size")

    if baseline_trades and candidate_trades:
        trade_ratio = candidate_trades / baseline_trades
        if trade_ratio > 2.0:
            score -= 15.0
            penalties.append("excessive trade count")
        elif trade_ratio < 0.25:
            score -= 15.0
            penalties.append("too few trades")

    if abs(sharpe_delta) < 0.05 and abs(cagr_delta) < 0.02:
        score -= 8.0
        penalties.append("tiny performance delta")

    improved = comparison.get("improved_metrics") or []
    regressed = comparison.get("regressed_metrics") or []
    if len(regressed) > len(improved):
        score -= 10.0
        penalties.append("more regressions than improvements")

    return {
        "score": round(score, 2),
        "cagr_delta": cagr_delta,
        "sharpe_delta": sharpe_delta,
        "max_drawdown_delta": drawdown_delta,
        "profit_factor_delta": profit_factor_delta,
        "trade_count": candidate_trades,
        "penalties": penalties,
    }


def promotion_recommendation(decision, scoring):
    sharpe_delta = scoring["sharpe_delta"]
    cagr_delta = scoring["cagr_delta"]
    drawdown_delta = scoring["max_drawdown_delta"]
    score = scoring["score"]
    trade_count = scoring["trade_count"]

    if (
        str(decision).upper() == "KEEP"
        and score >= 15
        and sharpe_delta > 0.10
        and cagr_delta > 0.02
        and drawdown_delta >= -0.02
        and trade_count >= 30
    ):
        return "Promote to candidate paper strategy"

    if score > 0 and drawdown_delta >= -0.05 and trade_count >= 30:
        return "Needs more testing"

    return "Reject"


def recommendation_reason(scoring, recommendation):
    parts = []
    if scoring["sharpe_delta"] > 0:
        parts.append(f"Sharpe improved by {scoring['sharpe_delta']:.2f}")
    elif scoring["sharpe_delta"] < 0:
        parts.append(f"Sharpe fell by {abs(scoring['sharpe_delta']):.2f}")

    if scoring["cagr_delta"] > 0:
        parts.append(f"CAGR improved by {format_percent(scoring['cagr_delta'])}")
    elif scoring["cagr_delta"] < 0:
        parts.append(f"CAGR fell by {format_percent(abs(scoring['cagr_delta']))}")

    if scoring["max_drawdown_delta"] < 0:
        parts.append(f"drawdown worsened by {format_percent(abs(scoring['max_drawdown_delta']))}")
    elif scoring["max_drawdown_delta"] > 0:
        parts.append(f"drawdown improved by {format_percent(scoring['max_drawdown_delta'])}")

    if scoring["penalties"]:
        parts.append("penalties: " + ", ".join(scoring["penalties"]))

    if not parts:
        parts.append("there was not enough measurable improvement")

    return f"{recommendation}: " + "; ".join(parts) + "."


def normalize_report_result(result):
    baseline = result.get("baseline") or {}
    candidate = result.get("candidate") or {}
    baseline_metrics = baseline.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    comparison = result.get("comparison") or {}
    decision = result.get("decision") or result.get("result", {}).get("decision") or "NEEDS MORE TESTING"
    scoring = score_experiment(baseline_metrics, candidate_metrics, comparison)
    recommendation = promotion_recommendation(decision, scoring)
    reason = recommendation_reason(scoring, recommendation)

    experiment = {
        "experiment_id": result.get("experiment_id"),
        "date": result.get("date") or result.get("timestamp"),
        "description": result.get("description", ""),
        "hypothesis": result.get("description", "No hypothesis recorded."),
        "parameters": result.get("parameters") or {},
        "baseline_strategy": baseline.get("name", "baseline"),
        "candidate_strategy": candidate.get("name", "candidate"),
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "comparison": comparison,
        "decision": str(decision).upper(),
        "reports": result.get("reports") or result.get("report_location") or {},
        "source": "report_json",
        **scoring,
        "promotion_recommendation": recommendation,
        "reason": reason,
    }
    experiment["title"] = experiment_title(experiment)
    experiment["parameter_set"] = parameter_summary(experiment["parameters"])
    experiment["plain_conclusion"] = plain_english_conclusion(experiment)
    return experiment


def normalize_registry_entry(entry, base_path):
    json_path = report_path_from_entry(entry, "json")
    if json_path is not None:
        result = read_json(base_path / json_path)
        if result:
            return normalize_report_result(result)

    decision = entry.get("decision") or entry.get("result", {}).get("decision") or "NEEDS MORE TESTING"
    experiment = {
        "experiment_id": entry.get("experiment_id"),
        "date": entry.get("date"),
        "description": entry.get("description", ""),
        "hypothesis": entry.get("description", "No hypothesis recorded."),
        "parameters": entry.get("parameters") or {},
        "baseline_strategy": "Unknown baseline",
        "candidate_strategy": "Unknown candidate",
        "baseline_metrics": {},
        "candidate_metrics": {},
        "comparison": entry.get("result") or {},
        "decision": str(decision).upper(),
        "reports": entry.get("report_location") or {},
        "source": "framework_registry",
        "score": -8.0,
        "cagr_delta": 0.0,
        "sharpe_delta": 0.0,
        "max_drawdown_delta": 0.0,
        "profit_factor_delta": 0.0,
        "trade_count": 0,
        "penalties": ["missing detailed metrics"],
        "promotion_recommendation": "Needs more testing",
        "reason": "Needs more testing: detailed baseline and candidate metrics are unavailable.",
    }
    experiment["title"] = experiment_title(experiment)
    experiment["parameter_set"] = parameter_summary(experiment["parameters"])
    experiment["plain_conclusion"] = plain_english_conclusion(experiment)
    return experiment


def normalize_legacy_experiment(entry):
    metrics = entry.get("metrics") or {}
    experiment = {
        "experiment_id": entry.get("experiment_id"),
        "date": entry.get("timestamp"),
        "description": entry.get("notes", ""),
        "hypothesis": entry.get("notes", "Legacy research run."),
        "parameters": entry.get("parameter_config") or {},
        "baseline_strategy": "Live saved baseline",
        "candidate_strategy": entry.get("name", "Legacy experiment"),
        "baseline_metrics": {},
        "candidate_metrics": {
            "cagr": metrics.get("cagr", 0.0),
            "sharpe": metrics.get("sharpe", metrics.get("sharpe_ratio", 0.0)),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "number_of_trades": metrics.get("number_of_trades", metrics.get("trade_count", 0)),
        },
        "comparison": {},
        "decision": str(entry.get("status", "NEEDS MORE TESTING")).upper(),
        "reports": {},
        "source": "legacy_jsonl",
        "score": -5.0,
        "cagr_delta": 0.0,
        "sharpe_delta": 0.0,
        "max_drawdown_delta": 0.0,
        "profit_factor_delta": 0.0,
        "trade_count": safe_int(metrics.get("number_of_trades", metrics.get("trade_count"))),
        "penalties": ["legacy run has no baseline delta"],
        "promotion_recommendation": "Needs more testing",
        "reason": "Needs more testing: legacy record has no comparable baseline deltas.",
    }
    experiment["title"] = experiment_title(experiment)
    experiment["parameter_set"] = parameter_summary(experiment["parameters"])
    experiment["plain_conclusion"] = plain_english_conclusion(experiment)
    return experiment


def load_research_experiments(base_path="."):
    base_path = Path(base_path)
    experiments = {}

    registry = load_registry(base_path / "experiments" / "registry.json")
    for entry in registry.get("experiments", []):
        if isinstance(entry, dict):
            normalized = normalize_registry_entry(entry, base_path)
            experiments[normalized["experiment_id"]] = normalized

    for path in sorted((base_path / REPORT_EXPORTS_DIR).glob("exp_*.json")):
        result = read_json(path)
        if not result:
            continue
        normalized = normalize_report_result(result)
        experiments[normalized["experiment_id"]] = normalized

    for entry in load_legacy_experiments(base_path / "research" / "experiments" / "experiments.jsonl"):
        if isinstance(entry, dict):
            normalized = normalize_legacy_experiment(entry)
            experiment_id = normalized.get("experiment_id")
            if experiment_id and experiment_id not in experiments:
                experiments[experiment_id] = normalized

    return sorted(
        experiments.values(),
        key=lambda item: str(item.get("date") or ""),
        reverse=True,
    )


def build_research_summary(experiments):
    completed_decisions = {"KEEP", "REJECT", "NEEDS MORE TESTING", "DRY_RUN", "TESTED"}
    completed = [
        item for item in experiments if str(item.get("decision", "")).upper() in completed_decisions
    ]
    pending = [
        item
        for item in experiments
        if item.get("promotion_recommendation") == "Needs more testing"
    ]
    latest = experiments[0] if experiments else None
    best = max(experiments, key=lambda item: safe_float(item.get("score")), default=None)
    latest_recommendation = (
        latest.get("promotion_recommendation") if latest else "No experiments available"
    )

    return {
        "total": len(experiments),
        "completed": len(completed),
        "pending": len(pending),
        "latest": latest,
        "best": best,
        "latest_recommendation": latest_recommendation,
    }


def build_leaderboard(experiments):
    rows = []
    for item in experiments:
        rows.append(
            {
                "Score": item.get("score", 0.0),
                "Experiment": item.get("title"),
                "Candidate Strategy": item.get("candidate_strategy"),
                "Baseline Strategy": item.get("baseline_strategy"),
                "CAGR Delta": format_percent(item.get("cagr_delta")),
                "Sharpe Delta": format_number(item.get("sharpe_delta")),
                "Max Drawdown Delta": format_percent(item.get("max_drawdown_delta")),
                "Trade Count": item.get("trade_count", 0),
                "Decision": item.get("decision"),
                "Promotion Recommendation": item.get("promotion_recommendation"),
                "Reason": item.get("reason"),
                "experiment_id": item.get("experiment_id"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("Score", ascending=False).reset_index(drop=True)


def build_metric_delta_table(experiment):
    baseline = experiment.get("baseline_metrics") or {}
    candidate = experiment.get("candidate_metrics") or {}
    rows = []
    for key in ["cagr", "sharpe", "max_drawdown", "profit_factor", "number_of_trades"]:
        rows.append(
            {
                "Metric": key,
                "Baseline": baseline.get(key, 0),
                "Candidate": candidate.get(key, 0),
                "Delta": safe_float(candidate.get(key)) - safe_float(baseline.get(key)),
            }
        )
    return pd.DataFrame(rows)


def research_briefing(summary):
    latest = summary.get("latest")
    best = summary.get("best")
    if not latest:
        return "No research experiments have been recorded yet."

    best_text = (
        f"Best risk-aware score is {best['title']} at {best['score']:.2f}."
        if best
        else "No best experiment is available."
    )
    ready = [
        item for item in [best, latest] if item and item.get("promotion_recommendation") == "Promote to candidate paper strategy"
    ]
    promotion_text = (
        f"{ready[0]['title']} is ready for candidate paper review."
        if ready
        else "No candidate is ready for paper promotion yet."
    )
    return (
        f"{latest['title']} latest recommendation: {latest['promotion_recommendation']}. "
        f"{latest['plain_conclusion']} {best_text} {promotion_text}"
    )


def build_research_lab_v2_model(base_path="."):
    experiments = load_research_experiments(base_path)
    summary = build_research_summary(experiments)
    leaderboard = build_leaderboard(experiments)
    return {
        "experiments": experiments,
        "summary": summary,
        "leaderboard": leaderboard,
        "briefing": research_briefing(summary),
        "atr_leaderboard": read_csv(Path(base_path) / ATR_LEADERBOARD),
    }
