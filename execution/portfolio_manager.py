import pandas as pd
from pathlib import Path
from config import (
    MIN_HOLD_DAYS_FOR_SIGNAL_EXIT,
    SELL_CONFIRMATION_RUNS,
    STARTING_CASH,
)
from execution.broker_account import load_account, update_account
from datetime import datetime
import json

PORTFOLIO_FILE = "paper_portfolio_v3.csv"
TRADE_JOURNAL_FILE = "trade_journal_v3.csv"
TRANSACTION_LOG_FILE = "trade_transactions_v1.csv"
TRADE_SNAPSHOTS_FILE = "trade_snapshots.csv"
DECISION_TRACE_FILE = Path("data") / "runtime_decision_trace.json"

PORTFOLIO_COLUMNS = [
    "ticker",
    "entry_date",
    "entry_price",
    "shares",
    "position_value",
    "stop_loss",
    "take_profit",
    "signal_exit_count",
    "last_signal_exit_check",
]


def load_portfolio():
    if Path(PORTFOLIO_FILE).exists():
        portfolio = pd.read_csv(PORTFOLIO_FILE)

        for col in PORTFOLIO_COLUMNS:
            if col not in portfolio.columns:
                portfolio[col] = 0 if col == "signal_exit_count" else ""

        portfolio["signal_exit_count"] = pd.to_numeric(
            portfolio["signal_exit_count"],
            errors="coerce",
        ).fillna(0).astype(int)
        portfolio["last_signal_exit_check"] = (
            portfolio["last_signal_exit_check"].fillna("").astype(str)
        )

        return portfolio[PORTFOLIO_COLUMNS]

    return pd.DataFrame(columns=PORTFOLIO_COLUMNS)


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


def holding_period_days(entry_date, exit_date):
    entry = pd.to_datetime(entry_date, errors="coerce")
    exit_value = pd.to_datetime(exit_date, errors="coerce")

    if pd.isna(entry) or pd.isna(exit_value):
        return 0

    return max(0, int((exit_value - entry).days))


def signal_exit_status(position, signal, latest_date, check_id):
    if signal == 1:
        return {
            "count": 0,
            "last_check": "",
            "confirmed": False,
            "hold_days": holding_period_days(position["entry_date"], latest_date),
            "reason": "signal restored",
        }

    current_count = int(position.get("signal_exit_count", 0) or 0)
    last_check = position.get("last_signal_exit_check", "")

    if signal != 0:
        return {
            "count": current_count,
            "last_check": last_check,
            "confirmed": False,
            "hold_days": holding_period_days(position["entry_date"], latest_date),
            "reason": "signal active",
        }

    if last_check != check_id:
        current_count += 1
        last_check = check_id

    hold_days = holding_period_days(position["entry_date"], latest_date)
    confirmed = (
        hold_days >= MIN_HOLD_DAYS_FOR_SIGNAL_EXIT
        and current_count >= SELL_CONFIRMATION_RUNS
    )

    if hold_days < MIN_HOLD_DAYS_FOR_SIGNAL_EXIT:
        reason = "minimum hold period not met"
    elif current_count < SELL_CONFIRMATION_RUNS:
        reason = "awaiting signal exit confirmation"
    else:
        reason = "confirmed signal exit"

    return {
        "count": current_count,
        "last_check": last_check,
        "confirmed": confirmed,
        "hold_days": hold_days,
        "reason": reason,
    }


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


def json_safe(value):
    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return value


def signal_label(value):
    if value == 1:
        return "BUY"
    if value == 0:
        return "SELL"
    return "HOLD"


def safe_lookup(series, key):
    try:
        if key in series.index:
            return json_safe(series[key])
    except Exception:
        pass
    return None


