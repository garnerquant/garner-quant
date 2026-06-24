def build_telegram_message(report, signal_rows, fundamental_scores, summary, v3_trades, trade_stats, broker, holdings_report, benchmark_stats):
    message = "📈 Garner Quant Daily Update\n\n"

    message += "Live Paper Account:\n"
    message += f"Portfolio Value: £{broker['portfolio_value']:,.2f}\n"
    message += f"Cash: £{broker['cash']:,.2f}\n"
    message += f"Buying Power: £{broker['buying_power']:,.2f}\n"
    message += f"Realised PnL: £{broker['realised_pnl']:,.2f}\n"
    message += f"Unrealised PnL: £{broker['unrealised_pnl']:,.2f}\n\n"

    message += "Backtest Snapshot:\n"
    message += (
        f"Final Value: £{report['final_value']:,.2f}\n"
        f"Return: {report['total_return']:.2%}\n"
        f"Max Drawdown: {report['max_drawdown']:.2%}\n"
        f"Sharpe: {report['sharpe_ratio']:.2f}\n\n"
    )

    message += "📊 Benchmark:\n"
    message += (
        f"Garner Quant: {benchmark_stats['portfolio_return']:.2%}\n"
        f"{benchmark_stats['ticker']}: {benchmark_stats['benchmark_return']:.2%}\n"
        f"Alpha: {benchmark_stats['alpha']:.2%}\n\n"
    )

    message += "Current Signals:\n"
    for row in signal_rows:
        message += f"{row['ticker']}: {row['status']} ({row['weight']:.2%})\n"

    message += "\nFundamental Scores:\n"
    for _, row in fundamental_scores.iterrows():
        message += f"{row['ticker']}: {row['fundamental_score']}\n"

    message += "\nPortfolio Manager V3:\n"
    message += f"Paper Value: £{summary['total_value']:,.2f}\n"
    message += f"Cash: £{summary['cash']:,.2f}\n"
    message += f"Open Positions: {len(summary['positions'])}\n"
    message += f"Unrealised PnL: £{summary['unrealised_pnl']:,.2f}\n\n"

    message += "Today's V3 Trades:\n"
    if len(v3_trades) == 0:
        message += "No new trades today.\n"
    else:
        for _, trade in v3_trades.iterrows():
            message += (
                f"{trade['action']} {trade['ticker']} "
                f"at {trade['price']:.2f} ({trade['reason']})\n"
            )

    message += "\nTrade Analytics:\n"
    message += f"Total Trades: {trade_stats['total_trades']}\n"
    message += f"Win Rate: {trade_stats['win_rate']:.2%}\n"
    message += f"Profit Factor: {trade_stats['profit_factor']:.2f}\n"
    message += f"Realised PnL: £{trade_stats['realised_pnl']:,.2f}\n"

    message += "\nHoldings:\n"

    if len(holdings_report) == 0:
        message += "No open holdings.\n"
    else:
        for _, row in holdings_report.iterrows():
            message += (
                f"{row['ticker']}: "
                f"£{row['market_value']:,.2f} "
                f"PnL £{row['unrealised_pnl']:,.2f} "
                f"({row['unrealised_pnl_percent']:.2%})\n"
            )

    return message