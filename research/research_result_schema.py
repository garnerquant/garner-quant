from __future__ import annotations

import json
import math
from pathlib import Path

from execution.atomic_io import atomic_write_json


CANONICAL_SCHEMA_VERSION = 1
CANONICAL_RESULT_DIR = Path("research") / "report_exports" / "canonical_results"

REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "title",
    "experiment_type",
    "status",
    "baseline_strategy",
    "candidate_strategy",
    "parameters",
    "metrics",
    "comparison",
    "recommendation",
    "decision",
    "confidence",
    "reason",
    "risk_flags",
    "report_path",
    "created_at",
}

METRIC_FIELDS = {
    "return",
    "cagr",
    "sharpe",
    "sortino",
    "drawdown",
    "profit_factor",
    "win_rate",
    "trade_count",
}

COMPARISON_FIELDS = {
    "return_delta",
    "cagr_delta",
    "sharpe_delta",
    "drawdown_delta",
}


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


def canonical_metrics(metrics=None):
    metrics = metrics or {}
    return {
        "return": safe_float(metrics.get("return", metrics.get("total_return"))),
        "cagr": safe_float(metrics.get("cagr")),
        "sharpe": safe_float(metrics.get("sharpe", metrics.get("sharpe_ratio"))),
        "sortino": safe_float(metrics.get("sortino", metrics.get("sortino_ratio"))),
        "drawdown": safe_float(metrics.get("drawdown", metrics.get("max_drawdown"))),
        "profit_factor": safe_float(metrics.get("profit_factor")),
        "win_rate": safe_float(metrics.get("win_rate", metrics.get("win_percent"))),
        "trade_count": safe_int(
            metrics.get(
                "trade_count",
                metrics.get("number_of_trades", metrics.get("completed_trades")),
            )
        ),
    }


def canonical_comparison(baseline_metrics=None, candidate_metrics=None, comparison=None):
    baseline = canonical_metrics(baseline_metrics)
    candidate = canonical_metrics(candidate_metrics)
    supplied = comparison or {}
    deltas = supplied.get("deltas") if isinstance(supplied.get("deltas"), dict) else {}
    return {
        "return_delta": safe_float(
            supplied.get("return_delta", deltas.get("return", candidate["return"] - baseline["return"]))
        ),
        "cagr_delta": safe_float(
            supplied.get("cagr_delta", deltas.get("cagr", candidate["cagr"] - baseline["cagr"]))
        ),
        "sharpe_delta": safe_float(
            supplied.get("sharpe_delta", deltas.get("sharpe", candidate["sharpe"] - baseline["sharpe"]))
        ),
        "drawdown_delta": safe_float(
            supplied.get(
                "drawdown_delta",
                deltas.get("max_drawdown", candidate["drawdown"] - baseline["drawdown"]),
            )
        ),
        "profit_factor_delta": safe_float(
            supplied.get(
                "profit_factor_delta",
                deltas.get("profit_factor", candidate["profit_factor"] - baseline["profit_factor"]),
            )
        ),
    }


def score_research_result(metrics, comparison, risk_flags):
    score = 0.0
    score += safe_float(comparison.get("sharpe_delta")) * 40.0
    score += safe_float(comparison.get("cagr_delta")) * 100.0
    score += safe_float(comparison.get("drawdown_delta")) * 80.0
    score += safe_float(comparison.get("profit_factor_delta")) * 10.0
    score -= 5.0 * len(risk_flags or [])
    return round(score, 2)


def infer_recommendation(decision, metrics, comparison, risk_flags):
    decision = str(decision or "").upper()
    score = score_research_result(metrics, comparison, risk_flags)
    if (
        decision == "KEEP"
        and score >= 15
        and safe_float(comparison.get("sharpe_delta")) > 0.10
        and safe_float(comparison.get("cagr_delta")) > 0.02
        and safe_float(comparison.get("drawdown_delta")) >= -0.02
        and safe_int(metrics.get("trade_count")) >= 30
        and not risk_flags
    ):
        return "Promote to candidate paper strategy"
    if score > 0 and safe_int(metrics.get("trade_count")) >= 30:
        return "Needs more testing"
    if decision == "KEEP":
        return "Needs more testing"
    return "Reject"


def reason_from_result(recommendation, comparison, risk_flags):
    parts = []
    sharpe_delta = safe_float(comparison.get("sharpe_delta"))
    cagr_delta = safe_float(comparison.get("cagr_delta"))
    drawdown_delta = safe_float(comparison.get("drawdown_delta"))
    if sharpe_delta:
        direction = "improved" if sharpe_delta > 0 else "fell"
        parts.append(f"Sharpe {direction} by {abs(sharpe_delta):.2f}")
    if cagr_delta:
        direction = "improved" if cagr_delta > 0 else "fell"
        parts.append(f"CAGR {direction} by {abs(cagr_delta) * 100:.2f}%")
    if drawdown_delta:
        direction = "improved" if drawdown_delta > 0 else "worsened"
        parts.append(f"drawdown {direction} by {abs(drawdown_delta) * 100:.2f}%")
    if risk_flags:
        parts.append("risk flags: " + ", ".join(risk_flags))
    if not parts:
        parts.append("no material improvement was recorded")
    return f"{recommendation}: " + "; ".join(parts) + "."


