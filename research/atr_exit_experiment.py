from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from research.experiment_runner import run_experiment
from research.strategies.atr_exit_strategy import AtrExitParameters, AtrExitStrategy
from research.strategies.baseline_strategy import BaselineStrategy


ATR_PERIODS = [7, 10, 14, 21]
ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0, 3.5]
LEADERBOARD_SORT = ["sharpe", "cagr", "max_drawdown", "calmar", "profit_factor"]


def atr_decision(baseline_metrics, candidate_metrics, _comparison):
    sharpe_delta = candidate_metrics.get("sharpe", 0.0) - baseline_metrics.get("sharpe", 0.0)
    drawdown_delta = (
        candidate_metrics.get("max_drawdown", 0.0)
        - baseline_metrics.get("max_drawdown", 0.0)
    )
    baseline_trades = max(1, int(baseline_metrics.get("number_of_trades", 0) or 0))
    candidate_trades = int(candidate_metrics.get("number_of_trades", 0) or 0)
    trade_count_reasonable = (
        candidate_trades >= max(1, int(baseline_trades * 0.25))
        and candidate_trades <= max(2, int(baseline_trades * 2.0))
    )

    if sharpe_delta > 1e-12 and drawdown_delta >= -0.02 and trade_count_reasonable:
        return "KEEP"
    if sharpe_delta <= 0 or drawdown_delta < -0.05 or not trade_count_reasonable:
        return "REJECT"
    return "NEEDS MORE TESTING"


def parameter_grid():
    for period in ATR_PERIODS:
        for multiplier in ATR_MULTIPLIERS:
            yield AtrExitParameters(
                atr_period=period,
                atr_multiplier=multiplier,
                initial_stop=True,
                trailing_stop_enabled=True,
                break_even_trigger=0.0,
                atr_method="wilder",
            )


def result_row(result):
    candidate = result["candidate"]["metrics"]
    baseline = result["baseline"]["metrics"]
    params = result["parameters"]
    return {
        "experiment_id": result["experiment_id"],
        "decision": result["decision"],
        "atr_period": params["atr_period"],
        "atr_multiplier": params["atr_multiplier"],
        "atr_method": params["atr_method"],
        "sharpe": candidate["sharpe"],
        "cagr": candidate["cagr"],
        "max_drawdown": candidate["max_drawdown"],
        "calmar": candidate["calmar"],
        "profit_factor": candidate["profit_factor"],
        "number_of_trades": candidate["number_of_trades"],
        "sharpe_delta": candidate["sharpe"] - baseline["sharpe"],
        "cagr_delta": candidate["cagr"] - baseline["cagr"],
        "max_drawdown_delta": candidate["max_drawdown"] - baseline["max_drawdown"],
        "calmar_delta": candidate["calmar"] - baseline["calmar"],
        "profit_factor_delta": candidate["profit_factor"] - baseline["profit_factor"],
        "markdown_report": result["reports"]["markdown"],
        "json_report": result["reports"]["json"],
    }


def build_leaderboard(results):
    rows = [result_row(result) for result in results]
    leaderboard = pd.DataFrame(rows)
    if leaderboard.empty:
        return leaderboard
    return leaderboard.sort_values(
        by=LEADERBOARD_SORT,
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)


def run_atr_parameter_sweep(
    *,
    base_path=".",
    registry_path=Path("experiments") / "registry.json",
    report_dir=Path("research") / "report_exports",
    leaderboard_path=Path("research") / "report_exports" / "atr_exit_leaderboard.csv",
    summary_path=Path("research") / "report_exports" / "atr_exit_leaderboard.json",
    timestamp=None,
):
    baseline = BaselineStrategy()
    start = timestamp
    if start is None:
        start = datetime.now(timezone.utc)
    elif isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    results = []
    for index, parameters in enumerate(parameter_grid()):
        candidate = AtrExitStrategy(parameters=parameters, baseline=baseline)
        run_timestamp = start + timedelta(seconds=index)
        result = run_experiment(
            baseline=baseline,
            candidate=candidate,
            description="ATR trailing stop exit wrapper versus current baseline.",
            parameters=parameters.as_dict(),
            metadata={
                "experiment_family": "atr_exit_sweep",
                "wrapper_scope": "exit_only",
            },
            base_path=base_path,
            registry_path=registry_path,
            report_dir=report_dir,
            timestamp=run_timestamp,
            decision_fn=atr_decision,
        )
        results.append(result)

    leaderboard = build_leaderboard(results)
    if not leaderboard.empty:
        atomic_write_csv_frames({leaderboard_path: leaderboard})
    best = leaderboard.iloc[0].to_dict() if not leaderboard.empty else {}
    summary = {
        "runs": len(results),
        "ranking": LEADERBOARD_SORT,
        "best_parameter_set": {
            "atr_period": best.get("atr_period"),
            "atr_multiplier": best.get("atr_multiplier"),
            "atr_method": best.get("atr_method"),
        },
        "best_decision": best.get("decision"),
        "leaderboard_path": str(leaderboard_path),
    }
    atomic_write_json(summary, summary_path)
    return {
        "results": results,
        "leaderboard": leaderboard,
        "summary": summary,
    }
