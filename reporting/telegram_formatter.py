import math


MARKET_DATA_WAITING = "Waiting for latest market data"
PRICE_UNAVAILABLE = "Price unavailable"
VALUE_UNAVAILABLE = "Unavailable"


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric_value):
        return None

    return numeric_value


def _format_money(value, missing_label=MARKET_DATA_WAITING):
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return missing_label
    return f"\u00a3{numeric_value:,.2f}"


def _format_percent(value, missing_label=MARKET_DATA_WAITING):
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return missing_label
    return f"{numeric_value:.2%}"


def _format_number(value, decimals=2, missing_label=VALUE_UNAVAILABLE):
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return missing_label
    return f"{numeric_value:,.{decimals}f}"


def _format_raw(value, missing_label=VALUE_UNAVAILABLE):
    if value is None:
        return missing_label
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return missing_label
    return text


def _format_position_count(positions):
    try:
        return str(len(positions))
    except TypeError:
        return "0"


def _format_holding_line(row):
    ticker = _format_raw(row.get("ticker"), "Unknown")
    market_value = _format_money(row.get("market_value"), PRICE_UNAVAILABLE)
    pnl = _format_money(row.get("unrealised_pnl"), VALUE_UNAVAILABLE)
    pnl_percent = _format_percent(
        row.get("unrealised_pnl_percent"),
        VALUE_UNAVAILABLE,
    )

    return f"{ticker}: {market_value} PnL {pnl} ({pnl_percent})"


def build_telegram_message(
    report,
    signal_rows,
    fundamental_scores,
    summary,
    v3_trades,
    trade_stats,
    broker,
    holdings_report,
    benchmark_stats,
):
    message = "\U0001f4c8 Garner Quant Daily Update\n\n"

    message += "Live Paper Account:\n"
    message += (
        f"Portfolio Value: {_format_money(broker.get('portfolio_value'))}\n"
    )
    message += f"Cash: {_format_money(broker.get('cash'), VALUE_UNAVAILABLE)}\n"
    message += (
        f"Buying Power: {_format_money(broker.get('buying_power'), VALUE_UNAVAILABLE)}\n"
    )
    message += (
        f"Realised PnL: {_format_money(broker.get('realised_pnl'), VALUE_UNAVAILABLE)}\n"
    )
    message += f"Unrealised PnL: {_format_money(broker.get('unrealised_pnl'))}\n\n"

    message += "Backtest Snapshot:\n"
    message += (
        f"Final Value: {_format_money(report.get('final_value'), VALUE_UNAVAILABLE)}\n"
        f"Return: {_format_percent(report.get('total_return'), VALUE_UNAVAILABLE)}\n"
        f"Max Drawdown: {_format_percent(report.get('max_drawdown'), VALUE_UNAVAILABLE)}\n"
        f"Sharpe: {_format_number(report.get('sharpe_ratio'))}\n\n"
    )

    message += "\U0001f4ca Benchmark:\n"
    message += (
        f"Garner Quant: {_format_percent(benchmark_stats.get('portfolio_return'), VALUE_UNAVAILABLE)}\n"
        f"{_format_raw(benchmark_stats.get('ticker'), 'Benchmark')}: "
        f"{_format_percent(benchmark_stats.get('benchmark_return'), VALUE_UNAVAILABLE)}\n"
        f"Alpha: {_format_percent(benchmark_stats.get('alpha'), VALUE_UNAVAILABLE)}\n\n"
    )

    message += "Current Signals:\n"
    for row in signal_rows:
        message += (
            f"{_format_raw(row.get('ticker'), 'Unknown')}: "
            f"{_format_raw(row.get('status'))} "
            f"({_format_percent(row.get('weight'), VALUE_UNAVAILABLE)})\n"
        )

    message += "\nFundamental Scores:\n"
    for _, row in fundamental_scores.iterrows():
        message += (
            f"{_format_raw(row.get('ticker'), 'Unknown')}: "
            f"{_format_raw(row.get('fundamental_score'))}\n"
        )

    positions = summary.get("positions", [])
    message += "\nPortfolio Manager V3:\n"
    message += f"Paper Value: {_format_money(summary.get('total_value'))}\n"
    message += f"Cash: {_format_money(summary.get('cash'), VALUE_UNAVAILABLE)}\n"
    message += f"Open Positions: {_format_position_count(positions)}\n"
    message += f"Unrealised PnL: {_format_money(summary.get('unrealised_pnl'))}\n\n"

    message += "Today's V3 Trades:\n"
    if len(v3_trades) == 0:
        message += "No new trades today.\n"
    else:
        for _, trade in v3_trades.iterrows():
            message += (
                f"{_format_raw(trade.get('action'))} "
                f"{_format_raw(trade.get('ticker'), 'Unknown')} "
                f"at {_format_number(trade.get('price'), missing_label=PRICE_UNAVAILABLE)} "
                f"({_format_raw(trade.get('reason'))})\n"
            )

    message += "\nTrade Analytics:\n"
    message += f"Total Trades: {_format_raw(trade_stats.get('total_trades'), '0')}\n"
    message += f"Win Rate: {_format_percent(trade_stats.get('win_rate'), VALUE_UNAVAILABLE)}\n"
    message += f"Profit Factor: {_format_number(trade_stats.get('profit_factor'))}\n"
    message += (
        f"Realised PnL: {_format_money(trade_stats.get('realised_pnl'), VALUE_UNAVAILABLE)}\n"
    )

    message += "\nHoldings:\n"

    if len(holdings_report) == 0:
        message += "No open holdings.\n"
    else:
        for _, row in holdings_report.iterrows():
            message += f"{_format_holding_line(row)}\n"

    return message
