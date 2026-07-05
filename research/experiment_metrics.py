from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

try:
    from config import BENCHMARK_TICKER
except Exception:
    BENCHMARK_TICKER = "SPY"


TRADING_DAYS = 252


METRIC_KEYS = [
    "return",
    "cagr",
    "annualised_return",
    "volatility",
    "sharpe",
    "sortino",
    "calmar",
    "max_drawdown",
    "win_percent",
    "profit_factor",
    "expectancy",
    "average_winner",
    "average_loser",
    "average_hold_time",
    "number_of_trades",
    "turnover",
    "exposure",
    "benchmark_return",
    "benchmark_alpha",
]


HIGHER_IS_BETTER = {
    "return": True,
    "cagr": True,
    "annualised_return": True,
    "volatility": False,
    "sharpe": True,
    "sortino": True,
    "calmar": True,
    "max_drawdown": True,
    "win_percent": True,
    "profit_factor": True,
    "expectancy": True,
    "average_winner": True,
    "average_loser": True,
    "average_hold_time": False,
    "number_of_trades": None,
    "turnover": False,
    "exposure": None,
    "benchmark_return": True,
    "benchmark_alpha": True,
}


def safe_float(value, default=0.0):
    try:
        numeric = float(value)
    except Exception:
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def normalise_equity_curve(portfolio):
    if portfolio is None or portfolio.empty:
        return pd.DataFrame(columns=["date", "equity", "daily_return", "drawdown"])

    frame = portfolio.copy()
    if "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce")
    else:
        dates = pd.to_datetime(frame.index, errors="coerce")

    equity_column = None
    for candidate in ["equity", "portfolio_value", "value", "ending_value"]:
        if candidate in frame.columns:
            equity_column = candidate
            break
    if equity_column is None:
        return pd.DataFrame(columns=["date", "equity", "daily_return", "drawdown"])

    result = pd.DataFrame(
        {
            "date": dates,
            "equity": pd.to_numeric(frame[equity_column], errors="coerce"),
        }
    ).dropna(subset=["date", "equity"])
    result = result.sort_values("date").reset_index(drop=True)

    if "daily_return" in frame.columns:
        result["daily_return"] = pd.to_numeric(
            frame.loc[result.index, "daily_return"],
            errors="coerce",
        )
    else:
        result["daily_return"] = result["equity"].pct_change().fillna(0.0)

    if "drawdown" in frame.columns:
        result["drawdown"] = pd.to_numeric(
            frame.loc[result.index, "drawdown"],
            errors="coerce",
        )
    else:
        peak = result["equity"].cummax()
        result["drawdown"] = (result["equity"] / peak) - 1

    result["daily_return"] = result["daily_return"].fillna(0.0)
    result["drawdown"] = result["drawdown"].fillna(0.0)
    return result


def elapsed_years(curve):
    if curve.empty:
        return 0.0
    days = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days
    if days > 0:
        return days / 365.25
    return max((len(curve) - 1) / TRADING_DAYS, 0.0)


def normalise_trades(trades):
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["pnl", "holding_days"])

    frame = trades.copy()
    if "action" in frame.columns:
        actions = frame["action"].astype(str).str.upper()
        sells = frame[actions.eq("SELL")].copy()
        if not sells.empty:
            frame = sells

    if "pnl" not in frame.columns:
        frame["pnl"] = 0.0
    frame["pnl"] = pd.to_numeric(frame["pnl"], errors="coerce").fillna(0.0)

    if "holding_days" not in frame.columns:
        if {"entry_date", "exit_date"}.issubset(frame.columns):
            entry = pd.to_datetime(frame["entry_date"], errors="coerce")
            exit_ = pd.to_datetime(frame["exit_date"], errors="coerce")
            frame["holding_days"] = (exit_ - entry).dt.total_seconds() / 86400
        else:
            frame["holding_days"] = pd.NA
    frame["holding_days"] = pd.to_numeric(frame["holding_days"], errors="coerce")
    return frame.reset_index(drop=True)


def benchmark_return_for_curve(curve, prices, benchmark_ticker=BENCHMARK_TICKER):
    if prices is None or prices.empty or benchmark_ticker not in prices.columns:
        return None
    if curve.empty:
        return None

    benchmark = prices.copy()
    if "date" in benchmark.columns:
        benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
    else:
        benchmark["date"] = pd.to_datetime(benchmark.index, errors="coerce")

    benchmark = benchmark.dropna(subset=["date"])
    benchmark = benchmark[
        (benchmark["date"] >= curve["date"].iloc[0])
        & (benchmark["date"] <= curve["date"].iloc[-1])
    ]
    values = pd.to_numeric(benchmark[benchmark_ticker], errors="coerce").dropna()
    if len(values) < 2 or values.iloc[0] <= 0:
        return None
    return float((values.iloc[-1] / values.iloc[0]) - 1)


