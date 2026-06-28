from pathlib import Path

import pandas as pd

try:
    from config import STARTING_CASH
except Exception:
    STARTING_CASH = 10000

try:
    from indicators.technical import technical_score
except Exception:
    technical_score = None


DEFAULT_EXPERIMENT_CONFIG = {
    "technical_score_threshold": 3,
    "max_positions": None,
    "position_size": None,
    "stop_loss_pct": None,
    "take_profit_pct": None,
    "min_volume": None,
    "exit_mode": "signals_and_stops",
}


def _as_datetime_index(df):
    result = df.copy()

    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
        result = result.dropna(subset=["Date"]).set_index("Date")
    elif "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.dropna(subset=["date"]).set_index("date")
    else:
        result.index = pd.to_datetime(result.index, errors="coerce")
        result = result[result.index.notna()]

    result = result.sort_index()
    result.index = result.index.normalize()
    return result


def _risk_value(risk_levels, date, side, ticker):
    if risk_levels is None or risk_levels.empty:
        return None

    lookup_date = pd.Timestamp(date).normalize()

    if lookup_date not in risk_levels.index:
        return None

    try:
        value = risk_levels.loc[lookup_date, (side, ticker)]
    except Exception:
        value = None

    if value is None:
        return None

    try:
        value = float(value)
    except Exception:
        return None

    if pd.isna(value):
        return None

    return value


