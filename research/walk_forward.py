from datetime import datetime

import pandas as pd

from research.experiment_config import build_experiment_config
from research.live_rule_backtest import (
    STARTING_CASH,
    _as_datetime_index,
    _load_optional_volumes,
    load_saved_inputs,
    run_live_rule_backtest,
)
from research.parameter_sweep import enrich_summary


def _date_range_from_inputs(signals, prices, weights):
    signal_dates = _as_datetime_index(signals).index
    price_dates = _as_datetime_index(prices).index
    weight_dates = _as_datetime_index(weights).index
    dates = signal_dates.intersection(price_dates).intersection(weight_dates)
    return dates.sort_values()


def generate_walk_forward_folds(
    dates,
    training_years=3,
    testing_years=1,
    rolling=True,
):
    if len(dates) == 0:
        return []

    dates = pd.DatetimeIndex(dates).sort_values()
    start = dates.min()
    end = dates.max()
    training_offset = pd.DateOffset(years=int(training_years))
    testing_offset = pd.DateOffset(years=int(testing_years))
    folds = []
    fold_start = start

    while True:
        train_start = fold_start if rolling else start
        train_end = fold_start + training_offset
        test_start = train_end
        test_end = test_start + testing_offset

        if test_start > end:
            break

        fold_dates = dates[(dates >= test_start) & (dates < test_end)]

        if len(fold_dates) == 0:
            break

        folds.append(
            {
                "fold": len(folds) + 1,
                "train_start": str(train_start.date()),
                "train_end": str((test_start - pd.Timedelta(days=1)).date()),
                "test_start": str(test_start.date()),
                "test_end": str(min(test_end - pd.Timedelta(days=1), end).date()),
            }
        )

        fold_start = fold_start + testing_offset

        if fold_start + training_offset > end:
            break

    return folds


def _slice_by_dates(df, start, end):
    indexed = _as_datetime_index(df)
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    sliced = indexed[(indexed.index >= start) & (indexed.index <= end)]
    return sliced.reset_index().rename(columns={"index": "Date"})


def _slice_risk_levels(risk_levels, start, end):
    if risk_levels is None or risk_levels.empty:
        return risk_levels

    sliced = risk_levels.copy()
    sliced.index = pd.to_datetime(sliced.index, errors="coerce")
    sliced = sliced[sliced.index.notna()]
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    return sliced[(sliced.index >= start) & (sliced.index <= end)]


def _equity_records(equity_curve):
    if equity_curve is None or equity_curve.empty:
        return []

    records = []

    for _, row in equity_curve.iterrows():
        date = pd.to_datetime(row.get("date"), errors="coerce")
        records.append(
            {
                "date": str(date.date()) if not pd.isna(date) else "",
                "portfolio_value": float(row.get("portfolio_value", 0)),
                "cash": float(row.get("cash", 0)),
            }
        )

    return records


def _fold_row(fold, summary):
    return {
        "Fold": fold["fold"],
        "Train Start": fold["train_start"],
        "Train End": fold["train_end"],
        "Test Start": fold["test_start"],
        "Test End": fold["test_end"],
        "Return": summary.get("total_return", 0),
        "CAGR": summary.get("cagr", 0),
        "Sharpe Ratio": summary.get("sharpe_ratio", 0),
        "Sortino Ratio": summary.get("sortino_ratio", 0),
        "Max Drawdown": summary.get("max_drawdown", 0),
        "Win Rate": summary.get("win_rate", 0),
        "Profit Factor": summary.get("profit_factor", 0),
        "Number of Trades": summary.get("number_of_trades", 0),
    }


def _safe_mean(series):
    series = pd.to_numeric(series, errors="coerce").dropna()
    return float(series.mean()) if not series.empty else 0


def _safe_std(series):
    series = pd.to_numeric(series, errors="coerce").dropna()
    return float(series.std()) if len(series) > 1 else 0


def _stability_metrics(fold_results):
    if fold_results.empty:
        return {
            "average_return": 0,
            "return_std": 0,
            "sharpe_std": 0,
            "drawdown_std": 0,
            "best_fold": None,
            "worst_fold": None,
            "consistency_score": 0,
        }

    positive_folds = (fold_results["Return"] > 0).sum()
    consistency_score = positive_folds / len(fold_results) if len(fold_results) else 0
    best_fold = int(fold_results.sort_values("Return", ascending=False).iloc[0]["Fold"])
    worst_fold = int(fold_results.sort_values("Return", ascending=True).iloc[0]["Fold"])

    return {
        "average_return": _safe_mean(fold_results["Return"]),
        "return_std": _safe_std(fold_results["Return"]),
        "sharpe_std": _safe_std(fold_results["Sharpe Ratio"]),
        "drawdown_std": _safe_std(fold_results["Max Drawdown"]),
        "best_fold": best_fold,
        "worst_fold": worst_fold,
        "consistency_score": float(consistency_score),
    }


