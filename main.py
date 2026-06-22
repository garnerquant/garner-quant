import pandas as pd
import matplotlib.pyplot as plt

from config import ASSETS
from data import download_market_data, get_price_field
from strategy import build_signals, build_weights
from backtest import run_backtest
from performance import calculate_performance, print_performance
from dashboard import show_dashboard
from signal_report import create_signal_report, print_signal_report
from risk import build_risk_levels
from telegram_alerts import send_message


def main():
    tickers = list(ASSETS.keys())

    print("Downloading market data...")
    market_data = download_market_data(tickers)

    prices = get_price_field(market_data, "Close")
    highs = get_price_field(market_data, "High")
    lows = get_price_field(market_data, "Low")
    volumes = get_price_field(market_data, "Volume")

    print("Building signals...")
    signals = build_signals(prices, volumes)

    print("Building portfolio weights...")
    weights = build_weights(signals)

    print("Building risk levels...")
    risk_levels = build_risk_levels(prices, highs, lows)

    print("Running backtest...")
    portfolio = run_backtest(prices, weights, risk_levels)

    prices.to_csv("prices.csv")
    signals.to_csv("signals.csv")
    weights.to_csv("weights.csv")
    risk_levels.to_csv("risk_levels.csv")
    portfolio.to_csv("portfolio.csv")

    report = calculate_performance(portfolio)
    print_performance(report)

    signal_rows = create_signal_report(signals, weights)
    print_signal_report(signal_rows)

    pd.DataFrame(signal_rows).to_csv(
        "signal_report.csv",
        index=False
    )

    telegram_message = "📈 Finance Bot Update\n\n"

    telegram_message += (
        f"Final Value: £{report['final_value']:,.2f}\n"
        f"Total Return: {report['total_return']:.2%}\n"
        f"Max Drawdown: {report['max_drawdown']:.2%}\n"
        f"Sharpe Ratio: {report['sharpe_ratio']:.2f}\n\n"
    )

    telegram_message += "Current Signals:\n"

    for row in signal_rows:
        telegram_message += (
            f"{row['ticker']}: {row['status']} "
            f"({row['weight']:.2%})\n"
        )

    send_message(telegram_message)

    show_dashboard(portfolio, weights, report)


if __name__ == "__main__":
    main()