def calculate_turnover(weights):
    if weights is None or weights.empty:
        return 0.0
    numeric = weights.select_dtypes(include="number")
    if numeric.empty:
        return 0.0
    return float(numeric.diff().abs().sum(axis=1).fillna(0.0).mean() / 2)


def calculate_exposure(weights, curve):
    if weights is not None and not weights.empty:
        numeric = weights.select_dtypes(include="number")
        if not numeric.empty:
            return float(numeric.gt(0).any(axis=1).mean())
    if curve.empty:
        return 0.0
    return float(curve["daily_return"].ne(0).mean())


def calculate_experiment_metrics(
    *,
    portfolio,
    trades=None,
    prices=None,
    weights=None,
    benchmark_ticker=BENCHMARK_TICKER,
):
    curve = normalise_equity_curve(portfolio)
    trades = normalise_trades(trades)

    if curve.empty or len(curve) < 2:
        return {key: 0.0 for key in METRIC_KEYS}

    starting_value = safe_float(curve["equity"].iloc[0])
    ending_value = safe_float(curve["equity"].iloc[-1])
    total_return = (ending_value / starting_value) - 1 if starting_value > 0 else 0.0
    years = elapsed_years(curve)
    cagr = (
        (ending_value / starting_value) ** (1 / years) - 1
        if years > 0 and starting_value > 0
        else 0.0
    )
    returns = pd.to_numeric(curve["daily_return"], errors="coerce").dropna()
    volatility = float(returns.std() * math.sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0
    annualised_return = float(returns.mean() * TRADING_DAYS) if len(returns) else 0.0
    sharpe = (
        float((returns.mean() / returns.std()) * math.sqrt(TRADING_DAYS))
        if len(returns) > 1 and returns.std() != 0
        else 0.0
    )
    downside = returns[returns < 0]
    sortino = (
        float((returns.mean() / downside.std()) * math.sqrt(TRADING_DAYS))
        if len(downside) > 1 and downside.std() != 0
        else 0.0
    )
    max_drawdown = float(pd.to_numeric(curve["drawdown"], errors="coerce").min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0

    pnl = pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    gross_profit = float(winners.sum())
    gross_loss = float(abs(losers.sum()))
    number_of_trades = int(len(pnl))
    win_percent = float((pnl > 0).mean()) if number_of_trades else 0.0
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0
    expectancy = float(pnl.mean()) if number_of_trades else 0.0
    average_winner = float(winners.mean()) if not winners.empty else 0.0
    average_loser = float(losers.mean()) if not losers.empty else 0.0
    holding = pd.to_numeric(trades.get("holding_days", pd.Series(dtype=float)), errors="coerce").dropna()
    average_hold_time = float(holding.mean()) if not holding.empty else 0.0

    benchmark_return = benchmark_return_for_curve(curve, prices, benchmark_ticker)
    benchmark_return = 0.0 if benchmark_return is None else benchmark_return

    metrics = {
        "return": float(total_return),
        "cagr": float(cagr),
        "annualised_return": float(annualised_return),
        "volatility": float(volatility),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "max_drawdown": float(max_drawdown),
        "win_percent": float(win_percent),
        "profit_factor": float(profit_factor),
        "expectancy": float(expectancy),
        "average_winner": float(average_winner),
        "average_loser": float(average_loser),
        "average_hold_time": float(average_hold_time),
        "number_of_trades": int(number_of_trades),
        "turnover": calculate_turnover(weights),
        "exposure": calculate_exposure(weights, curve),
        "benchmark_return": float(benchmark_return),
        "benchmark_alpha": float(total_return - benchmark_return),
    }
    return {key: metrics.get(key, 0.0) for key in METRIC_KEYS}


def compare_metrics(baseline, candidate, tolerance=1e-12):
    deltas = {}
    improved = []
    regressed = []
    unchanged = []

    for key in METRIC_KEYS:
        base = safe_float(baseline.get(key))
        cand = safe_float(candidate.get(key))
        delta = cand - base
        deltas[key] = delta
        direction = HIGHER_IS_BETTER.get(key)
        if abs(delta) <= tolerance or direction is None:
            unchanged.append(key)
        elif (delta > 0 and direction) or (delta < 0 and not direction):
            improved.append(key)
        else:
            regressed.append(key)

    return {
        "deltas": deltas,
        "improved_metrics": improved,
        "regressed_metrics": regressed,
        "unchanged_metrics": unchanged,
    }
