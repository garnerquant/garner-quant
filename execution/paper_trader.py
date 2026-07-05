from pathlib import Path

import pandas as pd

from execution.legacy_isolation import legacy_sandbox, require_legacy_sandbox


PORTFOLIO_FILE = "paper_portfolio.csv"


def send_telegram_alert(message, *, legacy_mode=False):
    require_legacy_sandbox(legacy_mode, "execution.paper_trader.send_telegram_alert")
    return {
        "sent": 0,
        "skipped": 1,
        "errors": [],
        "message": "Legacy sandbox suppresses external notifications.",
    }


def _portfolio_path(sandbox_dir=None):
    if sandbox_dir is None:
        return Path(PORTFOLIO_FILE)
    return Path(sandbox_dir) / PORTFOLIO_FILE


def load_portfolio(*, legacy_mode=False, sandbox_dir=None):
    require_legacy_sandbox(legacy_mode, "execution.paper_trader.load_portfolio")
    path = _portfolio_path(sandbox_dir)
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=["ticker", "entry_price"])


def save_portfolio(portfolio, *, legacy_mode=False, sandbox_dir=None):
    require_legacy_sandbox(legacy_mode, "execution.paper_trader.save_portfolio")
    path = _portfolio_path(sandbox_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    portfolio.to_csv(path, index=False)


def paper_trade(signals, prices, *, legacy_mode=False, sandbox_dir=None):
    require_legacy_sandbox(legacy_mode, "execution.paper_trader.paper_trade")

    if sandbox_dir is None:
        with legacy_sandbox("execution.paper_trader.paper_trade") as sandbox:
            return paper_trade(
                signals,
                prices,
                legacy_mode=True,
                sandbox_dir=sandbox,
            )

    portfolio = load_portfolio(legacy_mode=True, sandbox_dir=sandbox_dir)
    trades = []
    latest_date = signals.index[-1]
    latest_signals = signals.loc[latest_date]
    latest_prices = prices.loc[latest_date]
    held_tickers = set(portfolio["ticker"])

    for ticker in signals.columns:
        signal = latest_signals[ticker]
        price = latest_prices[ticker]

        if signal == 1 and ticker not in held_tickers:
            portfolio.loc[len(portfolio)] = [ticker, price]
            trades.append(
                {
                    "date": latest_date,
                    "ticker": ticker,
                    "action": "BUY",
                    "price": price,
                }
            )
            send_telegram_alert(
                f"BUY ALERT\nTicker: {ticker}\nPrice: {price}\nDate: {latest_date}",
                legacy_mode=True,
            )
            continue

        if signal != 1 and ticker in held_tickers:
            entry = portfolio.loc[
                portfolio["ticker"].eq(ticker),
                "entry_price",
            ].iloc[0]
            pnl = (price - entry) / entry
            trades.append(
                {
                    "date": latest_date,
                    "ticker": ticker,
                    "action": "SELL",
                    "price": price,
                    "pnl": pnl,
                }
            )
            send_telegram_alert(
                f"SELL ALERT\nTicker: {ticker}\nPrice: {price}\nPnL: {pnl:.2%}\nDate: {latest_date}",
                legacy_mode=True,
            )
            portfolio = portfolio[~portfolio["ticker"].eq(ticker)]

    save_portfolio(portfolio, legacy_mode=True, sandbox_dir=sandbox_dir)
    return pd.DataFrame(trades), portfolio
