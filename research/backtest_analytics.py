from pathlib import Path

import pandas as pd

try:
    from config import BENCHMARK_TICKER
except Exception:
    BENCHMARK_TICKER = "SPY"


TRADING_DAYS = 252
DEFAULT_FILES = {
    "portfolio": "portfolio_v2.csv",
    "trade_journal": "trade_journal_v3.csv",
    "trade_audit": "trade_audit_trail.csv",
    "prices": "prices_v2.csv",
    "paper_tracker": "paper_30_day_tracker.csv",
}


def _read_csv(path):
    path = Path(path)

    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _first_existing(columns, candidates):
    lookup = {str(column).lower(): column for column in columns}

    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]

    return None


def _safe_float(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return default

    if pd.isna(value):
        return default

    return value


def _normalise_date_column(df):
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    date_column = _first_existing(result.columns, ["date", "Date", "timestamp"])

    if date_column is None:
        result["date"] = pd.to_datetime(result.index, errors="coerce")
    else:
        result["date"] = pd.to_datetime(result[date_column], errors="coerce")

    result = result.dropna(subset=["date"]).sort_values("date")
    return result


def _normalise_equity_curve(portfolio):
    curve = _normalise_date_column(portfolio)

    if curve.empty:
        return pd.DataFrame(columns=["date", "equity", "daily_return", "drawdown"])

    equity_column = _first_existing(
        curve.columns,
        ["equity", "portfolio_value", "value", "ending_value"],
    )

    if equity_column is None:
        return pd.DataFrame(columns=["date", "equity", "daily_return", "drawdown"])

    result = pd.DataFrame()
    result["date"] = curve["date"]
    result["equity"] = pd.to_numeric(curve[equity_column], errors="coerce")
    result = result.dropna(subset=["equity"])

    return_column = _first_existing(
        curve.columns,
        ["daily_return", "return", "returns", "strategy_return"],
    )

    if return_column is not None:
        result["daily_return"] = pd.to_numeric(
            curve.loc[result.index, return_column],
            errors="coerce",
        )
    else:
        result["daily_return"] = result["equity"].pct_change()

    drawdown_column = _first_existing(curve.columns, ["drawdown", "max_drawdown"])

    if drawdown_column is not None:
        result["drawdown"] = pd.to_numeric(
            curve.loc[result.index, drawdown_column],
            errors="coerce",
        )
    else:
        peak = result["equity"].cummax()
        result["drawdown"] = (result["equity"] / peak) - 1

    return result.reset_index(drop=True)


def _elapsed_years(curve):
    if curve.empty:
        return 0

    elapsed_days = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days

    if elapsed_days > 0:
        return elapsed_days / 365.25

    return max((len(curve) - 1) / TRADING_DAYS, 0)


def calculate_equity_metrics(portfolio):
    curve = _normalise_equity_curve(portfolio)

    if curve.empty or len(curve) < 2:
        return {
            "starting_value": 0.0,
            "ending_value": 0.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "annualised_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
        }

    starting_value = _safe_float(curve["equity"].iloc[0])
    ending_value = _safe_float(curve["equity"].iloc[-1])
    total_return = (
        (ending_value / starting_value) - 1
        if starting_value > 0
        else 0.0
    )

    returns = pd.to_numeric(curve["daily_return"], errors="coerce").dropna()
    annualised_volatility = (
        float(returns.std() * (TRADING_DAYS ** 0.5))
        if len(returns) > 1
        else 0.0
    )
    sharpe_ratio = (
        float((returns.mean() / returns.std()) * (TRADING_DAYS ** 0.5))
        if len(returns) > 1 and returns.std() != 0
        else 0.0
    )
    downside = returns[returns < 0]
    sortino_ratio = (
        float((returns.mean() / downside.std()) * (TRADING_DAYS ** 0.5))
        if len(downside) > 1 and downside.std() != 0
        else 0.0
    )
    years = _elapsed_years(curve)
    cagr = (
        (ending_value / starting_value) ** (1 / years) - 1
        if years > 0 and starting_value > 0
        else 0.0
    )

    drawdown = pd.to_numeric(curve["drawdown"], errors="coerce").dropna()
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    return {
        "starting_value": float(starting_value),
        "ending_value": float(ending_value),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "annualised_volatility": float(annualised_volatility),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown": float(max_drawdown),
    }


def _holding_days_from_period(series):
    holding = pd.to_timedelta(series, errors="coerce")
    return holding.dt.total_seconds() / 86400


def _normalise_audit_trades(audit):
    if audit.empty:
        return pd.DataFrame()

    trades = audit.copy()
    rename_map = {
        "symbol": "ticker",
        "open_time": "entry_date",
        "close_time": "exit_date",
        "pnl": "pnl",
        "pnl_pct": "pnl_percent",
    }
    trades = trades.rename(
        columns={
            source: target
            for source, target in rename_map.items()
            if source in trades.columns
        }
    )

    if "holding_period" in trades.columns:
        trades["holding_days"] = _holding_days_from_period(
            trades["holding_period"],
        )
    elif {"entry_date", "exit_date"}.issubset(trades.columns):
        trades["entry_date"] = pd.to_datetime(trades["entry_date"], errors="coerce")
        trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="coerce")
        trades["holding_days"] = (
            trades["exit_date"] - trades["entry_date"]
        ).dt.total_seconds() / 86400

    return trades


