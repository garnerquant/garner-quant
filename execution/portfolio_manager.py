import pandas as pd
from pathlib import Path
from decimal import Decimal
from config import (
    ASSETS,
    MIN_HOLD_DAYS_FOR_SIGNAL_EXIT,
    SELL_CONFIRMATION_RUNS,
    STARTING_CASH,
)
from execution.broker_account import load_account, update_account
from execution.accounting import broker_values_from_ledger_and_holdings
from execution.accounting import authoritative_ledger_accounting
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from execution.trade_ledger import (
    LEDGER_FILE,
    build_trade_event,
    prepare_trade_ledger_append,
)
from datetime import datetime, timezone
import json

from risk_engine.authorization import verify_risk_authorization
from canonical_accounting.observation import observe_monitor_only_evaluation
from risk_engine.configuration import load_risk_configuration
from risk_engine.engine import PreTradeRiskEngine
from risk_engine.integration import build_order_proposal, build_production_risk_context

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

TRADE_JOURNAL_COLUMNS = [
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

TRANSACTION_LOG_COLUMNS = [
    "date",
    "action",
    "ticker",
    "price",
    "shares",
    "value",
    "reason",
]

TRADE_SNAPSHOT_COLUMNS = [
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
    atomic_write_csv_frames({Path(PORTFOLIO_FILE): portfolio[PORTFOLIO_COLUMNS]})


def load_trade_journal():
    if Path(TRADE_JOURNAL_FILE).exists():
        journal = pd.read_csv(TRADE_JOURNAL_FILE)

        for col in TRADE_JOURNAL_COLUMNS:
            if col not in journal.columns:
                journal[col] = ""

        return journal[TRADE_JOURNAL_COLUMNS]

    return pd.DataFrame(columns=TRADE_JOURNAL_COLUMNS)


def save_trade_journal(journal):
    atomic_write_csv_frames({Path(TRADE_JOURNAL_FILE): journal[TRADE_JOURNAL_COLUMNS]})


def load_transaction_log():
    if Path(TRANSACTION_LOG_FILE).exists():
        log = pd.read_csv(TRANSACTION_LOG_FILE)

        for col in TRANSACTION_LOG_COLUMNS:
            if col not in log.columns:
                log[col] = ""

        return log[TRANSACTION_LOG_COLUMNS]

    return pd.DataFrame(columns=TRANSACTION_LOG_COLUMNS)


def save_transaction_log(log):
    atomic_write_csv_frames({Path(TRANSACTION_LOG_FILE): log[TRANSACTION_LOG_COLUMNS]})


def load_trade_snapshots():
    if Path(TRADE_SNAPSHOTS_FILE).exists():
        snapshots = pd.read_csv(TRADE_SNAPSHOTS_FILE)

        for col in TRADE_SNAPSHOT_COLUMNS:
            if col not in snapshots.columns:
                snapshots[col] = ""

        return snapshots[TRADE_SNAPSHOT_COLUMNS]

    return pd.DataFrame(columns=TRADE_SNAPSHOT_COLUMNS)


def save_trade_snapshots(snapshots):
    atomic_write_csv_frames({Path(TRADE_SNAPSHOTS_FILE): snapshots[TRADE_SNAPSHOT_COLUMNS]})


def commit_trade_state(
    *,
    ledger_events,
    portfolio,
    journal,
    transaction_log,
    snapshots,
    authorizations=None,
    authorization_now=None,
    risk_configuration=None,
):
    authorizations = list(authorizations or [])
    if ledger_events:
        if len(authorizations) != len(ledger_events):
            raise RuntimeError("every ledger event requires one central risk authorization")
        configuration = risk_configuration or load_risk_configuration()
        for event, authorization in zip(ledger_events, authorizations):
            proposal, decision = authorization
            verify_risk_authorization(
                proposal,
                decision,
                configuration=configuration,
                now=authorization_now,
            )
            if (
                str(event.get("ticker")) != proposal.symbol
                or str(event.get("action")) != proposal.side
                or Decimal(str(event.get("shares"))) != proposal.quantity
                or Decimal(str(event.get("price")))
                != Decimal(str(proposal.metadata.get("reference_price")))
            ):
                raise RuntimeError("approved proposal does not match ledger event")
    frames_by_path = {
        Path(LEDGER_FILE): prepare_trade_ledger_append(ledger_events),
        Path(PORTFOLIO_FILE): portfolio[PORTFOLIO_COLUMNS],
        Path(TRADE_JOURNAL_FILE): journal[TRADE_JOURNAL_COLUMNS],
        Path(TRANSACTION_LOG_FILE): transaction_log[TRANSACTION_LOG_COLUMNS],
        Path(TRADE_SNAPSHOTS_FILE): snapshots[TRADE_SNAPSHOT_COLUMNS],
    }
    return atomic_write_csv_frames(frames_by_path)


def _position_shares_by_ticker(frame):
    if frame is None or frame.empty:
        return {}
    data = frame.copy()
    data["ticker"] = data["ticker"].fillna("").astype(str).str.strip().str.upper()
    data["shares"] = pd.to_numeric(data["shares"], errors="coerce").fillna(0.0)
    return data[data["ticker"].ne("")].groupby("ticker")["shares"].sum().to_dict()


def append_portfolio_position(portfolio, values):
    """Append one position without relying on potentially sparse row labels."""
    updated = portfolio.reset_index(drop=True).copy()
    ticker = str(values[0]).strip()
    existing = updated.get("ticker", pd.Series(dtype=str)).fillna("").astype(str)
    if ticker and existing.str.strip().eq(ticker).any():
        raise ValueError(f"Refusing duplicate open portfolio position for {ticker}")
    updated.loc[len(updated)] = values
    return updated


def assert_portfolio_matches_ledger(portfolio, tolerance=1e-6):
    accounting = authoritative_ledger_accounting()
    if accounting is None:
        return

    open_lots = accounting["open_lots"]
    ledger_positions = _position_shares_by_ticker(open_lots)
    portfolio_positions = _position_shares_by_ticker(portfolio)
    mismatches = []

    for ticker in sorted(set(ledger_positions) | set(portfolio_positions)):
        ledger_shares = float(ledger_positions.get(ticker, 0.0))
        portfolio_shares = float(portfolio_positions.get(ticker, 0.0))
        if abs(ledger_shares - portfolio_shares) > tolerance:
            mismatches.append(
                f"{ticker}: ledger={ledger_shares:.12g}, portfolio={portfolio_shares:.12g}"
            )

    if mismatches:
        raise RuntimeError(
            "Refusing paper execution because ledger open lots do not match "
            "paper_portfolio_v3.csv shares: "
            + "; ".join(mismatches)
        )


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


def date_string(value):
    timestamp = pd.to_datetime(value, errors="coerce")
    if not pd.isna(timestamp):
        return timestamp.strftime("%Y-%m-%d")

    if value is None:
        return ""

    return str(value)


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
    atomic_write_json(
        payload,
        DECISION_TRACE_FILE,
        json_kwargs={"indent": 2, "default": str},
    )
    return payload


def trade_currency(ticker):
    asset_config = ASSETS.get(str(ticker), {})
    return str(asset_config.get("listing_currency") or "UNKNOWN")


def update_portfolio(
    signals,
    prices,
    weights,
    risk_levels,
    *,
    eligible_symbols=None,
    bar_identities=None,
    bar_timestamps=None,
    risk_engine=None,
    risk_context_factory=None,
    shadow_mode=False,
):
    eligible_symbols = set(eligible_symbols or signals.columns)
    bar_identities = dict(bar_identities or {})
    bar_timestamps = dict(bar_timestamps or {})
    central_risk = risk_engine or PreTradeRiskEngine()
    context_factory = risk_context_factory or build_production_risk_context
    portfolio = load_portfolio()
    assert_portfolio_matches_ledger(portfolio)
    journal = load_trade_journal()
    transaction_log = load_transaction_log()
    snapshots = load_trade_snapshots()
    ledger_events = []
    authorizations = []
    risk_decisions = []

    latest_date = signals.index[-1]
    trade_date = date_string(latest_date)
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

        if ticker not in eligible_symbols:
            continue

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
            bar_identities.get(ticker, trace_timestamp),
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
            trade_id = f"{ticker}_{position['entry_date']}_SELL"

            bar_timestamp = bar_timestamps.get(ticker)
            if not bar_timestamp:
                if ticker in decisions:
                    decisions[ticker]["reason"] = "scheduler bar timestamp unavailable"
                continue
            proposal = build_order_proposal(
                proposal_id=trade_id,
                signal_id=bar_identities.get(ticker, ""),
                symbol=ticker,
                side="SELL",
                quantity=position["shares"],
                source_bar_timestamp=bar_timestamp,
                reference_price=current_price,
                stop_price=stop_loss,
                reason=sell_reason,
                correlation_id=run_id,
                strategy_timestamp=datetime.now(timezone.utc),
            )
            context_kwargs = {
                "reference_price": current_price,
                "reference_price_timestamp": bar_timestamp,
            }
            if shadow_mode:
                context_kwargs["shadow_mode"] = True
            risk_context = context_factory(proposal, **context_kwargs)
            risk_decision = central_risk.evaluate(proposal, risk_context)
            risk_decisions.append(risk_decision)
            if shadow_mode:
                observe_monitor_only_evaluation(proposal, risk_context, risk_decision)
            if shadow_mode and risk_decision.approved:
                raise RuntimeError("shadow mode received an executable approval")
            if not risk_decision.approved:
                if ticker in decisions:
                    decisions[ticker]["reason"] = risk_decision.primary_reason_code.lower()
                    decisions[ticker]["details"]["risk_decision_id"] = risk_decision.decision_id
                    decisions[ticker]["details"]["risk_status"] = risk_decision.status.value
                continue
            authorizations.append((proposal, risk_decision))

            journal.loc[len(journal)] = [
                trade_date,
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
                trade_date,
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

            ledger_event = build_trade_event(
                timestamp=timestamp,
                trade_date=trade_date,
                trade_time=trade_time,
                ticker=ticker,
                action="SELL",
                shares=position["shares"],
                price=current_price,
                value=value,
                currency=trade_currency(ticker),
                reason=sell_reason,
                legacy_trade_id=trade_id,
                run_id=run_id,
                position_id=f"{ticker}_{position['entry_date']}",
                pnl=pnl,
                pnl_percent=pnl_percent,
            )
            ledger_events.append(ledger_event)

            trades.append(
                {
                    "event_id": ledger_event["event_id"],
                    "trade_id": trade_id,
                    "date": trade_date,
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
                        "event_id": ledger_event["event_id"],
                        "price": json_safe(current_price),
                        "shares": json_safe(position["shares"]),
                        "position_value": json_safe(value),
                        "pnl": json_safe(pnl),
                        "pnl_percent": json_safe(pnl_percent),
                    }
                )

            portfolio = portfolio[
                portfolio["ticker"] != ticker
            ].reset_index(drop=True)

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

            trade_id = f"{ticker}_{trade_date}_BUY"
            bar_timestamp = bar_timestamps.get(ticker)
            if not bar_timestamp:
                if ticker in decisions:
                    decisions[ticker]["reason"] = "scheduler bar timestamp unavailable"
                continue
            proposal = build_order_proposal(
                proposal_id=trade_id,
                signal_id=bar_identities.get(ticker, ""),
                symbol=ticker,
                side="BUY",
                quantity=shares,
                source_bar_timestamp=bar_timestamp,
                reference_price=price,
                stop_price=stop_losses[ticker],
                reason="SIGNAL ENTRY",
                correlation_id=run_id,
                strategy_timestamp=datetime.now(timezone.utc),
            )
            context_kwargs = {
                "reference_price": price,
                "reference_price_timestamp": bar_timestamp,
            }
            if shadow_mode:
                context_kwargs["shadow_mode"] = True
            risk_context = context_factory(proposal, **context_kwargs)
            risk_decision = central_risk.evaluate(proposal, risk_context)
            risk_decisions.append(risk_decision)
            if shadow_mode:
                observe_monitor_only_evaluation(proposal, risk_context, risk_decision)
            if shadow_mode and risk_decision.approved:
                raise RuntimeError("shadow mode received an executable approval")
            if not risk_decision.approved:
                if ticker in decisions:
                    decisions[ticker]["reason"] = risk_decision.primary_reason_code.lower()
                    decisions[ticker]["details"]["risk_decision_id"] = risk_decision.decision_id
                    decisions[ticker]["details"]["risk_status"] = risk_decision.status.value
                continue
            authorizations.append((proposal, risk_decision))

            portfolio_value_before = (
                cash + portfolio["position_value"].sum()
                if not portfolio.empty
                else cash
            )

            portfolio = append_portfolio_position(portfolio, [
                ticker,
                trade_date,
                price,
                shares,
                position_value,
                stop_losses[ticker],
                take_profits[ticker],
                0,
                "",
            ])

            now = datetime.now()
            trade_time = now.strftime("%H:%M:%S")
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            transaction_log.loc[len(transaction_log)] = [
                trade_date,
                "BUY",
                ticker,
                price,
                shares,
                position_value,
                "SIGNAL ENTRY",
            ]

            journal.loc[len(journal)] = [
                trade_date,
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
                f"{ticker}_{trade_date}_BUY",
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
            ledger_event = build_trade_event(
                timestamp=timestamp,
                trade_date=trade_date,
                trade_time=trade_time,
                ticker=ticker,
                action="BUY",
                shares=shares,
                price=price,
                value=position_value,
                currency=trade_currency(ticker),
                reason="SIGNAL ENTRY",
                legacy_trade_id=trade_id,
                run_id=run_id,
                position_id=f"{ticker}_{trade_date}",
            )
            ledger_events.append(ledger_event)

            trades.append(
                {
                    "event_id": ledger_event["event_id"],
                    "trade_id": trade_id,
                    "date": trade_date,
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
                        "event_id": ledger_event["event_id"],
                        "price": json_safe(price),
                        "shares": json_safe(shares),
                        "position_value": json_safe(position_value),
                        "cash_after_trade": json_safe(cash),
                    }
                )

    if not shadow_mode:
        commit_trade_state(
            ledger_events=ledger_events,
            portfolio=portfolio,
            journal=journal,
            transaction_log=transaction_log,
            snapshots=snapshots,
            authorizations=authorizations,
            authorization_now=datetime.now(timezone.utc),
            risk_configuration=central_risk.configuration,
        )

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
        "shadow" if shadow_mode else "paper_execution",
        len(decision_trace),
        len(trades),
        decision_trace,
    )
    trades_df.attrs["decision_trace"] = decision_trace
    trades_df.attrs["risk_decisions"] = risk_decisions
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

    holdings_for_accounting = pd.DataFrame(
        [
            {
                "ticker": row["ticker"],
                "market_value": row["current_value"],
            }
            for row in rows
        ]
    )
    journal = load_trade_journal()
    broker_values = broker_values_from_ledger_and_holdings(
        holdings=holdings_for_accounting,
        portfolio=portfolio,
        journal=journal,
    )
    cash = broker_values["cash"]
    realised_pnl = broker_values["realised_pnl"]
    total_value = broker_values["portfolio_value"]
    unrealised_pnl = broker_values["unrealised_pnl"]

    account = load_account()

    update_account(
        account,
        cash,
        broker_values["positions_value"],
        realised_pnl,
        unrealised_pnl,
    )

    return {
        "date": latest_date,
        "cash": cash,
        "positions_value": broker_values["positions_value"],
        "total_value": total_value,
        "unrealised_pnl": unrealised_pnl,
        "positions": rows,
    }
