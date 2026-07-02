from pathlib import Path
from uuid import uuid4
import traceback

import pandas as pd

from research.automated_parameter_sweep import run_research_backtest_config
from research.experiment_registry import (
    DEFAULT_EXPERIMENTS_FILE,
    build_leaderboard,
    create_experiment,
    load_experiments,
    save_experiment,
)
from research.exit_simulation import run_exit_simulation


CAMPAIGN_001_ID = "campaign_001_exit_optimisation"
CAMPAIGN_001_NAME = "Research Campaign 001 - Exit Optimisation"


CAMPAIGN_001_VARIATIONS = [
    {
        "variation_name": "Current binary exit",
        "exit_method": "current_binary_exit",
        "parameter_config": {
            "exit_mode": "signal_only",
        },
        "notes": "Baseline: binary signal exit, preserving historical entry signals.",
    },
    {
        "variation_name": "Fixed stop loss 3%",
        "exit_method": "fixed_stop_loss",
        "parameter_config": {
            "exit_mode": "stops_only",
            "stop_loss_pct": 0.03,
        },
        "notes": "Research-only fixed stop loss variant.",
    },
    {
        "variation_name": "Trailing stop 5%",
        "exit_method": "trailing_stop",
        "parameter_config": {
            "exit_mode": "stops_only",
            "trailing_stop_pct": 0.05,
        },
        "notes": "Campaign placeholder for trailing stop methodology.",
    },
    {
        "variation_name": "Confirmation exit 2 days",
        "exit_method": "confirmation_exit",
        "parameter_config": {
            "exit_mode": "signal_only",
            "exit_confirmation_days": 2,
        },
        "notes": "Campaign placeholder for delayed confirmation exits.",
    },
    {
        "variation_name": "Partial exit 50%",
        "exit_method": "partial_exit",
        "parameter_config": {
            "exit_mode": "signals_and_stops",
            "partial_exit_pct": 0.50,
        },
        "notes": "Campaign placeholder for scaling out of positions.",
    },
    {
        "variation_name": "Time exit 10 days",
        "exit_method": "time_exit",
        "parameter_config": {
            "exit_mode": "signals_and_stops",
            "max_holding_days": 10,
        },
        "notes": "Campaign placeholder for maximum holding period exits.",
    },
]


DRY_RUN_EXIT_ADJUSTMENTS = {
    "current_binary_exit": {
        "sharpe_ratio": 0.0,
        "cagr": 0.0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
    },
    "fixed_stop_loss": {
        "sharpe_ratio": 0.04,
        "cagr": 0.002,
        "max_drawdown": 0.006,
        "profit_factor": 0.08,
    },
    "trailing_stop": {
        "sharpe_ratio": 0.07,
        "cagr": 0.004,
        "max_drawdown": 0.004,
        "profit_factor": 0.12,
    },
    "confirmation_exit": {
        "sharpe_ratio": 0.03,
        "cagr": 0.003,
        "max_drawdown": -0.002,
        "profit_factor": 0.04,
    },
    "partial_exit": {
        "sharpe_ratio": 0.02,
        "cagr": -0.001,
        "max_drawdown": 0.007,
        "profit_factor": 0.05,
    },
    "time_exit": {
        "sharpe_ratio": -0.01,
        "cagr": -0.003,
        "max_drawdown": 0.003,
        "profit_factor": -0.03,
    },
}


