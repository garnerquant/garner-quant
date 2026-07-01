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


def holding_period_label(entry_date, exit_date):
    entry = pd.to_datetime(entry_date, errors="coerce")
    exit_value = pd.to_datetime(exit_date, errors="coerce")

    if pd.isna(entry) or pd.isna(exit_value):
        return ""

    days = max(0, int((exit_value - entry).days))
    unit = "day" if days == 1 else "days"
    return f"{days} {unit}"


def calculate_cash(portfolio, journal=None):
    realised_pnl = 0

    if journal is not None and not journal.empty and "pnl" in journal.columns:
        realised_pnl = pd.to_numeric(
            journal["pnl"],
            errors="coerce"
        ).fillna(0).sum()

    if portfolio.empty or "position_value" not in portfolio.columns:
        return STARTING_CASH + realised_pnl

    invested = portfolio["position_value"].sum()
    return STARTING_CASH - invested + realised_pnl


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

    cash = calculate_cash(portfolio, journal)

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

            trade_id = f"{ticker}_{position['entry_date']}_SELL"

            trades.append(
                {
                    "trade_id": trade_id,
                    "date": latest_date,
                    "time": trade_time,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "action": "SELL",
                    "price": current_price,
                    "exit_price": current_price,
                    "reason": sell_reason,
                    "position_value": value,
                    "value": value,
                    "shares": position["shares"],
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                    "holding_period": holding_period_label(
                        position["entry_date"],
                        latest_date,
                    ),
                    "justification": [
                        "Exit condition triggered",
                        "Trade recorded in journal",
                        "Portfolio updated",
                    ],
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

            trade_id = f"{ticker}_{latest_date}_BUY"

            cash -= position_value

            trades.append(
                {
                    "trade_id": trade_id,
                    "date": latest_date,
                    "time": trade_time,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "action": "BUY",
                    "price": price,
                    "entry_price": price,
                    "reason": "SIGNAL ENTRY",
                    "position_value": position_value,
                    "value": position_value,
                    "shares": shares,
                    "stop_loss": stop_losses[ticker],
                    "take_profit": take_profits[ticker],
                    "justification": [
                        "Signal passed",
                        "Weight assigned",
                        "Risk level available",
                        "Position added to paper portfolio",
                    ],
                }
            )

    save_portfolio(portfolio)
    save_trade_journal(journal)
    save_transaction_log(transaction_log)
    save_trade_snapshots(snapshots)

    trades_df = pd.DataFrame(trades)
    notification_summary = {
        "sent": 0,
        "skipped": 0,
        "errors": [],
    }

    if trades:
        try:
            from notifications.alert_notifier import notify_trade_events

            notification_summary = notify_trade_events(trades)
        except Exception as exc:
            print(f"Trade notification failed after trade save: {exc}")

    trades_df.attrs["notification_summary"] = notification_summary

    return portfolio, journal, trades_df


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
