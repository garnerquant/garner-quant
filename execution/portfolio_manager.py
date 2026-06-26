import pandas as pd
from pathlib import Path
from config import STARTING_CASH
from execution.broker_account import load_account, update_account
from datetime import datetime

PORTFOLIO_FILE = "paper_portfolio_v3.csv"
TRADE_JOURNAL_FILE = "trade_journal_v3.csv"
TRANSACTION_LOG_FILE = "trade_transactions_v1.csv"
TRADE_SNAPSHOTS_FILE = "trade_snapshots.csv"


def load_portfolio():
    if Path(PORTFOLIO_FILE).exists():
        return pd.read_csv(PORTFOLIO_FILE)

    return pd.DataFrame(
        columns=[
            "ticker",
            "entry_date",
            "entry_price",
            "shares",
            "position_value",
            "stop_loss",
            "take_profit",
        ]
    )


def save_portfolio(portfolio):
    portfolio.to_csv(PORTFOLIO_FILE, index=False)


def load_trade_journal():
    columns = [
        "date",
        "time",
        "action",
        "ticker",
        "price",
        "shares",
        "value",
        "pnl",
        "pnl_percent",
        "reason",
    ]

    if Path(TRADE_JOURNAL_FILE).exists():
        journal = pd.read_csv(TRADE_JOURNAL_FILE)

        for col in columns:
            if col not in journal.columns:
                journal[col] = ""

        return journal[columns]

    return pd.DataFrame(columns=columns)


def save_trade_journal(journal):
    journal.to_csv(TRADE_JOURNAL_FILE, index=False)


def load_transaction_log():
    columns = [
        "date",
        "action",
        "ticker",
        "price",
        "shares",
        "value",
        "reason",
    ]

    if Path(TRANSACTION_LOG_FILE).exists():
        log = pd.read_csv(TRANSACTION_LOG_FILE)

        for col in columns:
            if col not in log.columns:
                log[col] = ""

        return log[columns]

    return pd.DataFrame(columns=columns)


def save_transaction_log(log):
    log.to_csv(TRANSACTION_LOG_FILE, index=False)


def load_trade_snapshots():
    columns = [
        "trade_id",
        "event",
        "ticker",
        "timestamp",
        "price",
        "shares",
        "position_value",
        "cash",
        "portfolio_value",
        "portfolio_weight",
        "signal",
        "reason",
        "stop_loss",
        "take_profit",
    ]

    if Path(TRADE_SNAPSHOTS_FILE).exists():
        snapshots = pd.read_csv(TRADE_SNAPSHOTS_FILE)

        for col in columns:
            if col not in snapshots.columns:
                snapshots[col] = ""

        return snapshots[columns]

    return pd.DataFrame(columns=columns)


def save_trade_snapshots(snapshots):
    snapshots.to_csv(TRADE_SNAPSHOTS_FILE, index=False)


def rebuild_trade_snapshots_from_journal():
    journal = load_trade_journal()

    columns = [
        "trade_id",
        "event",
        "ticker",
        "timestamp",
        "price",
        "shares",
        "position_value",
        "cash",
        "portfolio_value",
        "portfolio_weight",
        "signal",
        "reason",
        "stop_loss",
        "take_profit",
    ]

    snapshots = pd.DataFrame(columns=columns)

    if journal.empty:
        save_trade_snapshots(snapshots)
        return snapshots

    for _, row in journal.iterrows():
        ticker = row.get("ticker", "")
        action = str(row.get("action", "")).upper()
        date = row.get("date", "")
        time = row.get("time", "")

        if action not in ["BUY", "SELL"]:
            continue

        timestamp = f"{date} {time}".strip()

        price = row.get("price", 0)
        shares = row.get("shares", 0)
        value = row.get("value", 0)
        reason = row.get("reason", "")

        snapshots.loc[len(snapshots)] = [
            f"{ticker}_{timestamp}_{action}",
            action,
            ticker,
            timestamp,
            price,
            shares,
            value,
            "",
            "",
            "",
            "",
            reason,
            "",
            "",
        ]

    save_trade_snapshots(snapshots)
    return snapshots


def calculate_cash(portfolio):
    if portfolio.empty or "position_value" not in portfolio.columns:
        return STARTING_CASH

    invested = portfolio["position_value"].sum()
    return STARTING_CASH - invested