def _assessment(fold_results, stability):
    reasons = []

    if fold_results.empty:
        return {
            "status": "Failed",
            "reasons": ["No walk-forward folds were available."],
        }

    if stability["average_return"] > 0:
        reasons.append("Average fold return was positive.")
    else:
        reasons.append("Average fold return was not positive.")

    if stability["consistency_score"] >= 0.6:
        reasons.append("Most folds produced positive returns.")
    else:
        reasons.append("Returns were inconsistent across folds.")

    worst_drawdown = fold_results["Max Drawdown"].min()

    if worst_drawdown >= -0.25:
        reasons.append("Maximum drawdown remained within the research threshold.")
    else:
        reasons.append("At least one fold exceeded the drawdown threshold.")

    average_sharpe = _safe_mean(fold_results["Sharpe Ratio"])

    if average_sharpe > 0:
        reasons.append("Average Sharpe ratio was positive.")
    else:
        reasons.append("Average Sharpe ratio was not positive.")

    passed = (
        stability["average_return"] > 0
        and stability["consistency_score"] >= 0.6
        and worst_drawdown >= -0.25
        and average_sharpe > 0
    )

    return {
        "status": "Passed" if passed else "Failed",
        "reasons": reasons,
    }


def _combined_equity_curve(fold_curves):
    rows = []

    for fold in fold_curves:
        for row in fold["equity_curve"]:
            rows.append(
                {
                    "date": row["date"],
                    "portfolio_value": row["portfolio_value"],
                    "fold": f"Fold {fold['fold']}",
                }
            )

    return rows


def run_walk_forward_validation(
    live_config,
    experiment,
    training_years=3,
    testing_years=1,
    rolling=True,
    starting_cash=STARTING_CASH,
):
    signals, prices, weights, risk_levels = load_saved_inputs()
    volumes = _load_optional_volumes()
    dates = _date_range_from_inputs(signals, prices, weights)
    folds = generate_walk_forward_folds(
        dates,
        training_years=training_years,
        testing_years=testing_years,
        rolling=rolling,
    )
    experiment_config = build_experiment_config(
        live_config,
        experiment.get("parameters", {}),
    )
    fold_rows = []
    fold_curves = []

    for fold in folds:
        test_signals = _slice_by_dates(signals, fold["test_start"], fold["test_end"])
        test_prices = _slice_by_dates(prices, fold["test_start"], fold["test_end"])
        test_weights = _slice_by_dates(weights, fold["test_start"], fold["test_end"])
        test_risk = _slice_risk_levels(
            risk_levels,
            fold["test_start"],
            fold["test_end"],
        )
        test_volumes = (
            _slice_by_dates(volumes, fold["test_start"], fold["test_end"])
            if volumes is not None
            else None
        )

        equity_curve, holdings, trade_journal, summary = run_live_rule_backtest(
            test_signals,
            test_prices,
            test_weights,
            test_risk,
            starting_cash=starting_cash,
            experiment_config=experiment_config,
            volumes=test_volumes,
        )
        summary = enrich_summary(equity_curve, trade_journal, summary)
        fold_rows.append(_fold_row(fold, summary))
        fold_curves.append(
            {
                "fold": fold["fold"],
                "equity_curve": _equity_records(equity_curve),
                "summary": summary,
            }
        )

    fold_results = pd.DataFrame(fold_rows)
    stability = _stability_metrics(fold_results)
    assessment = _assessment(fold_results, stability)

    return {
        "status": assessment["status"],
        "date_completed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "configuration": {
            "training_years": int(training_years),
            "testing_years": int(testing_years),
            "rolling": bool(rolling),
        },
        "fold_results": fold_results.to_dict("records"),
        "fold_curves": fold_curves,
        "combined_equity_curve": _combined_equity_curve(fold_curves),
        "averages": {
            "return": _safe_mean(fold_results.get("Return", pd.Series(dtype=float))),
            "cagr": _safe_mean(fold_results.get("CAGR", pd.Series(dtype=float))),
            "sharpe_ratio": _safe_mean(
                fold_results.get("Sharpe Ratio", pd.Series(dtype=float))
            ),
            "sortino_ratio": _safe_mean(
                fold_results.get("Sortino Ratio", pd.Series(dtype=float))
            ),
            "max_drawdown": _safe_mean(
                fold_results.get("Max Drawdown", pd.Series(dtype=float))
            ),
            "win_rate": _safe_mean(fold_results.get("Win Rate", pd.Series(dtype=float))),
            "profit_factor": _safe_mean(
                fold_results.get("Profit Factor", pd.Series(dtype=float))
            ),
            "number_of_trades": _safe_mean(
                fold_results.get("Number of Trades", pd.Series(dtype=float))
            ),
        },
        "stability": stability,
        "assessment": assessment,
    }