def _normalise_journal_trades(journal):
    if journal.empty:
        return pd.DataFrame()

    trades = journal.copy()

    if "action" in trades.columns:
        actions = trades["action"].astype(str).str.upper()
        sells = trades[actions == "SELL"].copy()
        if not sells.empty:
            trades = sells

    if "date" in trades.columns and "exit_date" not in trades.columns:
        trades["exit_date"] = trades["date"]

    if "holding_period" in trades.columns:
        trades["holding_days"] = _holding_days_from_period(
            trades["holding_period"],
        )

    return trades


def normalise_trades(trade_journal=None, trade_audit=None):
    audit = trade_audit if trade_audit is not None else pd.DataFrame()
    journal = trade_journal if trade_journal is not None else pd.DataFrame()

    trades = _normalise_audit_trades(audit)

    if trades.empty:
        trades = _normalise_journal_trades(journal)

    if trades.empty:
        return pd.DataFrame(
            columns=["ticker", "pnl", "pnl_percent", "holding_days"],
        )

    result = trades.copy()

    if "ticker" not in result.columns:
        result["ticker"] = "Unknown"

    if "pnl" not in result.columns:
        result["pnl"] = 0

    result["pnl"] = pd.to_numeric(result["pnl"], errors="coerce").fillna(0)

    if "pnl_percent" not in result.columns:
        result["pnl_percent"] = pd.NA

    result["pnl_percent"] = pd.to_numeric(
        result["pnl_percent"],
        errors="coerce",
    )

    if "holding_days" not in result.columns:
        result["holding_days"] = pd.NA

    result["holding_days"] = pd.to_numeric(
        result["holding_days"],
        errors="coerce",
    )
    result["is_winner"] = result["pnl"] > 0

    return result.reset_index(drop=True)


def calculate_trade_metrics(trades):
    if trades is None or trades.empty:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "average_holding_period": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }

    pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0)
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    gross_profit = float(winners.sum())
    gross_loss = float(abs(losers.sum()))
    holding_days = pd.to_numeric(
        trades.get("holding_days", pd.Series(dtype=float)),
        errors="coerce",
    ).dropna()

    return {
        "trade_count": int(len(trades)),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "average_win": float(winners.mean()) if not winners.empty else 0.0,
        "average_loss": float(losers.mean()) if not losers.empty else 0.0,
        "profit_factor": (
            float(gross_profit / gross_loss)
            if gross_loss > 0
            else 0.0
        ),
        "average_holding_period": (
            float(holding_days.mean())
            if not holding_days.empty
            else 0.0
        ),
        "best_trade": float(pnl.max()) if not pnl.empty else 0.0,
        "worst_trade": float(pnl.min()) if not pnl.empty else 0.0,
    }


