import pandas as pd
import time

from config import ASSETS, BENCHMARK_TICKER

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
from reporting.trade_analytics import print_trade_analytics
from execution.broker_account import broker_summary
from execution.supabase_sync import sync_broker_account, sync_holdings, sync_30_day_tracker, sync_holdings_history, sync_trade_journal, sync_signals
from execution.atomic_io import atomic_write_csv_frames
from execution.trade_audit import ledger_open_positions
from execution.trade_ledger import load_trade_ledger
from execution.trade_reports import write_authoritative_trade_reports
from reporting.holdings_report import create_holdings_report, print_holdings_report
from reporting.paper_performance import (
    update_30_day_tracker,
    calculate_30_day_performance,
    print_30_day_performance
)
from runtime.locks import acquire_execution_lock


def _run_main_unlocked(show_charts=True, send_telegram=True, sync_remote=True):
    run_started = time.perf_counter()
    pipeline_events = []

    def record_event(event_type, message, details=None):
        pipeline_events.append(
            {
                "type": event_type,
                "severity": "info",
                "message": message,
                "details": details or {},
            }
        )

    from config import BENCHMARK_TICKER

    tickers = list(ASSETS.keys()) + [BENCHMARK_TICKER]

    print("Downloading market data...")
    market_data = download_market_data(tickers)
    record_event(
        "Downloaded Prices",
        "Downloaded latest market data.",
        {"symbols": tickers},
    )

    prices = get_price_field(market_data, "Close")
    highs = get_price_field(market_data, "High")
    lows = get_price_field(market_data, "Low")
    volumes = get_price_field(market_data, "Volume")

    asset_tickers = list(ASSETS.keys())

    asset_prices = prices[asset_tickers]
    asset_highs = highs[asset_tickers]
    asset_lows = lows[asset_tickers]
    asset_volumes = volumes[asset_tickers]

    print("Building signals...")
    signals = build_signals(asset_prices, asset_volumes)
    latest_signals = signals.loc[signals.index[-1]]
    buy_signals = int((latest_signals == 1).sum())
    sell_signals = int((latest_signals == 0).sum())
    hold_signals = int(len(latest_signals) - buy_signals - sell_signals)
    record_event(
        "Generated Signals",
        "Generated latest strategy signals.",
        {
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "hold_signals": hold_signals,
        },
    )
    print("Building risk levels...")
    risk_levels = build_risk_levels(asset_prices, asset_highs, asset_lows)
    record_event("Built Risk Levels", "Calculated stop loss and take profit levels.")

    print("Building portfolio weights...")
    weights = build_weights(signals, prices, risk_levels)
    record_event("Calculated Weights", "Calculated portfolio weights.")

    print("Running backtest...")
    portfolio = run_backtest(asset_prices, weights, risk_levels)
    record_event("Ran Backtest", "Updated backtest portfolio series.")

    print("Updating Portfolio Manager V3...")
    paper_portfolio, trade_journal, v3_trades = update_portfolio(
        signals,
        prices,
        weights,
        risk_levels
    )
    record_event(
        "Paper Portfolio Updated",
        "Updated paper portfolio, trade journal, and transaction log.",
        {"paper_trades": len(v3_trades)},
    )

    for _, trade in v3_trades.iterrows():
        record_event(
            f"{trade.get('action', 'TRADE')} {trade.get('ticker', '')}".strip(),
            (
                f"{trade.get('action', 'TRADE')} "
                f"{trade.get('ticker', 'UNKNOWN')} recorded in paper portfolio."
            ),
            {
                "ticker": trade.get("ticker"),
                "action": trade.get("action"),
                "price": trade.get("price"),
                "shares": trade.get("shares"),
            },
        )

    summary = portfolio_summary(paper_portfolio, prices)

    holdings_report = create_holdings_report(
        paper_portfolio,
        prices
    )

    print("Saving CSV files...")
    atomic_write_csv_frames(
        {
            "prices_v2.csv": prices,
            "signals_v2.csv": signals,
            "weights_v2.csv": weights,
            "risk_levels_v2.csv": risk_levels,
            "portfolio_v2.csv": portfolio,
            "paper_portfolio_v3.csv": paper_portfolio,
            "trade_journal_v3.csv": trade_journal,
            "v3_trades.csv": v3_trades,
        },
        to_csv_kwargs_by_path={
            "prices_v2.csv": {"index": True},
            "signals_v2.csv": {"index": True},
            "weights_v2.csv": {"index": True},
            "risk_levels_v2.csv": {"index": True},
            "portfolio_v2.csv": {"index": True},
        },
    )
    ledger = load_trade_ledger()
    audit_trail, trade_stats = write_authoritative_trade_reports(
        legacy_journal=trade_journal,
        audit_path="trade_audit_trail.csv",
        analytics_path="trade_analytics_v3.csv",
    )
    print("Saved trade_audit_trail.csv")
    atomic_write_csv_frames({"holdings_report.csv": holdings_report})
    record_event("Saved Reports", "Saved portfolio, signal, audit, and holding files.")

    fundamental_scores = pd.read_csv("fundamental_scores.csv")

    report = calculate_performance(portfolio)
    benchmark_prices = prices[BENCHMARK_TICKER].dropna()

    portfolio_return = report["total_return"]

    benchmark_return = float(
        ((benchmark_prices.iloc[-1] / benchmark_prices.iloc[0]) - 1)
    )

    benchmark_stats = {
        "ticker": BENCHMARK_TICKER,
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "alpha": portfolio_return - benchmark_return
    }

    print_performance(report)
    open_positions = len(ledger_open_positions(ledger))
    print_trade_analytics(trade_stats)

    signal_rows = create_signal_report(signals, weights)
    print_signal_report(signal_rows)
    print_holdings_report(holdings_report)

    atomic_write_csv_frames({"signal_report_v2.csv": pd.DataFrame(signal_rows)})

    broker = broker_summary()
    tracker = update_30_day_tracker(broker, benchmark_stats)
    paper_30_day = calculate_30_day_performance(tracker)
    print_30_day_performance(paper_30_day)

    if sync_remote:
        sync_broker_account()
        sync_holdings()
        sync_30_day_tracker()
        sync_holdings_history()
        sync_trade_journal()
        sync_signals()

    telegram_message = build_telegram_message(
        report,
        signal_rows,
        fundamental_scores,
        summary,
        v3_trades,
        trade_stats,
        broker,
        holdings_report,
        benchmark_stats
    )

    if send_telegram:
        print("Sending Telegram update...")
        send_message(telegram_message)
        record_event("Telegram Notification Sent", "Sent daily Telegram report.")

    if show_charts:
        show_dashboard(portfolio, weights, report)

    print("\nGarner Quant V2.1 run complete.")
    trade_notification_summary = v3_trades.attrs.get(
        "notification_summary",
        {},
    )
    decision_trace_summary = v3_trades.attrs.get(
        "decision_trace_summary",
        {},
    )
    trade_notifications_sent = int(
        trade_notification_summary.get("sent", 0)
    )
    if trade_notifications_sent:
        record_event(
            "Telegram Notification Sent",
            "Sent trade notification alerts.",
            {"sent": trade_notifications_sent},
        )

    return {
        "signals_count": len(signal_rows),
        "symbols_scanned": len(asset_tickers),
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_signals": hold_signals,
        "trades_recorded": len(v3_trades),
        "paper_trades": len(v3_trades),
        "portfolio_changed": bool(len(v3_trades) > 0),
        "trade_notifications_sent": trade_notifications_sent,
        "notifications_sent": trade_notifications_sent,
        "decision_trace_count": int(
            decision_trace_summary.get("decision_trace_count", 0) or 0
        ),
        "no_trade_count": int(
            decision_trace_summary.get("no_trade_count", 0) or 0
        ),
        "trade_count": int(
            decision_trace_summary.get("trade_count", 0) or 0
        ),
        "top_no_trade_reasons": decision_trace_summary.get(
            "top_no_trade_reasons",
            {},
        ),
        "execution_time_seconds": round(time.perf_counter() - run_started, 2),
        "events": pipeline_events,
        "latest_paper_trade": (
            v3_trades.iloc[-1].to_dict()
            if len(v3_trades)
            else None
        ),
    }


def main(show_charts=True, send_telegram=True, sync_remote=True):
    execution_lock = acquire_execution_lock(context="main_v2.main")

    if not execution_lock.acquired:
        print("Another execution is already running")
        return {
            "status": "skipped",
            "reason": "Another execution is already running",
            "signals_count": 0,
            "symbols_scanned": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "hold_signals": 0,
            "trades_recorded": 0,
            "paper_trades": 0,
            "portfolio_changed": False,
            "trade_notifications_sent": 0,
            "notifications_sent": 0,
            "decision_trace_count": 0,
            "no_trade_count": 0,
            "trade_count": 0,
            "top_no_trade_reasons": {},
            "execution_time_seconds": 0,
            "events": [
                {
                    "type": "Execution Skipped",
                    "severity": "warning",
                    "message": "Another execution is already running",
                    "details": execution_lock.existing,
                }
            ],
            "latest_paper_trade": None,
        }

    try:
        return _run_main_unlocked(
            show_charts=show_charts,
            send_telegram=send_telegram,
            sync_remote=sync_remote,
        )
    finally:
        execution_lock.release()


if __name__ == "__main__":
    main()
