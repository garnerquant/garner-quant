import json
import time
from datetime import datetime
from itertools import product
from pathlib import Path
from uuid import uuid4

import pandas as pd

from research.experiment_config import build_experiment_config
from research.live_rule_backtest import run_from_saved_files
from research.parameter_schema import supported_parameter_keys


EXPERIMENTS_FILE = Path("research/experiments.json")
SUPPORTED_PARAMETERS = supported_parameter_keys()


def load_experiments(experiments_file=EXPERIMENTS_FILE):
    path = Path(experiments_file)

    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            experiments = json.load(file)
    except Exception:
        return []

    return experiments if isinstance(experiments, list) else []


def save_experiments(experiments, experiments_file=EXPERIMENTS_FILE):
    path = Path(experiments_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(experiments, file, indent=2)


def _as_float(value, default=0):
    try:
        return float(value)
    except Exception:
        return default


def _normalise_number(value):
    value = _as_float(value)

    if value.is_integer():
        return int(value)

    return value


def parameter_values(parameter_name, specification):
    if not specification or not specification.get("enabled"):
        return []

    if parameter_name == "exit_mode":
        values = specification.get("values") or [specification.get("single")]
        return [value for value in values if value]

    mode = specification.get("mode", "Single")

    if mode == "Single":
        return [_normalise_number(specification.get("single", 0))]

    start = _as_float(specification.get("start", 0))
    end = _as_float(specification.get("end", start))
    step = abs(_as_float(specification.get("step", 1), 1)) or 1

    values = []
    current = start

    if start <= end:
        while current <= end + 1e-9:
            values.append(_normalise_number(current))
            current += step
    else:
        while current >= end - 1e-9:
            values.append(_normalise_number(current))
            current -= step

    return values


def generate_parameter_combinations(sweep_spec):
    enabled = []

    for parameter_name in SUPPORTED_PARAMETERS:
        values = parameter_values(parameter_name, sweep_spec.get(parameter_name, {}))

        if values:
            enabled.append((parameter_name, values))

    if not enabled:
        return []

    combinations = []
    names = [name for name, _ in enabled]
    value_sets = [values for _, values in enabled]

    for values in product(*value_sets):
        combinations.append(dict(zip(names, values)))

    return combinations


def _equity_records(equity_curve):
    if equity_curve is None or equity_curve.empty:
        return []

    records = []

    for _, row in equity_curve.iterrows():
        date = pd.to_datetime(row.get("date"), errors="coerce")

        records.append(
            {
                "date": str(date.date()) if not pd.isna(date) else "",
                "portfolio_value": _as_float(row.get("portfolio_value")),
                "cash": _as_float(row.get("cash")),
            }
        )

    return records


def _trade_metrics(trade_journal):
    if (
        trade_journal is None
        or trade_journal.empty
        or "action" not in trade_journal.columns
    ):
        return {
            "profit_factor": 0,
            "average_trade_pct": 0,
            "number_of_trades": 0,
        }

    sells = trade_journal[trade_journal["action"] == "SELL"].copy()

    if sells.empty:
        return {
            "profit_factor": 0,
            "average_trade_pct": 0,
            "number_of_trades": int(len(trade_journal)),
        }

    pnl = pd.to_numeric(sells["pnl"], errors="coerce").fillna(0)
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss else 0

    average_trade_pct = 0

    if "pnl_percent" in sells.columns:
        average_trade_pct = pd.to_numeric(
            sells["pnl_percent"],
            errors="coerce",
        ).dropna().mean()

    return {
        "profit_factor": float(profit_factor),
        "average_trade_pct": float(average_trade_pct)
        if not pd.isna(average_trade_pct)
        else 0,
        "number_of_trades": int(len(trade_journal)),
    }


def _equity_metrics(equity_curve):
    if equity_curve is None or equity_curve.empty:
        return {
            "cagr": 0,
            "annualised_return": 0,
            "sortino_ratio": 0,
            "current_cash": 0,
            "ending_equity": 0,
        }

    curve = equity_curve.copy()
    curve["date"] = pd.to_datetime(curve["date"], errors="coerce")
    curve = curve.dropna(subset=["date"])
    values = pd.to_numeric(curve["portfolio_value"], errors="coerce").dropna()

    if values.empty:
        return {
            "cagr": 0,
            "annualised_return": 0,
            "sortino_ratio": 0,
            "current_cash": 0,
            "ending_equity": 0,
        }

    daily_returns = values.pct_change().dropna()
    annualised_return = daily_returns.mean() * 252 if not daily_returns.empty else 0
    negative_returns = daily_returns[daily_returns < 0]
    downside_deviation = negative_returns.std()
    sortino_ratio = (
        (daily_returns.mean() / downside_deviation) * (252 ** 0.5)
        if downside_deviation and downside_deviation != 0
        else 0
    )
    elapsed_days = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days
    years = elapsed_days / 365.25 if elapsed_days > 0 else 0
    cagr = (
        (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1
        if years and values.iloc[0] > 0
        else 0
    )

    current_cash = 0

    if "cash" in curve.columns:
        cash_values = pd.to_numeric(curve["cash"], errors="coerce").dropna()
        current_cash = float(cash_values.iloc[-1]) if not cash_values.empty else 0

    return {
        "cagr": float(cagr),
        "annualised_return": float(annualised_return),
        "sortino_ratio": float(sortino_ratio),
        "current_cash": current_cash,
        "ending_equity": float(values.iloc[-1]),
    }


def enrich_summary(equity_curve, trade_journal, summary):
    result = dict(summary or {})
    result.update(_equity_metrics(equity_curve))
    result.update(_trade_metrics(trade_journal))
    result.setdefault("number_of_trades", len(trade_journal))
    result.setdefault("ending_equity", 0)
    result.setdefault("current_cash", 0)
    return result


def create_experiment(name_prefix, parameters, summary, equity_curve, metadata):
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name_bits = [
        f"{key}={value}"
        for key, value in parameters.items()
    ]

    return {
        "id": str(uuid4()),
        "name": f"{name_prefix} #{metadata['index']:03d}",
        "description": "Parameter sweep: " + ", ".join(name_bits),
        "created_timestamp": created,
        "status": "Tested",
        "parameters": parameters,
        "results": {
            "summary": summary,
            "equity_rows": metadata.get("equity_rows", 0),
            "holdings_rows": metadata.get("holdings_rows", 0),
            "journal_rows": metadata.get("journal_rows", 0),
            "experiment_config": metadata.get("experiment_config", {}),
            "equity_curve": _equity_records(equity_curve),
            "tested_timestamp": created,
            "sweep": {
                "name_prefix": name_prefix,
                "index": metadata["index"],
                "total": metadata["total"],
            },
        },
    }


def run_parameter_sweep(
    live_config,
    sweep_spec,
    name_prefix="Sweep",
    experiments_file=EXPERIMENTS_FILE,
    progress_callback=None,
):
    combinations = generate_parameter_combinations(sweep_spec)
    experiments = load_experiments(experiments_file)
    created_experiments = []
    start_time = time.time()
    total = len(combinations)

    for index, parameters in enumerate(combinations, start=1):
        experiment_config = build_experiment_config(live_config, parameters)
        equity_curve, holdings, trade_journal, summary = run_from_saved_files(
            experiment_config=experiment_config
        )
        summary = enrich_summary(equity_curve, trade_journal, summary)
        experiment = create_experiment(
            name_prefix,
            parameters,
            summary,
            equity_curve,
            {
                "index": index,
                "total": total,
                "equity_rows": len(equity_curve),
                "holdings_rows": len(holdings),
                "journal_rows": len(trade_journal),
                "experiment_config": experiment_config,
            },
        )

        experiments.append(experiment)
        created_experiments.append(experiment)
        save_experiments(experiments, experiments_file)

        elapsed = time.time() - start_time
        average = elapsed / index if index else 0
        remaining = average * (total - index)

        if progress_callback is not None:
            progress_callback(
                {
                    "current": index,
                    "total": total,
                    "experiment": experiment,
                    "elapsed_seconds": elapsed,
                    "remaining_seconds": remaining,
                }
            )

    return created_experiments
