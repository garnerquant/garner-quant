from uuid import uuid4
from itertools import product
import traceback

import pandas as pd

from research.backtest_analytics import load_backtest_analytics
from research.experiment_config import build_experiment_config
from research.experiment_registry import (
    DEFAULT_EXPERIMENTS_FILE,
    build_leaderboard,
    create_experiment,
    load_experiments,
    save_experiment,
)
from research.live_rule_backtest import run_from_saved_files
from research.parameter_schema import PARAMETER_ALIASES, supported_parameter_keys
from research.parameter_sweep import enrich_summary
from research.research_result_schema import (
    make_research_result,
    safe_float,
    safe_int,
    write_canonical_result,
)


def normalise_candidate_values(candidate_values):
    if isinstance(candidate_values, dict):
        start = float(candidate_values.get("start", 0))
        stop = float(candidate_values.get("stop", candidate_values.get("end", start)))
        step = abs(float(candidate_values.get("step", 1))) or 1.0
        values = []
        current = start
        if start <= stop:
            while current <= stop + 1e-12:
                values.append(round(current, 10))
                current += step
        else:
            while current >= stop - 1e-12:
                values.append(round(current, 10))
                current -= step
        return values

    return list(candidate_values or [])


def normalise_parameter_name(parameter_name, validate=True):
    parameter_key = PARAMETER_ALIASES.get(parameter_name, parameter_name)
    if validate and parameter_key not in supported_parameter_keys():
        supported = ", ".join(supported_parameter_keys())
        raise ValueError(
            f"Unsupported research parameter '{parameter_name}'. "
            f"Supported parameters: {supported}"
        )
    return parameter_key