def _safe_float(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return default

    if pd.isna(value):
        return default

    return value


def _normalise_experiment_config(experiment_config):
    config = DEFAULT_EXPERIMENT_CONFIG.copy()

    if experiment_config:
        config.update(
            {
                key: value
                for key, value in experiment_config.items()
                if key in config
            }
        )

    return config


def _safe_int(value):
    try:
        value = int(value)
    except Exception:
        return None

    if value <= 0:
        return None

    return value


def _safe_pct(value):
    value = _safe_float(value, None)

    if value is None or value <= 0:
        return None

    if value > 1:
        return value / 100

    return value


def _normalise_exit_mode(value):
    value = str(value or "signals_and_stops").strip().lower()
    value = value.replace(" ", "_").replace("-", "_")

    aliases = {
        "signals_and_stops": "signals_and_stops",
        "signal_and_stops": "signals_and_stops",
        "signal_and_stop": "signals_and_stops",
        "stops_and_signals": "signals_and_stops",
        "stops_only": "stops_only",
        "stop_only": "stops_only",
        "signal_only": "signal_only",
        "signals_only": "signal_only",
    }

    return aliases.get(value, "signals_and_stops")


def _apply_entry_filters(signals, prices, volumes, experiment_config):
    threshold = _safe_int(experiment_config.get("technical_score_threshold"))
    min_volume = _safe_float(experiment_config.get("min_volume"), None)

    if threshold is None and min_volume is None:
        return signals

    filtered = signals.copy()

    for ticker in filtered.columns:
        if ticker not in prices.columns:
            continue

        if threshold is not None and technical_score is not None:
            score = technical_score(ticker, prices[ticker])
            score = score.reindex(filtered.index).fillna(0)
            filtered[ticker] = (
                (filtered[ticker] == 1) & (score >= threshold)
            ).astype(int)

        if (
            min_volume is not None
            and volumes is not None
            and not volumes.empty
            and ticker in volumes.columns
        ):
            volume = pd.to_numeric(volumes[ticker], errors="coerce")
            volume = volume.reindex(filtered.index)
            filtered[ticker] = (
                (filtered[ticker] == 1) & (volume >= min_volume)
            ).astype(int)

    return filtered


def _calculate_metrics(equity_curve, trade_journal, holdings, latest_prices, starting_cash):
    if equity_curve.empty:
        return {
            "total_return": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "completed_trades": 0,
            "win_rate": 0,
            "realised_pnl": 0,
            "unrealised_pnl": 0,
            "average_holding_period": 0,
        }

    final_value = equity_curve["portfolio_value"].iloc[-1]
    total_return = (final_value / starting_cash) - 1
    max_drawdown = equity_curve["drawdown"].min()
    daily_returns = equity_curve["portfolio_value"].pct_change().dropna()
    volatility = daily_returns.std()
    sharpe_ratio = (
        (daily_returns.mean() / volatility) * (252 ** 0.5)
        if volatility and volatility != 0
        else 0
    )

    sells = trade_journal[trade_journal["action"] == "SELL"]
    completed_trades = len(sells)
    winners = sells[sells["pnl"] > 0]
    win_rate = len(winners) / completed_trades if completed_trades else 0
    realised_pnl = sells["pnl"].sum() if completed_trades else 0

    unrealised_pnl = 0
    if holdings and latest_prices is not None:
        for position in holdings.values():
            ticker = position["ticker"]
            if ticker in latest_prices.index:
                current_price = latest_prices[ticker]
                unrealised_pnl += (
                    current_price - position["entry_price"]
                ) * position["shares"]

    if completed_trades and "holding_days" in sells.columns:
        average_holding_period = sells["holding_days"].mean()
    else:
        average_holding_period = 0

    return {
        "total_return": float(total_return),
        "max_drawdown": float(max_drawdown),
        "sharpe_ratio": float(sharpe_ratio),
        "completed_trades": int(completed_trades),
        "win_rate": float(win_rate),
        "realised_pnl": float(realised_pnl),
        "unrealised_pnl": float(unrealised_pnl),
        "average_holding_period": float(average_holding_period),
    }


def run_live_rule_backtest(
    signals,
    prices,
    weights,
    risk_levels,
    starting_cash=STARTING_CASH,
    experiment_config=None,
    volumes=None,
):
    experiment_config = _normalise_experiment_config(experiment_config)
    signals = _as_datetime_index(signals)
    prices = _as_datetime_index(prices)
    weights = _as_datetime_index(weights)

    if volumes is not None and not volumes.empty:
        volumes = _as_datetime_index(volumes)
    else:
        volumes = None

    if risk_levels is not None and not risk_levels.empty:
        risk_levels = risk_levels.copy()
        risk_levels.index = pd.to_datetime(risk_levels.index, errors="coerce")
        risk_levels = risk_levels[risk_levels.index.notna()]
        risk_levels.index = risk_levels.index.normalize()
        risk_levels = risk_levels.sort_index()

    common_dates = signals.index.intersection(prices.index).intersection(
        weights.index
    )
    if volumes is not None:
        volumes = volumes.reindex(common_dates)

    common_dates = common_dates.sort_values()
    signals = _apply_entry_filters(signals, prices, volumes, experiment_config)

    cash = float(starting_cash)
    holdings = {}
    trade_rows = []
    equity_rows = []
    realised_pnl = 0.0

    tradable_tickers = [
        ticker
        for ticker in signals.columns
        if ticker in prices.columns and ticker in weights.columns
    ]

    for date in common_dates:
        latest_signals = signals.loc[date]
        latest_prices = prices.loc[date]
        latest_weights = weights.loc[date]
        exited_tickers = set()
        exit_mode = _normalise_exit_mode(experiment_config.get("exit_mode"))

        for ticker, position in list(holdings.items()):
            current_price = latest_prices.get(ticker)

            if pd.isna(current_price):
                continue

            current_price = float(current_price)
            signal = _safe_float(latest_signals.get(ticker), 0)

            sell_reason = None

            use_stops = exit_mode in {"signals_and_stops", "stops_only"}
            use_signal_exit = exit_mode in {"signals_and_stops", "signal_only"}

            if use_stops and current_price <= position["stop_loss"]:
                sell_reason = "STOP LOSS"
            elif use_stops and current_price >= position["take_profit"]:
                sell_reason = "TAKE PROFIT"
            elif use_signal_exit and signal == 0:
                sell_reason = "SIGNAL EXIT"

            if sell_reason is None:
                continue

            shares = position["shares"]
            value = current_price * shares
            pnl = (current_price - position["entry_price"]) * shares
            pnl_percent = (current_price / position["entry_price"]) - 1
            holding_days = (
                pd.Timestamp(date) - pd.Timestamp(position["entry_date"])
            ).days

            cash += value
            realised_pnl += pnl

            trade_rows.append(
                {
                    "date": date,
                    "action": "SELL",
                    "ticker": ticker,
                    "price": current_price,
                    "shares": shares,
                    "value": value,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                    "reason": sell_reason,
                    "holding_days": holding_days,
                }
            )

            del holdings[ticker]
            exited_tickers.add(ticker)

        max_positions = _safe_int(experiment_config.get("max_positions"))
        position_size = _safe_pct(experiment_config.get("position_size"))
        stop_loss_pct = _safe_pct(experiment_config.get("stop_loss_pct"))
        take_profit_pct = _safe_pct(experiment_config.get("take_profit_pct"))

        buy_candidates = [
            ticker
            for ticker in tradable_tickers
            if ticker not in holdings and ticker not in exited_tickers
        ]
        buy_candidates = sorted(
            buy_candidates,
            key=lambda ticker: _safe_float(latest_weights.get(ticker), 0),
            reverse=True,
        )

        for ticker in buy_candidates:
            if ticker in holdings or ticker in exited_tickers:
                continue

            if max_positions is not None and len(holdings) >= max_positions:
                continue

            signal = _safe_float(latest_signals.get(ticker), 0)
            weight = _safe_float(latest_weights.get(ticker), 0)
            price = latest_prices.get(ticker)

            if signal != 1 or weight <= 0 or pd.isna(price):
                continue

            price = float(price)
            effective_weight = position_size if position_size is not None else weight
            position_value = min(float(starting_cash) * effective_weight, cash)

            if position_value <= 0:
                continue

            stop_loss = _risk_value(risk_levels, date, "stop_loss", ticker)
            take_profit = _risk_value(risk_levels, date, "take_profit", ticker)

            if stop_loss_pct is not None:
                stop_loss = price * (1 - stop_loss_pct)

            if take_profit_pct is not None:
                take_profit = price * (1 + take_profit_pct)

            if stop_loss is None or take_profit is None:
                continue

            shares = position_value / price
            cash -= position_value

            holdings[ticker] = {
                "ticker": ticker,
                "entry_date": date,
                "entry_price": price,
                "shares": shares,
                "position_value": position_value,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

            trade_rows.append(
                {
                    "date": date,
                    "action": "BUY",
                    "ticker": ticker,
                    "price": price,
                    "shares": shares,
                    "value": position_value,
                    "pnl": 0.0,
                    "pnl_percent": 0.0,
                    "reason": "SIGNAL ENTRY",
                    "holding_days": 0,
                }
            )

        positions_value = 0.0
        unrealised_pnl = 0.0

        for position in holdings.values():
            ticker = position["ticker"]
            current_price = latest_prices.get(ticker)

            if pd.isna(current_price):
                current_price = position["entry_price"]

            current_price = float(current_price)
            current_value = current_price * position["shares"]
            positions_value += current_value
            unrealised_pnl += current_value - position["position_value"]

        portfolio_value = cash + positions_value
        peak = max(
            portfolio_value,
            equity_rows[-1]["peak"] if equity_rows else portfolio_value,
        )
        drawdown = (portfolio_value / peak) - 1 if peak else 0

        equity_rows.append(
            {
                "date": date,
                "cash": cash,
                "positions_value": positions_value,
                "portfolio_value": portfolio_value,
                "realised_pnl": realised_pnl,
                "unrealised_pnl": unrealised_pnl,
                "open_positions": len(holdings),
                "peak": peak,
                "drawdown": drawdown,
            }
        )

    equity_curve = pd.DataFrame(equity_rows)
    trade_journal = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(list(holdings.values()))
    latest_prices = prices.loc[common_dates[-1]] if len(common_dates) else None
    summary = _calculate_metrics(
        equity_curve,
        trade_journal,
        holdings,
        latest_prices,
        float(starting_cash),
    )

    return equity_curve, holdings_df, trade_journal, summary


def load_saved_inputs():
    signals = pd.read_csv("signals_v2.csv")
    prices = pd.read_csv("prices_v2.csv")
    weights = pd.read_csv("weights_v2.csv")
    risk_levels = pd.read_csv(
        "risk_levels_v2.csv",
        header=[0, 1],
        index_col=0,
    )
    return signals, prices, weights, risk_levels


def _load_optional_volumes():
    path = Path("volumes_v2.csv")

    if not path.exists():
        return None

    try:
        return pd.read_csv(path)
    except Exception:
        return None


def run_from_saved_files(starting_cash=STARTING_CASH, experiment_config=None):
    signals, prices, weights, risk_levels = load_saved_inputs()
    volumes = _load_optional_volumes()
    return run_live_rule_backtest(
        signals,
        prices,
        weights,
        risk_levels,
        starting_cash=starting_cash,
        experiment_config=experiment_config,
        volumes=volumes,
    )


if __name__ == "__main__":
    equity_curve, holdings, trade_journal, summary = run_from_saved_files()
    print("===== LIVE-RULE BACKTEST SUMMARY =====")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"equity rows: {len(equity_curve)}")
    print(f"holdings rows: {len(holdings)}")
    print(f"journal rows: {len(trade_journal)}")