def calculate_benchmark_metrics(portfolio, prices, paper_tracker=None, ticker=None):
    ticker = ticker or BENCHMARK_TICKER
    curve = _normalise_equity_curve(portfolio)

    if prices is not None and not prices.empty and ticker in prices.columns:
        benchmark = _normalise_date_column(prices)

        if not benchmark.empty:
            if not curve.empty:
                start = curve["date"].iloc[0]
                end = curve["date"].iloc[-1]
                benchmark = benchmark[
                    (benchmark["date"] >= start) & (benchmark["date"] <= end)
                ]

            values = pd.to_numeric(benchmark[ticker], errors="coerce").dropna()

            if len(values) >= 2 and values.iloc[0] > 0:
                benchmark_return = float((values.iloc[-1] / values.iloc[0]) - 1)
                return {
                    "benchmark_ticker": ticker,
                    "benchmark_return": benchmark_return,
                    "benchmark_source": "prices_v2.csv",
                }

    tracker = paper_tracker if paper_tracker is not None else pd.DataFrame()

    if not tracker.empty and "benchmark_return" in tracker.columns:
        values = pd.to_numeric(tracker["benchmark_return"], errors="coerce").dropna()

        if not values.empty:
            return {
                "benchmark_ticker": ticker,
                "benchmark_return": float(values.iloc[-1]),
                "benchmark_source": "paper_30_day_tracker.csv",
            }

    return {
        "benchmark_ticker": ticker,
        "benchmark_return": None,
        "benchmark_source": "",
    }


def build_metric_table(summary):
    rows = [
        ("Total Return", "total_return", "percent"),
        ("CAGR", "cagr", "percent"),
        ("Annualised Volatility", "annualised_volatility", "percent"),
        ("Sharpe Ratio", "sharpe_ratio", "number"),
        ("Sortino Ratio", "sortino_ratio", "number"),
        ("Max Drawdown", "max_drawdown", "percent"),
        ("Win Rate", "win_rate", "percent"),
        ("Average Win", "average_win", "currency"),
        ("Average Loss", "average_loss", "currency"),
        ("Profit Factor", "profit_factor", "number"),
        ("Average Holding Period", "average_holding_period", "days"),
        ("Benchmark Return", "benchmark_return", "percent"),
        ("Alpha", "alpha", "percent"),
        ("Trade Count", "trade_count", "number"),
        ("Best Trade", "best_trade", "currency"),
        ("Worst Trade", "worst_trade", "currency"),
    ]

    return pd.DataFrame(
        [
            {
                "metric": label,
                "key": key,
                "value": summary.get(key),
                "format": value_format,
            }
            for label, key, value_format in rows
        ]
    )


def load_backtest_analytics(base_path="."):
    base_path = Path(base_path)
    files = {
        key: base_path / filename
        for key, filename in DEFAULT_FILES.items()
    }
    portfolio = _read_csv(files["portfolio"])
    trade_journal = _read_csv(files["trade_journal"])
    trade_audit = _read_csv(files["trade_audit"])
    prices = _read_csv(files["prices"])
    paper_tracker = _read_csv(files["paper_tracker"])

    equity_metrics = calculate_equity_metrics(portfolio)
    trades = normalise_trades(trade_journal, trade_audit)
    trade_metrics = calculate_trade_metrics(trades)
    benchmark = calculate_benchmark_metrics(portfolio, prices, paper_tracker)

    summary = {}
    summary.update(equity_metrics)
    summary.update(trade_metrics)
    summary.update(benchmark)
    summary["alpha"] = (
        summary["total_return"] - summary["benchmark_return"]
        if summary.get("benchmark_return") is not None
        else None
    )

    availability = {
        "portfolio_rows": int(len(portfolio)),
        "trade_journal_rows": int(len(trade_journal)),
        "trade_audit_rows": int(len(trade_audit)),
        "prices_rows": int(len(prices)),
        "benchmark_available": summary.get("benchmark_return") is not None,
        "benchmark_source": summary.get("benchmark_source", ""),
    }

    return {
        "summary": summary,
        "metric_table": build_metric_table(summary),
        "trades": trades,
        "availability": availability,
    }
