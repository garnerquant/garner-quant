import pandas as pd

from config import ASSETS

from data.market_data import download_market_data, get_price_field
from strategy.signals import build_signals
from strategy.portfolio import build_weights
from risk.risk_manager import build_risk_levels
from backtest.engine import run_backtest

from reporting.performance import calculate_performance, print_performance
from reporting.signal_report import create_signal_report, print_signal_report
from reporting.dashboard import show_dashboard
from reporting.telegram_alerts import send_message
from reporting.telegram_formatter import build_telegram_message

from execution.portfolio_manager import update_portfolio, portfolio_summary
from reporting.trade_analytics import analyse_trade_journal, print_trade_analytics
from execution.broker_account import broker_summary
from execution.supabase_sync import sync_broker_account, sync_holdings, sync_30_day_tracker, sync_holdings_history, sync_trade_journal
from reporting.holdings_report import create_holdings_report, print_holdings_report
from reporting.paper_performance import (
    update_30_day_tracker,
    calculate_30_day_performance,
    print_30_day_performance
)


def main(show_charts=True, send_telegram=True):
    tickers = list(ASSETS.keys())

    print("Downloading market data...")
    market_data = download_market_data(tickers)

    prices = get_price_field(market_data, "Close")
    highs = get_price_field(market_data, "High")
    lows = get_price_field(market_data, "Low")
    volumes = get_price_field(market_data, "Volume")

    print("Building signals...")
    signals = build_signals(prices, volumes)

    print("Building risk levels...")
    risk_levels = build_risk_levels(prices, highs, lows)

    print("Building portfolio weights...")
    weights = build_weights(signals, prices, risk_levels)

    print("Running backtest...")
    portfolio = run_backtest(prices, weights, risk_levels)

    print("Updating Portfolio Manager V3...")
    paper_portfolio, trade_journal, v3_trades = update_portfolio(
        signals,
        prices,
        weights,
        risk_levels
    )

    summary = portfolio_summary(paper_portfolio, prices)

    holdings_report = create_holdings_report(
        paper_portfolio,
        prices
    )

    print("Saving CSV files...")
    prices.to_csv("prices_v2.csv")
    signals.to_csv("signals_v2.csv")
    weights.to_csv("weights_v2.csv")
    risk_levels.to_csv("risk_levels_v2.csv")
    portfolio.to_csv("portfolio_v2.csv")
    paper_portfolio.to_csv("paper_portfolio_v3.csv", index=False)
    trade_journal.to_csv("trade_journal_v3.csv", index=False)
    v3_trades.to_csv("v3_trades.csv", index=False)
    holdings_report.to_csv("holdings_report.csv", index=False)

    fundamental_scores = pd.read_csv("fundamental_scores.csv")

    report = calculate_performance(portfolio)
    print_performance(report)
    trade_stats = analyse_trade_journal(trade_journal)
    print_trade_analytics(trade_stats)

    pd.DataFrame([trade_stats]).to_csv(
        "trade_analytics_v3.csv",
        index=False
    )

    signal_rows = create_signal_report(signals, weights)
    print_signal_report(signal_rows)
    print_holdings_report(holdings_report)

    pd.DataFrame(signal_rows).to_csv(
        "signal_report_v2.csv",
        index=False
    )

    broker = broker_summary()
    tracker = update_30_day_tracker(broker)
    paper_30_day = calculate_30_day_performance(tracker)
    print_30_day_performance(paper_30_day)

    sync_broker_account()
    sync_holdings()
    sync_30_day_tracker()
    sync_holdings_history()
    sync_trade_journal()

    telegram_message = build_telegram_message(
        report,
        signal_rows,
        fundamental_scores,
        summary,
        v3_trades,
        trade_stats,
        broker,
        holdings_report
    )

    if send_telegram:
        print("Sending Telegram update...")
        send_message(telegram_message)

    if show_charts:
        show_dashboard(portfolio, weights, report)

    print("\nGarner Quant V2.1 run complete.")


if __name__ == "__main__":
    main()