def current_weights_by_ticker(portfolio, cash):
    if portfolio.empty or "ticker" not in portfolio.columns:
        return {}

    position_values = pd.to_numeric(
        portfolio.get("position_value", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0)
    total_value = float(cash + position_values.sum())
    if total_value <= 0:
        return {}

    weights = {}
    for index, position in portfolio.iterrows():
        ticker = position.get("ticker")
        if pd.isna(ticker):
            continue
        weights[str(ticker)] = float(position_values.loc[index] / total_value)
    return weights


def decision_trace_record(
    timestamp,
    ticker,
    signal,
    current_holding,
    target_weight,
    current_weight,
    portfolio_decision="NO_TRADE",
    trade_action=None,
    trade_recorded=False,
    reason="unknown",
    details=None,
):
    return {
        "timestamp": timestamp,
        "ticker": ticker,
        "signal": signal_label(signal),
        "current_holding": bool(current_holding),
        "target_weight": json_safe(target_weight),
        "current_weight": json_safe(current_weight),
        "portfolio_decision": portfolio_decision,
        "trade_action": trade_action,
        "trade_recorded": bool(trade_recorded),
        "reason": reason,
        "details": details or {},
    }


def decision_trace_summary(decisions):
    no_trade_reasons = {}
    for decision in decisions:
        if decision.get("trade_recorded"):
            continue
        reason = decision.get("reason") or "unknown"
        no_trade_reasons[reason] = no_trade_reasons.get(reason, 0) + 1

    top_reasons = dict(
        sorted(
            no_trade_reasons.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
    )
    trade_count = len([d for d in decisions if d.get("trade_recorded")])

    return {
        "decision_trace_count": len(decisions),
        "no_trade_count": len(decisions) - trade_count,
        "trade_count": trade_count,
        "top_no_trade_reasons": top_reasons,
    }


def save_decision_trace(generated_at, run_id, mode, signals_count, trades_recorded, decisions):
    DECISION_TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "run_id": run_id,
        "mode": mode,
        "signals_count": int(signals_count),
        "trades_recorded": int(trades_recorded),
        "decisions": decisions,
    }
    payload.update(decision_trace_summary(decisions))
    DECISION_TRACE_FILE.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    return payload


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
    initial_portfolio = portfolio.copy()
    initial_held_tickers = set(initial_portfolio["ticker"]) if not initial_portfolio.empty else set()
    initial_weights = current_weights_by_ticker(initial_portfolio, cash)
    trace_timestamp = datetime.now().isoformat(timespec="seconds")
    run_id = f"{pd.Timestamp(latest_date).strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}"
    decisions = {}

    for ticker in signals.columns:
        signal = safe_lookup(latest_signals, ticker)
        target_weight = safe_lookup(latest_weights, ticker)
        current_holding = ticker in initial_held_tickers
        current_weight = initial_weights.get(ticker, 0.0 if current_holding else 0.0)
        details = {
            "price": safe_lookup(latest_prices, ticker),
            "stop_loss": safe_lookup(stop_losses, ticker),
            "take_profit": safe_lookup(take_profits, ticker),
        }

        if ticker not in latest_prices.index:
            reason = "risk data missing"
            details["missing"] = "price"
        elif signal == 0 and not current_holding:
            reason = "sell signal but not held"
        elif signal == 1 and current_holding:
            reason = "already held"
        elif signal == 1 and (target_weight is None or float(target_weight or 0) <= 0):
            reason = "insufficient target weight"
        elif signal == 1:
            reason = "unknown"
        else:
            reason = "no allocation change required"

        decisions[ticker] = decision_trace_record(
            trace_timestamp,
            ticker,
            signal,
            current_holding,
            target_weight,
            current_weight,
            reason=reason,
            details=details,
        )

    # SELL logic
    for position_index, position in portfolio.copy().iterrows():
        ticker = position["ticker"]

        if ticker not in latest_prices.index:
            if ticker in decisions:
                decisions[ticker]["reason"] = "risk data missing"
                decisions[ticker]["details"]["missing"] = "price"
            continue

        current_price = latest_prices[ticker]
        signal = latest_signals[ticker]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        sell_reason = None
        exit_status = signal_exit_status(
            position,
            signal,
            latest_date,
            trace_timestamp,
        )

        portfolio.loc[
            position_index,
            "signal_exit_count",
        ] = exit_status["count"]
        portfolio.loc[
            position_index,
            "last_signal_exit_check",
        ] = exit_status["last_check"]

        if ticker in decisions:
            decisions[ticker]["details"].update(
                {
                    "signal_exit_count": exit_status["count"],
                    "sell_confirmation_runs": SELL_CONFIRMATION_RUNS,
                    "hold_days": exit_status["hold_days"],
                    "min_hold_days_for_signal_exit": (
                        MIN_HOLD_DAYS_FOR_SIGNAL_EXIT
                    ),
                }
            )

        if current_price <= stop_loss:
            sell_reason = "STOP LOSS"

        elif current_price >= take_profit:
            sell_reason = "TAKE PROFIT"

        elif signal == 0 and exit_status["confirmed"]:
            sell_reason = "CONFIRMED SIGNAL EXIT"

        elif signal == 0 and ticker in decisions:
            decisions[ticker]["reason"] = exit_status["reason"]

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
            if ticker in decisions:
                decisions[ticker].update(
                    {
                        "portfolio_decision": "TRADE_EXECUTED",
                        "trade_action": "SELL",
                        "trade_recorded": True,
                        "reason": str(sell_reason).lower(),
                    }
                )
                decisions[ticker]["details"].update(
                    {
                        "trade_id": trade_id,
                        "price": json_safe(current_price),
                        "shares": json_safe(position["shares"]),
                        "position_value": json_safe(value),
                        "pnl": json_safe(pnl),
                        "pnl_percent": json_safe(pnl_percent),
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
            if ticker in decisions:
                decisions[ticker]["reason"] = "risk data missing"
                decisions[ticker]["details"]["missing"] = "price"
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
                if ticker in decisions:
                    decisions[ticker]["reason"] = "max positions reached"
                    decisions[ticker]["details"].update(
                        {
                            "cash": json_safe(cash),
                            "target_position_value": json_safe(STARTING_CASH * weight),
                        }
                    )
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
                0,
                "",
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
            if ticker in decisions:
                decisions[ticker].update(
                    {
                        "portfolio_decision": "TRADE_EXECUTED",
                        "trade_action": "BUY",
                        "trade_recorded": True,
                        "reason": "signal entry",
                    }
                )
                decisions[ticker]["details"].update(
                    {
                        "trade_id": trade_id,
                        "price": json_safe(price),
                        "shares": json_safe(shares),
                        "position_value": json_safe(position_value),
                        "cash_after_trade": json_safe(cash),
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
    decision_trace = list(decisions.values())
    trace_payload = save_decision_trace(
        trace_timestamp,
        run_id,
        "paper_execution",
        len(decision_trace),
        len(trades),
        decision_trace,
    )
    trades_df.attrs["decision_trace"] = decision_trace
    trades_df.attrs["decision_trace_summary"] = {
        key: trace_payload.get(key)
        for key in [
            "decision_trace_count",
            "no_trade_count",
            "trade_count",
            "top_no_trade_reasons",
        ]
    }

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
