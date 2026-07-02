from pathlib import Path

import pandas as pd

try:
    from config import STARTING_CASH
except Exception:
    STARTING_CASH = 10000.0


TRADING_DAYS = 252
SUPPORTED_EXIT_METHODS = {
    "current_binary_exit",
    "fixed_stop_loss",
    "trailing_stop",
    "confirmation_exit",
    "partial_exit",
    "time_exit",
}


def _read_csv(path, **kwargs):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, **kwargs)
    except Exception:
        return pd.DataFrame()


def _as_datetime_index(frame):
    if frame.empty:
        return pd.DataFrame()

    result = frame.copy()
    date_column = "Date" if "Date" in result.columns else "date"
    if date_column in result.columns:
        result[date_column] = pd.to_datetime(result[date_column], errors="coerce")
        result = result.dropna(subset=[date_column]).set_index(date_column)
    else:
        result.index = pd.to_datetime(result.index, errors="coerce")
        result = result[result.index.notna()]

    result = result.sort_index()
    result.index = result.index.normalize()
    return result


def load_exit_simulation_inputs(base_path="."):
    base_path = Path(base_path)
    signals = _as_datetime_index(_read_csv(base_path / "signals_v2.csv"))
    prices = _as_datetime_index(_read_csv(base_path / "prices_v2.csv"))
    weights = _as_datetime_index(_read_csv(base_path / "weights_v2.csv"))
    return signals, prices, weights