def _metric_value(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return default
    if pd.isna(value):
        return default
    return value


def _apply_dry_run_adjustment(metrics, exit_method):
    adjusted = dict(metrics or {})
    adjustment = DRY_RUN_EXIT_ADJUSTMENTS.get(exit_method, {})

    for key, delta in adjustment.items():
        adjusted[key] = _metric_value(adjusted.get(key)) + delta

    return adjusted


def _best_row(leaderboard, metric, highest=True):
    if leaderboard.empty or metric not in leaderboard.columns:
        return None

    values = pd.to_numeric(leaderboard[metric], errors="coerce")
    if values.dropna().empty:
        return None

    index = values.idxmax() if highest else values.idxmin()
    return leaderboard.loc[index].to_dict()


def build_campaign_leaderboard(
    campaign_id,
    path=DEFAULT_EXPERIMENTS_FILE,
    sort_by="sharpe_ratio",
):
    leaderboard = build_leaderboard(sort_by=sort_by, path=path)
    if leaderboard.empty or "campaign_id" not in leaderboard.columns:
        return leaderboard

    return leaderboard[leaderboard["campaign_id"] == campaign_id].reset_index(
        drop=True,
    )


def build_campaign_summary(campaign_id, path=DEFAULT_EXPERIMENTS_FILE):
    experiments = [
        experiment
        for experiment in load_experiments(path)
        if experiment.get("campaign_id") == campaign_id
    ]
    leaderboard = build_campaign_leaderboard(campaign_id, path=path)

    return {
        "campaign_id": campaign_id,
        "campaign_name": experiments[0].get("campaign_name") if experiments else "",
        "runs": len(experiments),
        "completed_runs": len(
            [
                experiment
                for experiment in experiments
                if experiment.get("status") in {"completed", "dry_run"}
            ]
        ),
        "failed_runs": len(
            [experiment for experiment in experiments if experiment.get("status") == "failed"]
        ),
        "unsupported_runs": len(
            [
                experiment
                for experiment in experiments
                if experiment.get("status") == "unsupported"
            ]
        ),
        "dry_run_runs": len(
            [
                experiment
                for experiment in experiments
                if experiment.get("result_mode") == "dry_run"
            ]
        ),
        "real_simulation_runs": len(
            [
                experiment
                for experiment in experiments
                if experiment.get("result_mode") == "real_simulation"
            ]
        ),
        "best_sharpe": _best_row(leaderboard, "sharpe_ratio", highest=True),
        "best_cagr": _best_row(leaderboard, "cagr", highest=True),
        "best_drawdown": _best_row(leaderboard, "max_drawdown", highest=True),
        "best_profit_factor": _best_row(
            leaderboard,
            "profit_factor",
            highest=True,
        ),
    }


def campaign_history(path=DEFAULT_EXPERIMENTS_FILE):
    campaign_ids = []
    for experiment in load_experiments(path):
        campaign_id = experiment.get("campaign_id")
        if campaign_id and campaign_id not in campaign_ids:
            campaign_ids.append(campaign_id)

    return [
        build_campaign_summary(campaign_id, path=path)
        for campaign_id in campaign_ids
    ]


def campaign_report_text(summary, leaderboard, dry_run=False):
    baseline = None
    if not leaderboard.empty and "exit_method" in leaderboard.columns:
        baseline_rows = leaderboard[
            leaderboard["exit_method"] == "current_binary_exit"
        ]
        if not baseline_rows.empty:
            baseline = baseline_rows.iloc[0].to_dict()

    lines = [
        f"# {summary.get('campaign_name') or CAMPAIGN_001_NAME}",
        "",
        f"Campaign ID: {summary.get('campaign_id')}",
        f"Mode: {'dry run' if dry_run else 'real historical simulation'}",
        (
            f"Runs: {summary.get('runs')} completed={summary.get('completed_runs')} "
            f"failed={summary.get('failed_runs')} unsupported={summary.get('unsupported_runs')}"
        ),
        (
            f"Evidence split: real={summary.get('real_simulation_runs')} "
            f"dry_run={summary.get('dry_run_runs')}"
        ),
        "",
        "## Best Strategies",
    ]

    for label, key in [
        ("Sharpe", "best_sharpe"),
        ("CAGR", "best_cagr"),
        ("Drawdown", "best_drawdown"),
        ("Profit Factor", "best_profit_factor"),
    ]:
        row = summary.get(key) or {}
        lines.append(
            f"- Best {label}: {row.get('variation_name', 'Unavailable')} "
            f"({row.get('exit_method', 'unknown')})"
        )

    unsupported = []
    if not leaderboard.empty and "status" in leaderboard.columns:
        unsupported = [
            row.to_dict()
            for _, row in leaderboard.iterrows()
            if row.get("status") == "unsupported"
        ]

    lines.extend(["", "## Real Simulated Results"])
    real_rows = []
    if not leaderboard.empty and "result_mode" in leaderboard.columns:
        real_rows = [
            row.to_dict()
            for _, row in leaderboard.iterrows()
            if row.get("result_mode") == "real_simulation"
        ]
    if real_rows:
        for row in real_rows:
            lines.append(
                f"- {row.get('variation_name')}: Sharpe={_metric_value(row.get('sharpe_ratio')):.3f}, "
                f"CAGR={_metric_value(row.get('cagr')):.3%}, "
                f"Drawdown={_metric_value(row.get('max_drawdown')):.3%}, "
                f"Profit Factor={_metric_value(row.get('profit_factor')):.3f}"
            )
    else:
        lines.append("- No real simulated results in this campaign run.")

    lines.extend(["", "## Unsupported Variants"])
    if unsupported:
        for row in unsupported:
            lines.append(f"- {row.get('variation_name')}: {row.get('notes')}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Dry-Run Validation Results"])
    dry_rows = []
    if not leaderboard.empty and "result_mode" in leaderboard.columns:
        dry_rows = [
            row.to_dict()
            for _, row in leaderboard.iterrows()
            if row.get("result_mode") == "dry_run"
        ]
    if dry_rows:
        for row in dry_rows:
            lines.append(
                f"- {row.get('variation_name')}: validation-only metrics recorded."
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## What Improved"])

    if baseline:
        for _, row in leaderboard.iterrows():
            if row.get("exit_method") == "current_binary_exit":
                continue
            improved = []
            if _metric_value(row.get("sharpe_ratio")) > _metric_value(
                baseline.get("sharpe_ratio")
            ):
                improved.append("Sharpe")
            if _metric_value(row.get("cagr")) > _metric_value(baseline.get("cagr")):
                improved.append("CAGR")
            if _metric_value(row.get("max_drawdown")) > _metric_value(
                baseline.get("max_drawdown")
            ):
                improved.append("drawdown")
            if _metric_value(row.get("profit_factor")) > _metric_value(
                baseline.get("profit_factor")
            ):
                improved.append("profit factor")
            if improved:
                lines.append(
                    f"- {row.get('variation_name')}: improved {', '.join(improved)}."
                )

    lines.extend(["", "## What Became Worse"])
    if baseline:
        for _, row in leaderboard.iterrows():
            if row.get("exit_method") == "current_binary_exit":
                continue
            worse = []
            if _metric_value(row.get("sharpe_ratio")) < _metric_value(
                baseline.get("sharpe_ratio")
            ):
                worse.append("Sharpe")
            if _metric_value(row.get("cagr")) < _metric_value(baseline.get("cagr")):
                worse.append("CAGR")
            if _metric_value(row.get("max_drawdown")) < _metric_value(
                baseline.get("max_drawdown")
            ):
                worse.append("drawdown")
            if _metric_value(row.get("profit_factor")) < _metric_value(
                baseline.get("profit_factor")
            ):
                worse.append("profit factor")
            if worse:
                lines.append(
                    f"- {row.get('variation_name')}: weaker {', '.join(worse)}."
                )

    lines.extend(["", "## Walk-Forward Candidates"])
    candidates = []
    for key in ["best_sharpe", "best_cagr", "best_drawdown", "best_profit_factor"]:
        row = summary.get(key) or {}
        name = row.get("variation_name")
        if name and name not in candidates:
            candidates.append(name)

    for candidate in candidates:
        lines.append(f"- {candidate}")

    if dry_run:
        lines.extend(
            [
                "",
                "Note: this report was generated from dry-run validation metrics. "
                "Use full research backtests before drawing production conclusions.",
            ]
        )

    return "\n".join(lines) + "\n"


def save_campaign_report(
    campaign_id,
    text,
    reports_dir=Path("research") / "experiments" / "campaign_reports",
):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{campaign_id}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_campaign_001(
    path=DEFAULT_EXPERIMENTS_FILE,
    dry_run=False,
    base_path=".",
    save_report=True,
):
    campaign_run_id = f"{CAMPAIGN_001_ID}_{uuid4()}"
    saved_runs = []

    for index, variation in enumerate(CAMPAIGN_001_VARIATIONS, start=1):
        status = "dry_run" if dry_run else "completed"
        result_mode = "dry_run" if dry_run else "real_simulation"
        metrics = {}
        notes = variation["notes"]

        try:
            if dry_run:
                metrics = run_research_backtest_config(
                    variation["parameter_config"],
                    dry_run=True,
                    base_path=base_path,
                )
                metrics = _apply_dry_run_adjustment(
                    metrics,
                    variation["exit_method"],
                )
            else:
                simulation = run_exit_simulation(
                    variation["exit_method"],
                    parameter_config=variation["parameter_config"],
                    base_path=base_path,
                )
                metrics = simulation["metrics"]
        except Exception as exc:
            status = "failed"
            result_mode = "error"
            metrics = {"error": str(exc)}
            notes = f"{notes}\n{traceback.format_exc()}"

        experiment = create_experiment(
            name=f"{CAMPAIGN_001_NAME} - {variation['variation_name']}",
            parameter_config={
                **variation["parameter_config"],
                "campaign": {
                    "campaign_id": campaign_run_id,
                    "campaign_code": CAMPAIGN_001_ID,
                    "index": index,
                    "total": len(CAMPAIGN_001_VARIATIONS),
                    "dry_run": bool(dry_run),
                },
            },
            metrics=metrics,
            status=status,
            notes=notes,
            extra_fields={
                "campaign_id": campaign_run_id,
                "campaign_code": CAMPAIGN_001_ID,
                "campaign_name": CAMPAIGN_001_NAME,
                "variation_name": variation["variation_name"],
                "exit_method": variation["exit_method"],
                "result_mode": result_mode,
            },
        )
        saved_runs.append(save_experiment(experiment, path))

    summary = build_campaign_summary(campaign_run_id, path=path)
    leaderboard = build_campaign_leaderboard(campaign_run_id, path=path)
    report_text = campaign_report_text(summary, leaderboard, dry_run=dry_run)
    report_path = save_campaign_report(campaign_run_id, report_text) if save_report else None

    return {
        "campaign_id": campaign_run_id,
        "campaign_name": CAMPAIGN_001_NAME,
        "runs": saved_runs,
        "summary": summary,
        "leaderboard": leaderboard,
        "report_text": report_text,
        "report_path": report_path,
    }
