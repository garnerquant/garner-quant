from uuid import uuid4
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


def run_research_backtest(parameter_key, value, dry_run=False, base_path="."):
    if dry_run:
        analytics = load_backtest_analytics(base_path)
        metrics = _metrics_from_summary(analytics.get("summary", {}))
        numeric_value = _safe_metric(value)
        metrics["sharpe_ratio"] = metrics["sharpe_ratio"] + numeric_value * 0.001
        metrics["cagr"] = metrics["cagr"] + numeric_value * 0.0005
        metrics["max_drawdown"] = metrics["max_drawdown"] - numeric_value * 0.0001
        return metrics

    try:
        import config as live_config
    except Exception:
        live_config = None

    experiment_config = build_experiment_config(
        live_config,
        {parameter_key: value},
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
        saved_runs.append(save_experiment(experiment, path))

    return {
        "sweep_id": sweep_id,
        "parameter_tested": parameter_key,
        "experiment_name": experiment_name,
        "runs": saved_runs,
        "summary": build_sweep_summary(sweep_id, path=path),
        "leaderboard": build_sweep_leaderboard(sweep_id, path=path),
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