def _safe_metric(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return default
    if pd.isna(value):
        return default
    return value


def _metrics_from_summary(summary):
    return {
        "sharpe_ratio": _safe_metric(summary.get("sharpe_ratio")),
        "cagr": _safe_metric(summary.get("cagr")),
        "total_return": _safe_metric(summary.get("total_return")),
        "max_drawdown": _safe_metric(summary.get("max_drawdown")),
        "sortino_ratio": _safe_metric(summary.get("sortino_ratio")),
        "profit_factor": _safe_metric(summary.get("profit_factor")),
        "trade_count": int(
            _safe_metric(
                summary.get("trade_count", summary.get("number_of_trades", 0)),
                0,
            )
        ),
    }


def _canonical_decision(metrics, baseline_metrics, status):
    if status != "completed":
        return "REJECT"
    sharpe_delta = safe_float(metrics.get("sharpe_ratio")) - safe_float(
        baseline_metrics.get("sharpe_ratio")
    )
    cagr_delta = safe_float(metrics.get("cagr")) - safe_float(baseline_metrics.get("cagr"))
    drawdown_delta = safe_float(metrics.get("max_drawdown")) - safe_float(
        baseline_metrics.get("max_drawdown")
    )
    if sharpe_delta > 0 and cagr_delta > 0 and drawdown_delta >= -0.02:
        return "NEEDS MORE TESTING"
    return "REJECT"


def _canonical_risk_flags(metrics, baseline_metrics, dry_run=False):
    flags = []
    if safe_int(metrics.get("trade_count")) < 30:
        flags.append("low sample size")
    if safe_float(metrics.get("max_drawdown")) < safe_float(
        baseline_metrics.get("max_drawdown")
    ):
        flags.append("worse drawdown")
    if dry_run:
        flags.append("dry-run metrics")
    return flags


def _canonical_reason(metrics, baseline_metrics, decision):
    sharpe_delta = safe_float(metrics.get("sharpe_ratio")) - safe_float(
        baseline_metrics.get("sharpe_ratio")
    )
    cagr_delta = safe_float(metrics.get("cagr")) - safe_float(baseline_metrics.get("cagr"))
    drawdown_delta = safe_float(metrics.get("max_drawdown")) - safe_float(
        baseline_metrics.get("max_drawdown")
    )
    return (
        f"{decision}: Sharpe delta {sharpe_delta:.3f}; "
        f"CAGR delta {cagr_delta * 100:.2f}%; "
        f"drawdown delta {drawdown_delta * 100:.2f}%."
    )


def _export_canonical_optimisation_result(
    experiment,
    *,
    experiment_type,
    title,
    baseline_metrics,
    dry_run=False,
):
    if experiment.get("status") != "completed":
        return None
    metrics = experiment.get("metrics") or {}
    decision = _canonical_decision(metrics, baseline_metrics, experiment.get("status"))
    result = make_research_result(
        id=experiment.get("experiment_id"),
        title=title,
        experiment_type=experiment_type,
        status=experiment.get("status"),
        baseline_strategy="Current binary exit",
        candidate_strategy=title,
        parameters=experiment.get("parameter_config") or {},
        metrics=metrics,
        baseline_metrics=baseline_metrics,
        decision=decision,
        confidence="low" if dry_run else "high",
        reason=_canonical_reason(metrics, baseline_metrics, decision),
        risk_flags=_canonical_risk_flags(metrics, baseline_metrics, dry_run=dry_run),
        report_path="",
        created_at=experiment.get("timestamp"),
        source="optimisation_producer",
        extra={
            "name": experiment.get("name"),
            "notes": experiment.get("notes"),
        },
    )
    return write_canonical_result(result)


def _baseline_metrics_for_run(dry_run=False, base_path="."):
    try:
        return run_research_backtest_config({}, dry_run=dry_run, base_path=base_path)
    except Exception:
        return {}


def run_research_backtest(parameter_key, value, dry_run=False, base_path="."):
    return run_research_backtest_config(
        {parameter_key: value},
        dry_run=dry_run,
        base_path=base_path,
    )


def run_research_backtest_config(parameter_config, dry_run=False, base_path="."):
    parameter_config = dict(parameter_config or {})

    if dry_run:
        analytics = load_backtest_analytics(base_path)
        metrics = _metrics_from_summary(analytics.get("summary", {}))
        numeric_values = [
            _safe_metric(value)
            for value in parameter_config.values()
            if isinstance(value, (int, float))
        ]
        numeric_total = sum(numeric_values)
        numeric_count = len(numeric_values) or 1
        metrics["sharpe_ratio"] = metrics["sharpe_ratio"] + numeric_total * 0.001
        metrics["cagr"] = metrics["cagr"] + numeric_total * 0.0005
        metrics["max_drawdown"] = (
            metrics["max_drawdown"] - (numeric_total / numeric_count) * 0.0001
        )
        return metrics

    try:
        import config as live_config
    except Exception:
        live_config = None

    experiment_config = build_experiment_config(
        live_config,
        parameter_config,
    )
    equity_curve, holdings, trade_journal, summary = run_from_saved_files(
        experiment_config=experiment_config,
    )
    enriched = enrich_summary(equity_curve, trade_journal, summary)
    metrics = _metrics_from_summary(enriched)
    metrics.update(
        {
            "equity_rows": int(len(equity_curve)),
            "holdings_rows": int(len(holdings)),
            "journal_rows": int(len(trade_journal)),
        }
    )
    return metrics


def run_parameter_sweep(
    parameter_name,
    candidate_values,
    experiment_name,
    notes="",
    path=DEFAULT_EXPERIMENTS_FILE,
    dry_run=False,
    base_path=".",
):
    parameter_key = normalise_parameter_name(parameter_name, validate=not dry_run)
    values = normalise_candidate_values(candidate_values)
    sweep_id = str(uuid4())
    saved_runs = []
    canonical_result_paths = []
    baseline_metrics = _baseline_metrics_for_run(dry_run=dry_run, base_path=base_path)

    for index, value in enumerate(values, start=1):
        status = "completed"
        metrics = {}
        run_notes = notes

        try:
            metrics = run_research_backtest(
                parameter_key,
                value,
                dry_run=dry_run,
                base_path=base_path,
            )
        except Exception as exc:
            status = "failed"
            metrics = {"error": str(exc)}
            run_notes = (
                f"{notes}\n{traceback.format_exc()}"
                if notes
                else traceback.format_exc()
            )

        experiment = create_experiment(
            name=f"{experiment_name} - {parameter_key}={value}",
            parameter_config={
                parameter_key: value,
                "sweep": {
                    "sweep_id": sweep_id,
                    "index": index,
                    "total": len(values),
                    "dry_run": bool(dry_run),
                },
            },
            metrics=metrics,
            status=status,
            notes=run_notes,
            extra_fields={
                "sweep_id": sweep_id,
                "parameter_tested": parameter_key,
                "value_tested": value,
            },
        )
        saved_experiment = save_experiment(experiment, path)
        saved_runs.append(saved_experiment)
        canonical_path = _export_canonical_optimisation_result(
            saved_experiment,
            experiment_type="parameter_sweep",
            title=f"{experiment_name} - {parameter_key}={value}",
            baseline_metrics=baseline_metrics,
            dry_run=dry_run,
        )
        if canonical_path:
            canonical_result_paths.append(canonical_path)

    return {
        "sweep_id": sweep_id,
        "parameter_tested": parameter_key,
        "experiment_name": experiment_name,
        "runs": saved_runs,
        "summary": build_sweep_summary(sweep_id, path=path),
        "leaderboard": build_sweep_leaderboard(sweep_id, path=path),
        "canonical_result_paths": canonical_result_paths,
    }


def build_sweep_leaderboard(sweep_id, path=DEFAULT_EXPERIMENTS_FILE, sort_by="sharpe_ratio"):
    leaderboard = build_leaderboard(sort_by=sort_by, path=path)
    if leaderboard.empty or "sweep_id" not in leaderboard.columns:
        return leaderboard

    return leaderboard[leaderboard["sweep_id"] == sweep_id].reset_index(drop=True)


def _best_value(frame, metric, highest=True):
    if frame.empty or metric not in frame.columns:
        return None

    values = pd.to_numeric(frame[metric], errors="coerce")
    if values.dropna().empty:
        return None

    index = values.idxmax() if highest else values.idxmin()
    value = frame.loc[index, "value_tested"]
    if hasattr(value, "item"):
        return value.item()
    return value


def build_sweep_summary(sweep_id, path=DEFAULT_EXPERIMENTS_FILE):
    experiments = [
        experiment
        for experiment in load_experiments(path)
        if experiment.get("sweep_id") == sweep_id
    ]
    leaderboard = build_sweep_leaderboard(sweep_id, path=path)
    parameter = experiments[0].get("parameter_tested") if experiments else None

    return {
        "sweep_id": sweep_id,
        "parameter_tested": parameter,
        "runs": len(experiments),
        "completed_runs": len(
            [experiment for experiment in experiments if experiment.get("status") == "completed"]
        ),
        "failed_runs": len(
            [experiment for experiment in experiments if experiment.get("status") == "failed"]
        ),
        "best_sharpe_value": _best_value(leaderboard, "sharpe_ratio", highest=True),
        "best_cagr_value": _best_value(leaderboard, "cagr", highest=True),
        "lowest_drawdown_value": _best_value(
            leaderboard,
            "max_drawdown",
            highest=True,
        ),
    }


def sweep_history(path=DEFAULT_EXPERIMENTS_FILE):
    experiments = load_experiments(path)
    sweep_ids = []
    for experiment in experiments:
        sweep_id = experiment.get("sweep_id")
        if sweep_id and sweep_id not in sweep_ids:
            sweep_ids.append(sweep_id)

    return [build_sweep_summary(sweep_id, path=path) for sweep_id in sweep_ids]


def generate_parameter_combinations(parameter_grid, dry_run=False):
    normalised = []

    for parameter_name, candidate_values in (parameter_grid or {}).items():
        parameter_key = normalise_parameter_name(parameter_name, validate=not dry_run)
        values = normalise_candidate_values(candidate_values)
        if values:
            normalised.append((parameter_key, values))

    if not normalised:
        return []

    keys = [key for key, _ in normalised]
    value_sets = [values for _, values in normalised]

    return [
        dict(zip(keys, values))
        for values in product(*value_sets)
    ]


def run_parameter_grid(
    parameter_grid,
    experiment_name,
    notes="",
    path=DEFAULT_EXPERIMENTS_FILE,
    dry_run=False,
    base_path=".",
):
    combinations = generate_parameter_combinations(parameter_grid, dry_run=dry_run)
    grid_id = str(uuid4())
    saved_runs = []
    canonical_result_paths = []
    baseline_metrics = _baseline_metrics_for_run(dry_run=dry_run, base_path=base_path)

    for index, parameter_config in enumerate(combinations, start=1):
        status = "completed"
        metrics = {}
        run_notes = notes

        try:
            metrics = run_research_backtest_config(
                parameter_config,
                dry_run=dry_run,
                base_path=base_path,
            )
        except Exception as exc:
            status = "failed"
            metrics = {"error": str(exc)}
            run_notes = (
                f"{notes}\n{traceback.format_exc()}"
                if notes
                else traceback.format_exc()
            )

        label = ", ".join(
            f"{key}={value}"
            for key, value in parameter_config.items()
        )
        experiment = create_experiment(
            name=f"{experiment_name} - {label}",
            parameter_config={
                **parameter_config,
                "grid": {
                    "grid_id": grid_id,
                    "index": index,
                    "total": len(combinations),
                    "dry_run": bool(dry_run),
                },
            },
            metrics=metrics,
            status=status,
            notes=run_notes,
            extra_fields={
                "grid_id": grid_id,
            },
        )
        saved_experiment = save_experiment(experiment, path)
        saved_runs.append(saved_experiment)
        canonical_path = _export_canonical_optimisation_result(
            saved_experiment,
            experiment_type="parameter_grid",
            title=f"{experiment_name} - {label}",
            baseline_metrics=baseline_metrics,
            dry_run=dry_run,
        )
        if canonical_path:
            canonical_result_paths.append(canonical_path)

    return {
        "grid_id": grid_id,
        "experiment_name": experiment_name,
        "runs": saved_runs,
        "summary": build_grid_summary(grid_id, path=path),
        "leaderboard": build_grid_leaderboard(grid_id, path=path),
        "canonical_result_paths": canonical_result_paths,
    }


def build_grid_leaderboard(grid_id, path=DEFAULT_EXPERIMENTS_FILE, sort_by="sharpe_ratio"):
    leaderboard = build_leaderboard(sort_by=sort_by, path=path)
    if leaderboard.empty or "grid_id" not in leaderboard.columns:
        return leaderboard

    return leaderboard[leaderboard["grid_id"] == grid_id].reset_index(drop=True)


def _best_grid_config(grid_id, metric, path=DEFAULT_EXPERIMENTS_FILE, highest=True):
    leaderboard = build_grid_leaderboard(grid_id, path=path, sort_by=metric)
    if leaderboard.empty or metric not in leaderboard.columns:
        return None

    values = pd.to_numeric(leaderboard[metric], errors="coerce")
    if values.dropna().empty:
        return None

    index = values.idxmax() if highest else values.idxmin()
    experiment_id = leaderboard.loc[index, "experiment_id"]
    for experiment in load_experiments(path):
        if experiment.get("experiment_id") == experiment_id:
            config = dict(experiment.get("parameter_config") or {})
            config.pop("grid", None)
            config.pop("sweep", None)
            return config

    return None


def build_grid_summary(grid_id, path=DEFAULT_EXPERIMENTS_FILE):
    experiments = [
        experiment
        for experiment in load_experiments(path)
        if experiment.get("grid_id") == grid_id
    ]

    return {
        "grid_id": grid_id,
        "runs": len(experiments),
        "completed_runs": len(
            [experiment for experiment in experiments if experiment.get("status") == "completed"]
        ),
        "failed_runs": len(
            [experiment for experiment in experiments if experiment.get("status") == "failed"]
        ),
        "best_sharpe_config": _best_grid_config(
            grid_id,
            "sharpe_ratio",
            path=path,
            highest=True,
        ),
        "best_cagr_config": _best_grid_config(
            grid_id,
            "cagr",
            path=path,
            highest=True,
        ),
        "lowest_drawdown_config": _best_grid_config(
            grid_id,
            "max_drawdown",
            path=path,
            highest=True,
        ),
    }


def grid_history(path=DEFAULT_EXPERIMENTS_FILE):
    experiments = load_experiments(path)
    grid_ids = []
    for experiment in experiments:
        grid_id = experiment.get("grid_id")
        if grid_id and grid_id not in grid_ids:
            grid_ids.append(grid_id)

    return [build_grid_summary(grid_id, path=path) for grid_id in grid_ids]
