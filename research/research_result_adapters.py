from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.experiment_registry import load_experiments as load_legacy_experiments
from research.experiment_registry import load_registry
from research.research_result_schema import (
    canonical_from_experiment_result,
    load_canonical_result,
    make_research_result,
    safe_float,
    safe_int,
    validate_research_result,
)


REPORT_EXPORTS_DIR = Path("research") / "report_exports"
CANONICAL_RESULTS_DIR = REPORT_EXPORTS_DIR / "canonical_results"
ATR_LEADERBOARD = REPORT_EXPORTS_DIR / "atr_exit_leaderboard.csv"
CAMPAIGN_REPORT_DIRS = (
    Path("research") / "experiments" / "campaign_reports",
    REPORT_EXPORTS_DIR / "campaign_reports",
)


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


def read_text(path):
    path = Path(path)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def missing_detail_flag(source_file, fields):
    readable = ", ".join(str(field).replace("_", " ") for field in fields)
    return f"missing fields in {source_file}: {readable}"


def parameter_summary(parameters):
    if not parameters:
        return "Default parameters"
    parts = [
        f"{key}={value}"
        for key, value in parameters.items()
        if not isinstance(value, (dict, list))
    ]
    return ", ".join(parts[:6]) if parts else "Structured parameter set"


def adapt_framework_registry_entry(entry, base_path):
    reports = entry.get("report_location") or entry.get("reports") or {}
    canonical_path = reports.get("canonical")
    if canonical_path:
        path = base_path / canonical_path
        if path.exists():
            return load_canonical_result(path)

    json_path = reports.get("json")
    if json_path:
        data = read_json(base_path / json_path)
        if data:
            return canonical_from_experiment_result(data)

    decision = entry.get("decision") or entry.get("result", {}).get("decision") or "NEEDS MORE TESTING"
    result = make_research_result(
        id=entry.get("experiment_id"),
        title=entry.get("description") or "Registry experiment",
        experiment_type="framework_registry",
        status=decision,
        baseline_strategy="Unknown baseline",
        candidate_strategy="Unknown candidate",
        parameters=entry.get("parameters") or {},
        metrics={},
        baseline_metrics={},
        comparison={},
        decision=decision,
        confidence="low",
        risk_flags=[missing_detail_flag("experiments/registry.json", ["baseline_strategy", "candidate_strategy", "metrics"])],
        report_path=reports.get("markdown") or reports.get("json") or "",
        created_at=entry.get("date") or "",
        source="framework_registry_adapter",
    )
    return result


def adapt_framework_report(path):
    data = read_json(path)
    if not data:
        return None
    return canonical_from_experiment_result(data)


def adapt_atr_leaderboard_row(row):
    params = {
        "atr_period": row.get("atr_period"),
        "atr_multiplier": row.get("atr_multiplier"),
        "atr_method": row.get("atr_method", "wilder"),
    }
    metrics = {
        "cagr": safe_float(row.get("cagr")),
        "sharpe": safe_float(row.get("sharpe")),
        "drawdown": safe_float(row.get("max_drawdown")),
        "profit_factor": safe_float(row.get("profit_factor")),
        "trade_count": safe_int(row.get("number_of_trades")),
    }
    comparison = {
        "cagr_delta": safe_float(row.get("cagr_delta")),
        "sharpe_delta": safe_float(row.get("sharpe_delta")),
        "drawdown_delta": safe_float(row.get("max_drawdown_delta")),
        "profit_factor_delta": safe_float(row.get("profit_factor_delta")),
    }
    baseline_metrics = {
        "cagr": metrics["cagr"] - comparison["cagr_delta"],
        "sharpe": metrics["sharpe"] - comparison["sharpe_delta"],
        "drawdown": metrics["drawdown"] - comparison["drawdown_delta"],
        "profit_factor": metrics["profit_factor"] - comparison["profit_factor_delta"],
    }
    risk_flags = []
    if "baseline_trade_count" not in row:
        risk_flags.append(missing_detail_flag(str(ATR_LEADERBOARD), ["baseline trade_count"]))
    title = (
        f"ATR trailing stop p{params['atr_period']} "
        f"x{params['atr_multiplier']} ({params['atr_method']})"
    )
    return make_research_result(
        id=row.get("experiment_id") or f"atr_exit_p{params['atr_period']}_m{params['atr_multiplier']}",
        title=title,
        experiment_type="atr_exit_sweep",
        status=row.get("decision") or "NEEDS MORE TESTING",
        baseline_strategy="baseline_current_behaviour",
        candidate_strategy=(
            f"atr_exit_p{params['atr_period']}_m{params['atr_multiplier']}_"
            f"{params['atr_method']}"
        ),
        parameters=params,
        metrics=metrics,
        baseline_metrics=baseline_metrics,
        comparison=comparison,
        decision=row.get("decision") or "NEEDS MORE TESTING",
        confidence="medium" if risk_flags else "high",
        risk_flags=risk_flags,
        report_path=row.get("json_report") or row.get("markdown_report") or str(ATR_LEADERBOARD),
        created_at=row.get("date") or "",
        source="atr_leaderboard_adapter",
    )


