from __future__ import annotations

import pandas as pd

from research.research_result_adapters import load_research_results
from research.research_result_schema import safe_float, safe_int, validate_research_result


def format_percent(value):
    return f"{safe_float(value) * 100:.2f}%"


def format_number(value):
    return f"{safe_float(value):,.2f}"


def parameter_summary(parameters):
    if not parameters:
        return "Default parameters"
    parts = [
        f"{key}={value}"
        for key, value in parameters.items()
        if not isinstance(value, (dict, list))
    ]
    return ", ".join(parts[:6]) if parts else "Structured parameter set"


def plain_english_conclusion(result):
    recommendation = result.get("recommendation", "Needs more testing")
    reason = result.get("reason", "")
    candidate = result.get("candidate_strategy", "Candidate")
    baseline = result.get("baseline_strategy", "baseline")
    if recommendation == "Promote to candidate paper strategy":
        return f"{candidate} beat {baseline} on canonical research evidence. {reason}"
    if recommendation == "Reject":
        return f"{candidate} is not ready to replace {baseline}. {reason}"
    return f"{candidate} needs more testing against {baseline}. {reason}"


def is_actionable_result(result):
    return result.get("title") != "Baseline self-check"


def build_research_summary(results):
    completed_statuses = {"KEEP", "REJECT", "NEEDS MORE TESTING", "TESTED", "DRY_RUN"}
    completed = [
        item
        for item in results
        if str(item.get("decision", "")).upper() in completed_statuses
    ]
    pending = [
        item
        for item in results
        if item.get("recommendation") == "Needs more testing"
    ]
    actionable = [item for item in results if is_actionable_result(item)]
    pool = actionable or results
    latest = pool[0] if pool else None
    best = max(pool, key=lambda item: safe_float(item.get("score")), default=None)
    latest_recommendation = (
        latest.get("recommendation") if latest else "No experiments available"
    )
    return {
        "total": len(results),
        "completed": len(completed),
        "pending": len(pending),
        "latest": latest,
        "best": best,
        "latest_recommendation": latest_recommendation,
    }


def build_leaderboard(results):
    rows = []
    for item in results:
        comparison = item.get("comparison") or {}
        metrics = item.get("metrics") or {}
        rows.append(
            {
                "Score": item.get("score", 0.0),
                "Experiment": item.get("title"),
                "Candidate Strategy": item.get("candidate_strategy"),
                "Baseline Strategy": item.get("baseline_strategy"),
                "CAGR Delta": format_percent(comparison.get("cagr_delta")),
                "Sharpe Delta": format_number(comparison.get("sharpe_delta")),
                "Max Drawdown Delta": format_percent(comparison.get("drawdown_delta")),
                "Trade Count": safe_int(metrics.get("trade_count")),
                "Decision": item.get("decision"),
                "Promotion Recommendation": item.get("recommendation"),
                "Reason": item.get("reason"),
                "experiment_id": item.get("id"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("Score", ascending=False).reset_index(drop=True)


def build_metric_delta_table(result):
    metrics = result.get("metrics") or {}
    comparison = result.get("comparison") or {}
    rows = [
        {
            "Metric": "cagr",
            "Baseline": safe_float(metrics.get("cagr")) - safe_float(comparison.get("cagr_delta")),
            "Candidate": metrics.get("cagr", 0.0),
            "Delta": comparison.get("cagr_delta", 0.0),
        },
        {
            "Metric": "sharpe",
            "Baseline": safe_float(metrics.get("sharpe")) - safe_float(comparison.get("sharpe_delta")),
            "Candidate": metrics.get("sharpe", 0.0),
            "Delta": comparison.get("sharpe_delta", 0.0),
        },
        {
            "Metric": "drawdown",
            "Baseline": safe_float(metrics.get("drawdown")) - safe_float(comparison.get("drawdown_delta")),
            "Candidate": metrics.get("drawdown", 0.0),
            "Delta": comparison.get("drawdown_delta", 0.0),
        },
        {
            "Metric": "profit_factor",
            "Baseline": safe_float(metrics.get("profit_factor")) - safe_float(comparison.get("profit_factor_delta")),
            "Candidate": metrics.get("profit_factor", 0.0),
            "Delta": comparison.get("profit_factor_delta", 0.0),
        },
        {
            "Metric": "trade_count",
            "Baseline": "",
            "Candidate": metrics.get("trade_count", 0),
            "Delta": "",
        },
    ]
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
        item
        for item in [best, latest]
        if item and item.get("recommendation") == "Promote to candidate paper strategy"
    ]
    promotion_text = (
        f"{ready[0]['title']} is ready for candidate paper review."
        if ready
        else "No candidate is ready for paper promotion yet."
    )
    return (
        f"{latest['title']} latest recommendation: {latest['recommendation']}. "
        f"{plain_english_conclusion(latest)} {best_text} {promotion_text}"
    )


def enrich_for_page(result):
    validate_research_result(result)
    enriched = dict(result)
    enriched["experiment_id"] = result["id"]
    enriched["promotion_recommendation"] = result["recommendation"]
    enriched["parameter_set"] = parameter_summary(result.get("parameters") or {})
    enriched["plain_conclusion"] = plain_english_conclusion(result)
    enriched["hypothesis"] = (
        result.get("extra", {}).get("hypothesis")
        if isinstance(result.get("extra"), dict)
        else None
    ) or result.get("title", "No hypothesis recorded.")
    enriched["trade_count"] = safe_int(result.get("metrics", {}).get("trade_count"))
    enriched["risk_flags"] = list(result.get("risk_flags") or [])
    enriched["penalties"] = enriched["risk_flags"]
    enriched["reports"] = {"canonical_or_source": result.get("report_path", "")}
    return enriched


def build_research_lab_v2_model(base_path="."):
    canonical_results = load_research_results(base_path)
    results = [enrich_for_page(result) for result in canonical_results]
    summary = build_research_summary(results)
    leaderboard = build_leaderboard(results)
    return {
        "experiments": results,
        "summary": summary,
        "leaderboard": leaderboard,
        "briefing": research_briefing(summary),
    }