def validate_research_result(result):
    if not isinstance(result, dict):
        raise ValueError("Research result must be a dict")
    missing = sorted(REQUIRED_FIELDS - set(result))
    if missing:
        raise ValueError(f"Research result missing fields: {', '.join(missing)}")
    if int(result["schema_version"]) != CANONICAL_SCHEMA_VERSION:
        raise ValueError("Unsupported research result schema_version")
    if not isinstance(result["parameters"], dict):
        raise ValueError("parameters must be a dict")
    if not isinstance(result["metrics"], dict):
        raise ValueError("metrics must be a dict")
    if not isinstance(result["comparison"], dict):
        raise ValueError("comparison must be a dict")
    if not isinstance(result["risk_flags"], list):
        raise ValueError("risk_flags must be a list")
    metric_missing = sorted(METRIC_FIELDS - set(result["metrics"]))
    if metric_missing:
        raise ValueError(f"metrics missing fields: {', '.join(metric_missing)}")
    comparison_missing = sorted(COMPARISON_FIELDS - set(result["comparison"]))
    if comparison_missing:
        raise ValueError(f"comparison missing fields: {', '.join(comparison_missing)}")
    return result


def make_research_result(
    *,
    id,
    title,
    experiment_type,
    status,
    baseline_strategy,
    candidate_strategy,
    parameters=None,
    metrics=None,
    baseline_metrics=None,
    comparison=None,
    recommendation=None,
    decision=None,
    confidence="medium",
    reason=None,
    risk_flags=None,
    report_path="",
    created_at="",
    source="canonical",
    extra=None,
):
    metrics = canonical_metrics(metrics)
    comparison = canonical_comparison(baseline_metrics, metrics, comparison)
    risk_flags = list(risk_flags or [])
    decision = str(decision or status or "NEEDS MORE TESTING").upper()
    recommendation = recommendation or infer_recommendation(decision, metrics, comparison, risk_flags)
    reason = reason or reason_from_result(recommendation, comparison, risk_flags)
    result = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "id": str(id),
        "title": str(title or id),
        "experiment_type": str(experiment_type or "unknown"),
        "status": str(status or decision),
        "baseline_strategy": str(baseline_strategy or "Unknown baseline"),
        "candidate_strategy": str(candidate_strategy or "Unknown candidate"),
        "parameters": parameters or {},
        "metrics": metrics,
        "comparison": comparison,
        "recommendation": recommendation,
        "decision": decision,
        "confidence": str(confidence or "medium"),
        "reason": reason,
        "risk_flags": risk_flags,
        "report_path": str(report_path or ""),
        "created_at": str(created_at or ""),
        "source": str(source or "canonical"),
        "score": score_research_result(metrics, comparison, risk_flags),
    }
    if extra:
        result["extra"] = extra
    return validate_research_result(result)


def canonical_from_experiment_result(result):
    baseline = result.get("baseline") or {}
    candidate = result.get("candidate") or {}
    reports = result.get("reports") or result.get("report_location") or {}
    report_path = reports.get("canonical") or reports.get("json") or reports.get("markdown") or ""
    candidate_name = candidate.get("name", "candidate")
    parameters = result.get("parameters") or {}
    title = str(candidate_name)
    if candidate_name.startswith("atr_exit"):
        title = (
            f"ATR trailing stop p{parameters.get('atr_period')} "
            f"x{parameters.get('atr_multiplier')} ({parameters.get('atr_method', 'ATR')})"
        )
    elif baseline.get("name") == candidate.get("name"):
        title = "Baseline self-check"
    return make_research_result(
        id=result.get("experiment_id"),
        title=title,
        experiment_type=(result.get("metadata") or {}).get("experiment_family", "framework_experiment"),
        status=result.get("decision", "NEEDS MORE TESTING"),
        baseline_strategy=baseline.get("name", "baseline"),
        candidate_strategy=candidate_name,
        parameters=parameters,
        metrics=candidate.get("metrics") or {},
        baseline_metrics=baseline.get("metrics") or {},
        comparison=result.get("comparison") or {},
        decision=result.get("decision", "NEEDS MORE TESTING"),
        confidence="high" if candidate.get("metrics") else "low",
        report_path=report_path,
        created_at=result.get("date") or result.get("timestamp") or "",
        source="framework_report",
    )


def canonical_result_path(result_id, base_dir=CANONICAL_RESULT_DIR):
    safe_id = str(result_id).replace("/", "_").replace("\\", "_")
    return Path(base_dir) / f"{safe_id}.json"


def write_canonical_result(result, base_dir=CANONICAL_RESULT_DIR):
    validate_research_result(result)
    path = canonical_result_path(result["id"], base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(result, path)
    return str(path)


def load_canonical_result(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_research_result(data)