def load_atr_results(base_path):
    frame = read_csv(base_path / ATR_LEADERBOARD)
    if frame.empty:
        return []
    return [adapt_atr_leaderboard_row(row.to_dict()) for _, row in frame.iterrows()]


def latest_campaign_report(base_path):
    candidates = []
    for directory in CAMPAIGN_REPORT_DIRS:
        full_dir = base_path / directory
        if full_dir.exists():
            candidates.extend(full_dir.glob("campaign_001*.md"))
    if not candidates:
        return None
    latest = [path for path in candidates if path.name.endswith("_latest.md")]
    if latest:
        return sorted(latest, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def parse_campaign_report(text):
    variants = []
    walk_forward = set()
    in_results = False
    in_walk_forward = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "## Real Simulated Results":
            in_results = True
            in_walk_forward = False
            continue
        if line == "## Walk-Forward Candidates":
            in_results = False
            in_walk_forward = True
            continue
        if line.startswith("## "):
            in_results = False
            in_walk_forward = False
        if in_walk_forward and line.startswith("- "):
            walk_forward.add(line[2:].strip())
        if not in_results or not line.startswith("- ") or ": Sharpe=" not in line:
            continue
        name, metrics_text = line[2:].split(":", 1)
        metrics = {}
        for part in metrics_text.split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            metrics[key.strip()] = value.strip().replace("%", "")
        variants.append(
            {
                "name": name.strip(),
                "metrics": {
                    "sharpe": safe_float(metrics.get("Sharpe")),
                    "cagr": safe_float(metrics.get("CAGR")) / 100,
                    "drawdown": safe_float(metrics.get("Drawdown")) / 100,
                    "profit_factor": safe_float(metrics.get("Profit Factor")),
                    "trade_count": 0,
                },
                "walk_forward": name.strip() in walk_forward,
            }
        )
    return variants


def campaign_key(name):
    return str(name).lower().replace("%", "pct").replace(" ", "_").replace("-", "_")


def adapt_campaign_variant(variant, baseline, report_path):
    metrics = variant["metrics"]
    comparison = {
        "cagr_delta": metrics["cagr"] - baseline["cagr"],
        "sharpe_delta": metrics["sharpe"] - baseline["sharpe"],
        "drawdown_delta": metrics["drawdown"] - baseline["drawdown"],
        "profit_factor_delta": metrics["profit_factor"] - baseline["profit_factor"],
    }
    risk_flags = [missing_detail_flag(str(report_path), ["trade_count"])]
    decision = "KEEP" if variant["name"] == "Current binary exit" else "NEEDS MORE TESTING"
    if variant["name"] != "Current binary exit" and comparison["sharpe_delta"] < 0 and comparison["cagr_delta"] < 0:
        decision = "REJECT"
    return make_research_result(
        id=f"campaign_001_{campaign_key(variant['name'])}",
        title=variant["name"],
        experiment_type="campaign_001_exit_optimisation",
        status=decision,
        baseline_strategy="Current binary exit",
        candidate_strategy=variant["name"],
        parameters={"campaign": "campaign_001_exit_optimisation"},
        metrics=metrics,
        baseline_metrics=baseline,
        comparison=comparison,
        decision=decision,
        confidence="low",
        risk_flags=risk_flags,
        report_path=str(report_path),
        created_at=pd.Timestamp.fromtimestamp(report_path.stat().st_mtime).isoformat(),
        source="campaign_001_adapter",
    )


def load_campaign_results(base_path):
    report_path = latest_campaign_report(base_path)
    if report_path is None:
        return []
    variants = parse_campaign_report(read_text(report_path))
    if not variants:
        return []
    baseline = next(
        (item["metrics"] for item in variants if item["name"] == "Current binary exit"),
        variants[0]["metrics"],
    )
    return [adapt_campaign_variant(variant, baseline, report_path) for variant in variants]


def adapt_legacy_jsonl(entry):
    metrics = entry.get("metrics") or {}
    risk_flags = [missing_detail_flag("research/experiments/experiments.jsonl", ["baseline metrics"])]
    return make_research_result(
        id=entry.get("experiment_id"),
        title=entry.get("name", "Legacy experiment"),
        experiment_type="legacy_jsonl",
        status=entry.get("status", "NEEDS MORE TESTING"),
        baseline_strategy="Unknown legacy baseline",
        candidate_strategy=entry.get("name", "Legacy experiment"),
        parameters=entry.get("parameter_config") or {},
        metrics=metrics,
        baseline_metrics={},
        comparison={
            "return_delta": 0.0,
            "cagr_delta": 0.0,
            "sharpe_delta": 0.0,
            "drawdown_delta": 0.0,
            "profit_factor_delta": 0.0,
        },
        decision=entry.get("status", "NEEDS MORE TESTING"),
        confidence="low",
        risk_flags=risk_flags,
        report_path="research/experiments/experiments.jsonl",
        created_at=entry.get("timestamp") or "",
        source="legacy_jsonl_adapter",
    )


def load_canonical_results(base_path):
    directory = base_path / CANONICAL_RESULTS_DIR
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        try:
            results.append(load_canonical_result(path))
        except Exception:
            continue
    return results


def _is_self_comparison(result):
    return (
        str(result.get("candidate_strategy") or "").strip()
        == str(result.get("baseline_strategy") or "").strip()
    )


def _prefer_actionable_results(results):
    values = list(results)
    actionable = [
        item
        for item in values
        if item.get("title") != "Baseline self-check" and not _is_self_comparison(item)
    ]
    if actionable:
        real_results = [
            item
            for item in actionable
            if "dry-run metrics" not in set(item.get("risk_flags") or [])
        ]
        return real_results or actionable
    return [
        item
        for item in values
        if item.get("title") != "Baseline self-check"
    ] or values


def _sort_results(results):
    return sorted(results, key=lambda item: item.get("created_at") or "", reverse=True)


def load_research_results(base_path="."):
    base_path = Path(base_path)
    canonical_results = load_canonical_results(base_path)
    if canonical_results:
        return _sort_results(_prefer_actionable_results(canonical_results))

    results = {}

    registry = load_registry(base_path / "experiments" / "registry.json")
    for entry in registry.get("experiments", []):
        if isinstance(entry, dict):
            result = adapt_framework_registry_entry(entry, base_path)
            results.setdefault(result["id"], result)

    for path in sorted((base_path / REPORT_EXPORTS_DIR).glob("exp_*.json")):
        result = adapt_framework_report(path)
        if result:
            results[result["id"]] = result

    for result in load_atr_results(base_path):
        results.setdefault(result["id"], result)

    for result in load_campaign_results(base_path):
        results[result["id"]] = result

    for entry in load_legacy_experiments(base_path / "research" / "experiments" / "experiments.jsonl"):
        if isinstance(entry, dict):
            result = adapt_legacy_jsonl(entry)
            results.setdefault(result["id"], result)

    return _sort_results(_prefer_actionable_results(results.values()))


def validate_adapted_results(results):
    for result in results:
        validate_research_result(result)
    return results
