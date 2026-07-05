from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.atr_exit_experiment import run_atr_parameter_sweep  # noqa: E402
from research.experiment_metrics import calculate_experiment_metrics  # noqa: E402
from research.strategies.atr_exit_strategy import AtrExitParameters, AtrExitStrategy  # noqa: E402
from research.strategies.baseline_strategy import BaselineStrategy  # noqa: E402


SCRATCH = ROOT / "data" / "atr_exit_validation"


def check(condition, message, issues):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def prepare_scratch(label):
    path = SCRATCH / label
    shutil.rmtree(path, ignore_errors=True)
    (path / "reports").mkdir(parents=True, exist_ok=True)
    return path


def buy_rows(frame):
    if frame.empty or "action" not in frame.columns:
        return pd.DataFrame()
    buys = frame[frame["action"].astype(str).str.upper().eq("BUY")].copy()
    columns = ["date", "ticker", "price", "shares", "value"]
    for column in columns:
        if column not in buys.columns:
            buys[column] = ""
    result = buys[columns].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ["price", "shares", "value"]:
        result[column] = pd.to_numeric(result[column], errors="coerce").round(10)
    return result.sort_values(columns).reset_index(drop=True)


def baseline_unchanged():
    baseline = BaselineStrategy()
    first = baseline.run(type("Context", (), {"base_path": ROOT, "metadata": {}})())
    second = baseline.run(type("Context", (), {"base_path": ROOT, "metadata": {}})())
    first_metrics = calculate_experiment_metrics(
        portfolio=first.portfolio,
        trades=first.trades,
        prices=first.prices,
        weights=first.weights,
    )
    second_metrics = calculate_experiment_metrics(
        portfolio=second.portfolio,
        trades=second.trades,
        prices=second.prices,
        weights=second.weights,
    )
    return first_metrics == second_metrics and buy_rows(first.trades).equals(buy_rows(second.trades))


def wrapper_only_affects_exits():
    context = type("Context", (), {"base_path": ROOT, "metadata": {}})()
    baseline = BaselineStrategy()
    candidate = AtrExitStrategy(
        AtrExitParameters(atr_period=14, atr_multiplier=2.0),
        baseline=baseline,
    )
    baseline_data = baseline.run(context)
    candidate_data = candidate.run(context)
    same_buys = buy_rows(baseline_data.trades).equals(buy_rows(candidate_data.trades))
    candidate_sells = candidate_data.trades[
        candidate_data.trades["action"].astype(str).str.upper().eq("SELL")
    ]
    reasons = set(candidate_sells.get("reason", pd.Series(dtype=str)).astype(str))
    return same_buys and reasons.issubset({"ATR TRAILING STOP", "END OF TEST"})


def identical_parameters_reproduce_metrics():
    context = type("Context", (), {"base_path": ROOT, "metadata": {}})()
    params = AtrExitParameters(atr_period=10, atr_multiplier=2.5)
    first = AtrExitStrategy(params).run(context)
    second = AtrExitStrategy(params).run(context)
    first_metrics = calculate_experiment_metrics(
        portfolio=first.portfolio,
        trades=first.trades,
        prices=first.prices,
        weights=first.weights,
    )
    second_metrics = calculate_experiment_metrics(
        portfolio=second.portfolio,
        trades=second.trades,
        prices=second.prices,
        weights=second.weights,
    )
    return first_metrics == second_metrics


def comparable_leaderboard(frame):
    columns = [
        "atr_period",
        "atr_multiplier",
        "atr_method",
        "decision",
        "sharpe",
        "cagr",
        "max_drawdown",
        "calmar",
        "profit_factor",
        "number_of_trades",
        "sharpe_delta",
        "cagr_delta",
        "max_drawdown_delta",
    ]
    result = frame[columns].copy()
    numeric = result.select_dtypes(include="number").columns
    for column in numeric:
        result[column] = result[column].round(12)
    return result.reset_index(drop=True)


def parameter_sweep_reproducible():
    first_root = prepare_scratch("first")
    second_root = prepare_scratch("second")
    first = run_atr_parameter_sweep(
        registry_path=first_root / "registry.json",
        report_dir=first_root / "reports",
        leaderboard_path=first_root / "leaderboard.csv",
        summary_path=first_root / "leaderboard.json",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    second = run_atr_parameter_sweep(
        registry_path=second_root / "registry.json",
        report_dir=second_root / "reports",
        leaderboard_path=second_root / "leaderboard.csv",
        summary_path=second_root / "leaderboard.json",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    try:
        return (
            len(first["leaderboard"]) == 20
            and first["summary"]["best_parameter_set"] == second["summary"]["best_parameter_set"]
            and comparable_leaderboard(first["leaderboard"]).equals(
                comparable_leaderboard(second["leaderboard"])
            )
        )
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)


def main():
    issues = []
    check(baseline_unchanged(), "baseline strategy is deterministic and unchanged", issues)
    check(wrapper_only_affects_exits(), "ATR wrapper preserves baseline BUY rows and only emits ATR exits", issues)
    check(identical_parameters_reproduce_metrics(), "identical ATR parameters produce identical metrics", issues)
    check(parameter_sweep_reproducible(), "ATR parameter sweep is reproducible", issues)

    if issues:
        print("\nATR exit strategy validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nATR exit strategy validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
