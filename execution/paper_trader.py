import os
import requests
import pandas as pd
from pathlib import Path


PORTFOLIO_FILE = "paper_portfolio.csv"

def send_telegram_alert(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    print("BOT TOKEN EXISTS:", bool(bot_token))
    print("CHAT ID EXISTS:", bool(chat_id))

    if not bot_token or not chat_id:
        print("Missing Telegram environment variables")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=10
        )

        print("Telegram status:", response.status_code)
        print("Telegram response:", response.text)

    except Exception as e:
        print(f"Telegram alert failed: {e}")

def load_portfolio():

    if Path(PORTFOLIO_FILE).exists():

        return pd.read_csv(
            PORTFOLIO_FILE
        )

    return pd.DataFrame(
        columns=[
            "ticker",
            "entry_price"
        ]
    )


def save_portfolio(
    portfolio
):

    portfolio.to_csv(
        PORTFOLIO_FILE,
        index=False
    )


def paper_trade(
    signals,
    prices
):

    portfolio = load_portfolio()

    trades = []

    latest_date = signals.index[-1]

    latest_signals = signals.loc[
        latest_date
    ]

    latest_prices = prices.loc[
        latest_date
    ]

    held_tickers = set(
        portfolio["ticker"]
    )

    for ticker in signals.columns:

        signal = latest_signals[
            ticker
        ]

        price = latest_prices[
            ticker
        ]

        if signal == 1:

            if ticker not in held_tickers:

                portfolio.loc[
                    len(portfolio)
                ] = [

                    ticker,

                    price

                ]

                trades.append({

                    "date":
                    latest_date,

                    "ticker":
                    ticker,

                    "action":
                    "BUY",

                    "price":
                    price

                })
                send_telegram_alert(
                    f"🟢 BUY ALERT\nTicker: {ticker}\nPrice: {price}\nDate: {latest_date}"
                )

        else:

            if ticker in held_tickers:

                entry = portfolio[
                    portfolio[
                        "ticker"
                    ]

                    == ticker

                ][

                    "entry_price"

                ].iloc[0]

                pnl = (

                    price

                    -

                    entry

                ) / entry

                trades.append({

                    "date":
                    latest_date,

                    "ticker":
                    ticker,

                    "action":
                    "SELL",

                    "price":
                    price,

                    "pnl":
                    pnl

                })
                send_telegram_alert(
                    f"🔴 SELL ALERT\nTicker: {ticker}\nPrice: {price}\nPnL: {pnl:.2%}\nDate: {latest_date}"
                )

                portfolio = portfolio[

                    portfolio[
                        "ticker"
                    ]

                    != ticker

                ]

    save_portfolio(
        portfolio
    )

    return (

        pd.DataFrame(
            trades
        ),

        portfolio

    )