def update_portfolio(signals, prices, weights, risk_levels):
    portfolio = load_portfolio()
    journal = load_trade_journal()
    transaction_log = load_transaction_log()
    snapshots = load_trade_snapshots()

    latest_date = signals.index[-1]
    latest_signals = signals.loc[latest_date]
    latest_prices = prices.loc[latest_date]
    latest_weights = weights.loc[latest_date]

    stop_losses = risk_levels["stop_loss"].loc[latest_date]
    take_profits = risk_levels["take_profit"].loc[latest_date]

    trades = []
    exited_tickers = set()

    held_tickers = set(portfolio["ticker"]) if not portfolio.empty else set()

    cash = calculate_cash(portfolio)

    # SELL logic
    for _, position in portfolio.copy().iterrows():
        ticker = position["ticker"]

        if ticker not in latest_prices.index:
            continue

        current_price = latest_prices[ticker]
        signal = latest_signals[ticker]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        sell_reason = None

        if current_price <= stop_loss:
            sell_reason = "STOP LOSS"

        elif current_price >= take_profit:
            sell_reason = "TAKE PROFIT"

        elif signal == 0:
            sell_reason = "SIGNAL EXIT"

        if sell_reason is not None:
            pnl = (
                current_price - position["entry_price"]
            ) * position["shares"]

            pnl_percent = (
                current_price / position["entry_price"]
            ) - 1

            now = datetime.now()
            trade_time = now.strftime("%H:%M:%S")
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

            value = current_price * position["shares"]

            journal.loc[len(journal)] = [
                latest_date,
                trade_time,
                "SELL",
                ticker,
                current_price,
                position["shares"],
                value,
                pnl,
                pnl_percent,
                sell_reason,
            ]

            transaction_log.loc[len(transaction_log)] = [
                latest_date,
                "SELL",
                ticker,
                current_price,
                position["shares"],
                value,
                sell_reason,
            ]

            portfolio_value_before_sell = (
                cash + portfolio["position_value"].sum()
                if not portfolio.empty
                else cash
            )

            snapshots.loc[len(snapshots)] = [
                f"{ticker}_{position['entry_date']}_SELL",
                "SELL",
                ticker,
                timestamp,
                current_price,
                position["shares"],
                value,
                cash + value,
                portfolio_value_before_sell,
                0,
                signal,
                sell_reason,
                stop_loss,
                take_profit,
            ]

            trades.append(
                {
                    "date": latest_date,
                    "time": trade_time,
                    "ticker": ticker,
                    "action": "SELL",
                    "price": current_price,
                    "reason": sell_reason,
                    "position_value": value,
                    "shares": position["shares"],
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                }
            )

            portfolio = portfolio[
                portfolio["ticker"] != ticker
            ]

            cash += value
            exited_tickers.add(ticker)

    held_tickers = set(portfolio["ticker"]) if not portfolio.empty else set()

    # BUY logic
    for ticker in signals.columns:
        signal = latest_signals[ticker]
        weight = latest_weights[ticker]

        if ticker not in latest_prices.index:
            continue

        price = latest_prices[ticker]

        if (
            signal == 1
            and ticker not in held_tickers
            and ticker not in exited_tickers
            and weight > 0
        ):
            position_value = STARTING_CASH * weight

            if position_value > cash:
                position_value = cash

            if position_value <= 0:
                continue

            shares = position_value / price

            portfolio_value_before = (
                cash + portfolio["position_value"].sum()
                if not portfolio.empty
                else cash
            )

            portfolio.loc[len(portfolio)] = [
                ticker,
                latest_date,
                price,
                shares,
                position_value,
                stop_losses[ticker],
                take_profits[ticker],
            ]

            now = datetime.now()
            trade_time = now.strftime("%H:%M:%S")
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

            transaction_log.loc[len(transaction_log)] = [
                latest_date,
                "BUY",
                ticker,
                price,
                shares,
                position_value,
                "SIGNAL ENTRY",
            ]

            journal.loc[len(journal)] = [
                latest_date,
                trade_time,
                "BUY",
                ticker,
                price,
                shares,
                position_value,
                0,
                0,
                "SIGNAL ENTRY",
            ]

            snapshots.loc[len(snapshots)] = [
                f"{ticker}_{latest_date}_BUY",
                "BUY",
                ticker,
                timestamp,
                price,
                shares,
                position_value,
                cash,
                portfolio_value_before,
                weight,
                signal,
                "SIGNAL ENTRY",
                stop_losses[ticker],
                take_profits[ticker],
            ]

            cash -= position_value

            trades.append(
                {
                    "date": latest_date,
                    "time": trade_time,
                    "ticker": ticker,
                    "action": "BUY",
                    "price": price,
                    "reason": "SIGNAL ENTRY",
                    "position_value": position_value,
                    "shares": shares,
                }
            )

    save_portfolio(portfolio)
    save_trade_journal(journal)
    save_transaction_log(transaction_log)
    save_trade_snapshots(snapshots)

    # This backfills snapshots from the full journal too, so old trades have replay rows.
    rebuild_trade_snapshots_from_journal()

    return portfolio, journal, pd.DataFrame(trades)


def portfolio_summary(portfolio, prices):
    latest_date = prices.index[-1]
    latest_prices = prices.loc[latest_date]

    total_position_value = 0
    unrealised_pnl = 0

    rows = []

    for _, position in portfolio.iterrows():
        ticker = position["ticker"]
        current_price = latest_prices[ticker]

        current_value = current_price * position["shares"]

        pnl = current_value - position["position_value"]

        pnl_percent = (
            current_price / position["entry_price"]
        ) - 1

        total_position_value += current_value
        unrealised_pnl += pnl

        rows.append(
            {
                "ticker": ticker,
                "entry_price": position["entry_price"],
                "current_price": current_price,
                "shares": position["shares"],
                "current_value": current_value,
                "unrealised_pnl": pnl,
                "unrealised_pnl_percent": pnl_percent,
            }
        )

    journal = load_trade_journal()

    realised_pnl = 0

    if len(journal) > 0:
        realised_pnl = journal["pnl"].sum()

    cash = STARTING_CASH - portfolio["position_value"].sum() + realised_pnl

    total_value = cash + total_position_value

    account = load_account()

    update_account(
        account,
        cash,
        total_position_value,
        realised_pnl,
        unrealised_pnl,
    )

    return {
        "date": latest_date,
        "cash": cash,
        "positions_value": total_position_value,
        "total_value": total_value,
        "unrealised_pnl": unrealised_pnl,
        "positions": rows,
    }