def _float_value(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return default
    if pd.isna(value):
        return default
    return value


def _int_value(value, default=0):
    try:
        value = int(value)
    except Exception:
        return default
    return value


def _pct_value(value, default=None):
    if value is None:
        return default
    value = _float_value(value, default)
    if value is None:
        return default
    if value > 1:
        return value / 100
    return value


def _clean_metrics(metrics):
    cleaned = {}
    for key, value in metrics.items():
        if isinstance(value, int):
            cleaned[key] = int(value)
            continue
        try:
            value = float(value)
        except Exception:
            cleaned[key] = 0.0
            continue
        if pd.isna(value):
            value = 0.0
        cleaned[key] = float(value)
    return cleaned


def _sell_position(
    holdings,
    ticker,
    date,
    price,
    shares,
    reason,
    trade_rows,
    cash,
):
    position = holdings[ticker]
    shares = min(float(shares), float(position["shares"]))
    if shares <= 0:
        return cash

    value = price * shares
    pnl = (price - position["entry_price"]) * shares
    pnl_percent = (price / position["entry_price"]) - 1 if position["entry_price"] else 0
    holding_days = max(
        0,
        (pd.Timestamp(date) - pd.Timestamp(position["entry_date"])).days,
    )

    trade_rows.append(
        {
            "date": date,
            "action": "SELL",
            "ticker": ticker,
            "price": price,
            "shares": shares,
            "value": value,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "reason": reason,
            "holding_days": holding_days,
        }
    )
    cash += value
    position["shares"] -= shares

    if position["shares"] <= 1e-12:
        del holdings[ticker]

    return cash


def _exit_shares(position, exit_method, signal, price, date, config):
    holding_days = max(
        0,
        (pd.Timestamp(date) - pd.Timestamp(position["entry_date"])).days,
    )
    entry_price = position["entry_price"]

    if exit_method == "current_binary_exit":
        if signal == 0:
            return position["shares"], "SIGNAL EXIT"
        return 0, None

    if exit_method == "fixed_stop_loss":
        stop_loss_pct = _pct_value(config.get("stop_loss_pct"), 0.03)
        if price <= entry_price * (1 - stop_loss_pct):
            return position["shares"], "FIXED STOP LOSS"
        return 0, None

    if exit_method == "trailing_stop":
        trailing_stop_pct = _pct_value(config.get("trailing_stop_pct"), 0.05)
        position["high_water"] = max(position.get("high_water", entry_price), price)
        trailing_stop = position["high_water"] * (1 - trailing_stop_pct)
        if price <= trailing_stop:
            return position["shares"], "TRAILING STOP"
        return 0, None

    if exit_method == "confirmation_exit":
        confirmation_days = max(1, _int_value(config.get("exit_confirmation_days"), 2))
        if signal == 0:
            position["exit_signal_count"] = position.get("exit_signal_count", 0) + 1
        else:
            position["exit_signal_count"] = 0
        if position.get("exit_signal_count", 0) >= confirmation_days:
            return position["shares"], "CONFIRMED SIGNAL EXIT"
        return 0, None

    if exit_method == "partial_exit":
        stop_loss_pct = _pct_value(config.get("stop_loss_pct"), 0.03)
        trigger_pct = _pct_value(config.get("partial_exit_trigger_pct"), 0.05)
        partial_pct = _pct_value(config.get("partial_exit_pct"), 0.50)
        if price <= entry_price * (1 - stop_loss_pct):
            return position["shares"], "PARTIAL EXIT STOP"
        if not position.get("partial_exit_done") and price >= entry_price * (1 + trigger_pct):
            position["partial_exit_done"] = True
            return position["shares"] * partial_pct, "PARTIAL TAKE PROFIT"
        if signal == 0:
            return position["shares"], "SIGNAL EXIT REMAINDER"
        return 0, None

    if exit_method == "time_exit":
        minimum_holding_days = max(0, _int_value(config.get("minimum_holding_days"), 0))
        max_holding_days = max(1, _int_value(config.get("max_holding_days"), 10))
        if holding_days >= max_holding_days:
            return position["shares"], "TIME EXIT"
        if holding_days >= minimum_holding_days and signal == 0:
            return position["shares"], "SIGNAL EXIT AFTER MIN HOLD"
        return 0, None

    raise ValueError(f"Unsupported exit method: {exit_method}")


def calculate_exit_metrics(equity_curve, trade_journal, starting_cash):
    if equity_curve.empty:
        return _clean_metrics(
            {
                "total_return": 0,
                "cagr": 0,
                "sharpe_ratio": 0,
                "sortino_ratio": 0,
                "max_drawdown": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "trade_count": 0,
                "average_holding_period": 0,
                "average_win": 0,
                "average_loss": 0,
                "best_trade": 0,
                "worst_trade": 0,
            }
        )

    values = pd.to_numeric(equity_curve["portfolio_value"], errors="coerce").dropna()
    final_value = values.iloc[-1] if not values.empty else starting_cash
    total_return = (final_value / starting_cash) - 1 if starting_cash else 0
    elapsed_days = (
        pd.Timestamp(equity_curve["date"].iloc[-1])
        - pd.Timestamp(equity_curve["date"].iloc[0])
    ).days
    years = elapsed_days / 365.25 if elapsed_days > 0 else 0
    cagr = (
        (final_value / starting_cash) ** (1 / years) - 1
        if years > 0 and starting_cash > 0
        else 0
    )
    returns = values.pct_change().dropna()
    volatility = returns.std()
    sharpe = (
        float((returns.mean() / volatility) * (TRADING_DAYS ** 0.5))
        if len(returns) > 1 and volatility and volatility != 0
        else 0
    )
    downside = returns[returns < 0]
    downside_volatility = downside.std()
    sortino = (
        float((returns.mean() / downside_volatility) * (TRADING_DAYS ** 0.5))
        if len(downside) > 1 and downside_volatility and downside_volatility != 0
        else 0
    )
    max_drawdown = float(pd.to_numeric(equity_curve["drawdown"], errors="coerce").min())

    sells = pd.DataFrame()
    if not trade_journal.empty and "action" in trade_journal.columns:
        sells = trade_journal[trade_journal["action"] == "SELL"].copy()

    if sells.empty:
        trade_metrics = {
            "win_rate": 0,
            "profit_factor": 0,
            "trade_count": 0,
            "average_holding_period": 0,
            "average_win": 0,
            "average_loss": 0,
            "best_trade": 0,
            "worst_trade": 0,
        }
    else:
        pnl = pd.to_numeric(sells["pnl"], errors="coerce").fillna(0)
        winners = pnl[pnl > 0]
        losers = pnl[pnl < 0]
        gross_profit = float(winners.sum())
        gross_loss = float(abs(losers.sum()))
        holding_days = pd.to_numeric(sells["holding_days"], errors="coerce").fillna(0)
        trade_metrics = {
            "win_rate": float((pnl > 0).mean()),
            "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else 0,
            "trade_count": int(len(sells)),
            "average_holding_period": float(holding_days.mean()) if len(holding_days) else 0,
            "average_win": float(winners.mean()) if len(winners) else 0,
            "average_loss": float(losers.mean()) if len(losers) else 0,
            "best_trade": float(pnl.max()) if len(pnl) else 0,
            "worst_trade": float(pnl.min()) if len(pnl) else 0,
        }

    return _clean_metrics(
        {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_drawdown,
            **trade_metrics,
        }
    )


def run_exit_simulation(
    exit_method,
    parameter_config=None,
    base_path=".",
    starting_cash=STARTING_CASH,
):
    if exit_method not in SUPPORTED_EXIT_METHODS:
        raise ValueError(f"Unsupported exit method: {exit_method}")

    signals, prices, weights = load_exit_simulation_inputs(base_path)
    if signals.empty or prices.empty or weights.empty:
        raise ValueError("Saved signals, prices, or weights are unavailable.")

    common_dates = signals.index.intersection(prices.index).intersection(weights.index)
    common_dates = common_dates.sort_values()
    if common_dates.empty:
        raise ValueError("No overlapping dates for saved signals, prices, and weights.")

    config = dict(parameter_config or {})
    max_positions = max(1, _int_value(config.get("max_positions"), 5))
    position_size = _pct_value(config.get("position_size"), None)

    cash = float(starting_cash)
    holdings = {}
    trade_rows = []
    equity_rows = []

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

        for ticker in list(holdings):
            raw_price = latest_prices.get(ticker)
            if pd.isna(raw_price):
                continue
            price = float(raw_price)
            signal = _float_value(latest_signals.get(ticker), 0)
            shares, reason = _exit_shares(
                holdings[ticker],
                exit_method,
                signal,
                price,
                date,
                config,
            )
            if shares and reason:
                cash = _sell_position(
                    holdings,
                    ticker,
                    date,
                    price,
                    shares,
                    reason,
                    trade_rows,
                    cash,
                )
                if ticker not in holdings:
                    exited_tickers.add(ticker)

        buy_candidates = [
            ticker
            for ticker in tradable_tickers
            if ticker not in holdings and ticker not in exited_tickers
        ]
        buy_candidates = sorted(
            buy_candidates,
            key=lambda ticker: _float_value(latest_weights.get(ticker), 0),
            reverse=True,
        )

        for ticker in buy_candidates:
            if len(holdings) >= max_positions:
                break

            signal = _float_value(latest_signals.get(ticker), 0)
            weight = _float_value(latest_weights.get(ticker), 0)
            raw_price = latest_prices.get(ticker)

            if signal != 1 or weight <= 0 or pd.isna(raw_price):
                continue

            price = float(raw_price)
            effective_weight = position_size if position_size is not None else weight
            position_value = min(float(starting_cash) * effective_weight, cash)
            if position_value <= 0:
                continue

            shares = position_value / price
            cash -= position_value
            holdings[ticker] = {
                "ticker": ticker,
                "entry_date": date,
                "entry_price": price,
                "shares": shares,
                "position_value": position_value,
                "high_water": price,
                "exit_signal_count": 0,
                "partial_exit_done": False,
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
        for position in holdings.values():
            raw_price = latest_prices.get(position["ticker"])
            price = position["entry_price"] if pd.isna(raw_price) else float(raw_price)
            positions_value += price * position["shares"]

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
                "open_positions": len(holdings),
                "peak": peak,
                "drawdown": drawdown,
            }
        )

    final_date = common_dates[-1]
    final_prices = prices.loc[final_date]
    for ticker in list(holdings):
        raw_price = final_prices.get(ticker)
        price = holdings[ticker]["entry_price"] if pd.isna(raw_price) else float(raw_price)
        cash = _sell_position(
            holdings,
            ticker,
            final_date,
            price,
            holdings[ticker]["shares"],
            "END OF TEST",
            trade_rows,
            cash,
        )

    equity_curve = pd.DataFrame(equity_rows)
    trade_journal = pd.DataFrame(trade_rows)
    metrics = calculate_exit_metrics(equity_curve, trade_journal, float(starting_cash))

    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trade_journal": trade_journal,
        "availability": {
            "signals_rows": int(len(signals)),
            "prices_rows": int(len(prices)),
            "weights_rows": int(len(weights)),
            "overlap_rows": int(len(common_dates)),
        },
    }
